"""Publish a notification according to recipient and delivery policy."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Sequence

from engineering_automation.application.ports.notifications import DeduplicationStore
from engineering_automation.application.services.provider_delivery import ProviderDelivery
from engineering_automation.domain.notification_policy import suppression_reason
from engineering_automation.domain.notifications import (
    ContactPoint,
    DeliveryMode,
    DeliveryState,
    Notification,
    NotificationAttempt,
    NotificationPolicy,
    NotificationReport,
    RecipientPreferences,
)


class PublishNotification:
    """Coordinate deduplication, preference policy, and provider delivery."""

    def __init__(
        self,
        provider_delivery: ProviderDelivery,
        deduplication_store: DeduplicationStore,
    ) -> None:
        self._provider_delivery = provider_delivery
        self._deduplication = deduplication_store

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
            for point in recipient.contact_points:
                reason = suppression_reason(notification, recipient, point)
                if reason:
                    decisions.append(self._suppressed(recipient, point, reason))
                else:
                    decisions.append(
                        self._provider_delivery.invoke(notification, recipient, point, semaphore)
                    )
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
        attempts: list[NotificationAttempt] = []
        succeeded = False
        for point in recipient.contact_points:
            reason = suppression_reason(notification, recipient, point)
            if succeeded:
                attempts.append(
                    self._suppressed(recipient, point, "earlier contact point succeeded")
                )
            elif reason:
                attempts.append(self._suppressed(recipient, point, reason))
            else:
                attempt = await self._provider_delivery.invoke(
                    notification,
                    recipient,
                    point,
                    semaphore,
                )
                attempts.append(attempt)
                succeeded = attempt.state is DeliveryState.SUCCEEDED
        return tuple(attempts)

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
