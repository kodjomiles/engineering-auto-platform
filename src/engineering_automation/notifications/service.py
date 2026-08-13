"""Preference-aware, failure-isolated notification delivery."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from engineering_automation.notifications.deduplication import (
    DeduplicationStore,
    InMemoryDeduplicationStore,
)
from engineering_automation.notifications.models import (
    ContactPoint,
    DeliveryMode,
    DeliveryState,
    Notification,
    NotificationAttempt,
    NotificationPolicy,
    NotificationReport,
    RecipientPreferences,
)

NotificationProvider = Callable[[Notification, ContactPoint], Awaitable[Mapping[str, Any] | None]]
Clock = Callable[[], float]


class NotificationService:
    """Apply recipient policy and deliver through registered providers."""

    def __init__(
        self,
        providers: Mapping[str, NotificationProvider],
        *,
        deduplication_store: DeduplicationStore | None = None,
        monotonic: Clock = time.monotonic,
    ) -> None:
        normalized: dict[str, NotificationProvider] = {}
        for channel, provider in providers.items():
            normalized_channel = channel.strip().lower()
            if not normalized_channel:
                raise ValueError("provider channels cannot be empty")
            if normalized_channel in normalized:
                raise ValueError("provider channels must be unique after normalization")
            normalized[normalized_channel] = provider
        self._providers = normalized
        self._deduplication = deduplication_store or InMemoryDeduplicationStore()
        self._monotonic = monotonic

    async def publish(
        self,
        notification: Notification,
        recipients: Sequence[RecipientPreferences],
        policy: NotificationPolicy | None = None,
    ) -> NotificationReport:
        active_policy = policy or NotificationPolicy()
        self._validate_recipients(recipients)
        if not recipients:
            return NotificationReport(notification.notification_id, False, ())

        if notification.deduplication_key is not None:
            claimed = await self._deduplication.claim(
                notification.deduplication_key,
                active_policy.deduplication_window_seconds,
            )
            if not claimed:
                return NotificationReport(notification.notification_id, True, ())

        semaphore = asyncio.Semaphore(active_policy.max_concurrency)
        if active_policy.mode is DeliveryMode.FAN_OUT:
            attempts = await self._fan_out(notification, recipients, semaphore)
        else:
            attempts = await self._first_success(notification, recipients, semaphore)
        return NotificationReport(notification.notification_id, False, attempts)

    async def _fan_out(
        self,
        notification: Notification,
        recipients: Sequence[RecipientPreferences],
        semaphore: asyncio.Semaphore,
    ) -> tuple[NotificationAttempt, ...]:
        decisions: list[NotificationAttempt | Awaitable[NotificationAttempt]] = []
        for recipient in recipients:
            reason = self._suppression_reason(notification, recipient)
            for point in recipient.contact_points:
                point_reason = reason or (None if point.enabled else "contact point is disabled")
                if point_reason:
                    decisions.append(self._suppressed(recipient, point, point_reason))
                else:
                    decisions.append(self._invoke(notification, recipient, point, semaphore))
        return await self._resolve(decisions)

    async def _first_success(
        self,
        notification: Notification,
        recipients: Sequence[RecipientPreferences],
        semaphore: asyncio.Semaphore,
    ) -> tuple[NotificationAttempt, ...]:
        groups = await asyncio.gather(
            *(
                self._deliver_recipient(notification, recipient, semaphore)
                for recipient in recipients
            )
        )
        return tuple(attempt for group in groups for attempt in group)

    async def _deliver_recipient(
        self,
        notification: Notification,
        recipient: RecipientPreferences,
        semaphore: asyncio.Semaphore,
    ) -> tuple[NotificationAttempt, ...]:
        reason = self._suppression_reason(notification, recipient)
        if reason:
            return tuple(
                self._suppressed(recipient, point, reason) for point in recipient.contact_points
            )

        attempts: list[NotificationAttempt] = []
        succeeded = False
        for point in recipient.contact_points:
            if succeeded:
                attempts.append(
                    self._suppressed(recipient, point, "earlier contact point succeeded")
                )
            elif not point.enabled:
                attempts.append(self._suppressed(recipient, point, "contact point is disabled"))
            else:
                attempt = await self._invoke(notification, recipient, point, semaphore)
                attempts.append(attempt)
                succeeded = attempt.state is DeliveryState.SUCCEEDED
        return tuple(attempts)

    async def _invoke(
        self,
        notification: Notification,
        recipient: RecipientPreferences,
        point: ContactPoint,
        semaphore: asyncio.Semaphore,
    ) -> NotificationAttempt:
        provider = self._providers.get(point.channel)
        if provider is None:
            return NotificationAttempt(
                recipient.recipient_id,
                point.channel,
                point.address,
                DeliveryState.MISSING_PROVIDER,
                0,
                error=f"no provider registered for {point.channel}",
            )

        async with semaphore:
            started_at = self._monotonic()
            try:
                output = await provider(notification, point)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return NotificationAttempt(
                    recipient.recipient_id,
                    point.channel,
                    point.address,
                    DeliveryState.FAILED,
                    self._duration_ms(started_at),
                    error=f"{type(exc).__name__}: {exc}",
                )
            return NotificationAttempt(
                recipient.recipient_id,
                point.channel,
                point.address,
                DeliveryState.SUCCEEDED,
                self._duration_ms(started_at),
                output=dict(output) if output is not None else None,
            )

    @staticmethod
    def _suppression_reason(
        notification: Notification,
        recipient: RecipientPreferences,
    ) -> str | None:
        if notification.priority < recipient.minimum_priority:
            return "notification priority is below recipient minimum"
        if notification.topic in recipient.muted_topics:
            return "notification topic is muted"
        return None

    @staticmethod
    def _suppressed(
        recipient: RecipientPreferences,
        point: ContactPoint,
        reason: str,
    ) -> NotificationAttempt:
        return NotificationAttempt(
            recipient.recipient_id,
            point.channel,
            point.address,
            DeliveryState.SUPPRESSED,
            0,
            error=reason,
        )

    @staticmethod
    async def _resolve(
        decisions: Sequence[NotificationAttempt | Awaitable[NotificationAttempt]],
    ) -> tuple[NotificationAttempt, ...]:
        async def resolve(
            decision: NotificationAttempt | Awaitable[NotificationAttempt],
        ) -> NotificationAttempt:
            if isinstance(decision, NotificationAttempt):
                return decision
            return await decision

        return tuple(await asyncio.gather(*(resolve(decision) for decision in decisions)))

    @staticmethod
    def _validate_recipients(recipients: Sequence[RecipientPreferences]) -> None:
        identifiers = [recipient.recipient_id for recipient in recipients]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("recipient identifiers must be unique")

    def _duration_ms(self, started_at: float) -> int:
        return max(0, round((self._monotonic() - started_at) * 1000))
