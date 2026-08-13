from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from engineering_automation.events import EngineeringEvent, EventDispatcher, RoutePlan
from engineering_automation.notifications import (
    ContactPoint,
    Notification,
    NotificationEventHandler,
    NotificationPriority,
    NotificationService,
    RecipientPreferences,
)


def make_event() -> EngineeringEvent:
    return EngineeringEvent(
        event_id="evt-123",
        source="github",
        event_type="deployment.completed",
        subject="payments-api",
        occurred_at=datetime(2026, 8, 13, 9, tzinfo=UTC),
        payload={"environment": "production"},
    )


def make_recipient() -> RecipientPreferences:
    return RecipientPreferences(
        "platform-team",
        (ContactPoint("email", "platform@example.com"),),
    )


def test_handler_renders_event_and_returns_delivery_summary() -> None:
    received: list[Notification] = []

    async def provider(notification: Notification, _: ContactPoint) -> None:
        received.append(notification)

    handler = NotificationEventHandler(
        NotificationService({"email": provider}),
        (make_recipient(),),
        subject=lambda event: f"{event.subject} deployed",
        body=lambda event: f"Environment: {event.payload['environment']}",
        priority=NotificationPriority.HIGH,
        topic="production-deployments",
    )
    result = asyncio.run(handler(make_event()))

    assert result == {"deduplicated": False, "delivered": 1, "failed": 0, "suppressed": 0}
    assert received[0].subject == "payments-api deployed"
    assert received[0].body == "Environment: production"
    assert received[0].topic == "production-deployments"
    assert received[0].priority is NotificationPriority.HIGH


def test_handler_plugs_into_event_dispatcher_and_deduplicates() -> None:
    calls = 0

    async def provider(_: Notification, __: ContactPoint) -> None:
        nonlocal calls
        calls += 1

    event = make_event()
    handler = NotificationEventHandler(
        NotificationService({"email": provider}),
        (make_recipient(),),
        subject=lambda _: "Deployment completed",
        body=lambda _: "payments-api reached production",
        deduplication_key=lambda item: f"{item.event_type}:{item.subject}",
    )
    dispatcher = EventDispatcher({"notifications": handler})
    plan = RoutePlan(event.event_id, ("notify-deployments",), ("notifications",))

    async def exercise() -> tuple[object, object]:
        first = await dispatcher.dispatch(event, plan)
        second = await dispatcher.dispatch(event, plan)
        return first.results[0].output, second.results[0].output

    first, second = asyncio.run(exercise())
    assert first == {"deduplicated": False, "delivered": 1, "failed": 0, "suppressed": 0}
    assert second == {"deduplicated": True, "delivered": 0, "failed": 0, "suppressed": 0}
    assert calls == 1


def test_handler_rejects_blank_topic() -> None:
    with pytest.raises(ValueError, match="topic"):
        NotificationEventHandler(
            NotificationService({}),
            (make_recipient(),),
            subject=lambda _: "subject",
            body=lambda _: "body",
            topic=" ",
        )


def test_renderer_failure_is_isolated_by_event_dispatcher() -> None:
    def fail(_: EngineeringEvent) -> str:
        raise RuntimeError("template failed")

    event = make_event()
    handler = NotificationEventHandler(
        NotificationService({}),
        (make_recipient(),),
        subject=fail,
        body=lambda _: "body",
    )
    report = asyncio.run(
        EventDispatcher({"notifications": handler}).dispatch(
            event,
            RoutePlan(event.event_id, (), ("notifications",)),
        )
    )
    assert not report.succeeded
    assert report.results[0].error == "RuntimeError: template failed"
