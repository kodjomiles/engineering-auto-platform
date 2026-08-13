"""Provider-neutral notification orchestration."""

from engineering_automation.notifications.deduplication import (
    DeduplicationStore,
    InMemoryDeduplicationStore,
)
from engineering_automation.notifications.handler import NotificationEventHandler
from engineering_automation.notifications.models import (
    ContactPoint,
    DeliveryMode,
    DeliveryState,
    Notification,
    NotificationAttempt,
    NotificationPolicy,
    NotificationPriority,
    NotificationReport,
    RecipientPreferences,
)
from engineering_automation.notifications.service import NotificationProvider, NotificationService

__all__ = [
    "ContactPoint",
    "DeduplicationStore",
    "DeliveryMode",
    "DeliveryState",
    "InMemoryDeduplicationStore",
    "Notification",
    "NotificationAttempt",
    "NotificationEventHandler",
    "NotificationPolicy",
    "NotificationPriority",
    "NotificationProvider",
    "NotificationReport",
    "NotificationService",
    "RecipientPreferences",
]
