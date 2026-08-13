"""Compatibility façade composing the notification use case."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence

from engineering_automation.application.ports.notifications import (
    DeduplicationStore,
    NotificationProvider,
)
from engineering_automation.bootstrap.notifications import build_notification_publisher
from engineering_automation.domain.notifications import (
    Notification,
    NotificationPolicy,
    NotificationReport,
    RecipientPreferences,
)

Clock = Callable[[], float]


class NotificationService:
    """Compose default notification adapters while preserving the original API."""

    def __init__(
        self,
        providers: Mapping[str, NotificationProvider],
        *,
        deduplication_store: DeduplicationStore | None = None,
        monotonic: Clock = time.monotonic,
    ) -> None:
        self._publisher = build_notification_publisher(
            providers,
            deduplication_store=deduplication_store,
            monotonic=monotonic,
        )

    async def publish(
        self,
        notification: Notification,
        recipients: Sequence[RecipientPreferences],
        policy: NotificationPolicy | None = None,
    ) -> NotificationReport:
        return await self._publisher.publish(notification, recipients, policy)


__all__ = ["NotificationProvider", "NotificationService"]
