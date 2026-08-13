"""Notification use-case composition root."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

from engineering_automation.application.ports.notifications import (
    DeduplicationStore,
    NotificationProvider,
)
from engineering_automation.application.services.provider_delivery import ProviderDelivery
from engineering_automation.application.use_cases.publish_notification import PublishNotification
from engineering_automation.infrastructure.persistence.memory_deduplication import (
    InMemoryDeduplicationStore,
)

Clock = Callable[[], float]


def build_notification_publisher(
    providers: Mapping[str, NotificationProvider],
    *,
    deduplication_store: DeduplicationStore | None = None,
    monotonic: Clock = time.monotonic,
) -> PublishNotification:
    """Wire notification application ports to their default adapters."""

    return PublishNotification(
        ProviderDelivery(providers, monotonic=monotonic),
        deduplication_store or InMemoryDeduplicationStore(),
    )
