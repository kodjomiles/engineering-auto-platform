"""Notification use-case ports."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from engineering_automation.domain.notifications import (
    ContactPoint,
    Notification,
    NotificationPolicy,
    NotificationReport,
    RecipientPreferences,
)

NotificationProvider = Callable[[Notification, ContactPoint], Awaitable[Mapping[str, Any] | None]]


class DeduplicationStore(Protocol):
    """Atomically claim deduplication keys for a bounded time window."""

    async def claim(self, key: str, ttl_seconds: float) -> bool:
        """Return true only for the first live claim of a key."""
        ...


class NotificationPublisher(Protocol):
    """Inbound port used by notification interface adapters."""

    async def publish(
        self,
        notification: Notification,
        recipients: Sequence[RecipientPreferences],
        policy: NotificationPolicy | None = None,
    ) -> NotificationReport: ...
