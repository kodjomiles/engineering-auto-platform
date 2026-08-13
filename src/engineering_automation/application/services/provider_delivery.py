"""Invoke exactly one notification provider and build its audit record."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping

from engineering_automation.application.ports.notifications import NotificationProvider
from engineering_automation.domain.notifications import (
    ContactPoint,
    DeliveryState,
    Notification,
    NotificationAttempt,
    RecipientPreferences,
)

Clock = Callable[[], float]


class ProviderDelivery:
    """Failure-isolated invocation of registered notification providers."""

    def __init__(
        self,
        providers: Mapping[str, NotificationProvider],
        *,
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
        self._monotonic = monotonic

    async def invoke(
        self,
        notification: Notification,
        recipient: RecipientPreferences,
        contact_point: ContactPoint,
        semaphore: asyncio.Semaphore,
    ) -> NotificationAttempt:
        provider = self._providers.get(contact_point.channel)
        if provider is None:
            return NotificationAttempt(
                recipient.recipient_id,
                contact_point.channel,
                contact_point.address,
                DeliveryState.MISSING_PROVIDER,
                0,
                error=f"no provider registered for {contact_point.channel}",
            )

        async with semaphore:
            started_at = self._monotonic()
            try:
                output = await provider(notification, contact_point)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return NotificationAttempt(
                    recipient.recipient_id,
                    contact_point.channel,
                    contact_point.address,
                    DeliveryState.FAILED,
                    self._duration_ms(started_at),
                    error=f"{type(exc).__name__}: {exc}",
                )
            return NotificationAttempt(
                recipient.recipient_id,
                contact_point.channel,
                contact_point.address,
                DeliveryState.SUCCEEDED,
                self._duration_ms(started_at),
                output=dict(output) if output is not None else None,
            )

    def _duration_ms(self, started_at: float) -> int:
        return max(0, round((self._monotonic() - started_at) * 1000))
