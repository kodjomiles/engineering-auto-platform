"""Translate engineering events into notification use-case requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from engineering_automation.application.ports.notifications import NotificationPublisher
from engineering_automation.domain.notifications import (
    DeliveryState,
    Notification,
    NotificationPolicy,
    NotificationPriority,
    RecipientPreferences,
)
from engineering_automation.events.models import EngineeringEvent

TextRenderer = Callable[[EngineeringEvent], str]
KeyFactory = Callable[[EngineeringEvent], str | None]


class NotificationEventHandler:
    """Render routed engineering events and publish them through an inbound port."""

    def __init__(
        self,
        publisher: NotificationPublisher,
        recipients: Sequence[RecipientPreferences],
        *,
        subject: TextRenderer,
        body: TextRenderer,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        topic: str | None = None,
        policy: NotificationPolicy | None = None,
        deduplication_key: KeyFactory | None = None,
    ) -> None:
        if topic is not None and not topic.strip():
            raise ValueError("topic cannot be empty")
        self._publisher = publisher
        self._recipients = tuple(recipients)
        self._subject = subject
        self._body = body
        self._priority = priority
        self._topic = topic.strip() if topic is not None else None
        self._policy = policy
        self._deduplication_key = deduplication_key

    async def __call__(self, event: EngineeringEvent) -> Mapping[str, Any]:
        key = self._deduplication_key(event) if self._deduplication_key is not None else None
        notification = Notification(
            notification_id=event.event_id,
            topic=self._topic or event.event_type,
            subject=self._subject(event),
            body=self._body(event),
            priority=self._priority,
            occurred_at=event.occurred_at,
            metadata={
                "source": event.source,
                "subject": event.subject,
                "payload": event.payload,
                "labels": event.labels,
            },
            deduplication_key=key,
        )
        report = await self._publisher.publish(notification, self._recipients, self._policy)
        return {
            "deduplicated": report.deduplicated,
            "delivered": sum(
                attempt.state is DeliveryState.SUCCEEDED for attempt in report.attempts
            ),
            "failed": sum(
                attempt.state in {DeliveryState.FAILED, DeliveryState.MISSING_PROVIDER}
                for attempt in report.attempts
            ),
            "suppressed": sum(
                attempt.state is DeliveryState.SUPPRESSED for attempt in report.attempts
            ),
        }
