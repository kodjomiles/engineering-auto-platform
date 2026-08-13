from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from engineering_automation.notifications import (
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


@pytest.mark.parametrize(
    ("channel", "address", "message"),
    [(" ", "person@example.com", "channel"), ("email", " ", "address")],
)
def test_contact_point_rejects_blank_fields(channel: str, address: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ContactPoint(channel, address)


def test_contact_point_normalizes_channel_and_address() -> None:
    point = ContactPoint(" EMAIL ", " person@example.com ")
    assert point == ContactPoint("email", "person@example.com")


def test_recipient_normalizes_identity_and_muted_topics() -> None:
    recipient = RecipientPreferences(
        " person-1 ",
        (ContactPoint("email", "person@example.com"),),
        muted_topics=frozenset({" deployments ", "", "security"}),
    )
    assert recipient.recipient_id == "person-1"
    assert recipient.muted_topics == {"deployments", "security"}


@pytest.mark.parametrize(
    ("recipient_id", "points", "message"),
    [
        (" ", (ContactPoint("email", "a@example.com"),), "recipient_id"),
        ("person", (), "at least one"),
        (
            "person",
            (ContactPoint("email", "a@example.com"), ContactPoint("EMAIL", "a@example.com")),
            "unique",
        ),
    ],
)
def test_recipient_rejects_invalid_contract(
    recipient_id: str, points: tuple[ContactPoint, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        RecipientPreferences(recipient_id, points)


def make_notification(**overrides: object) -> Notification:
    values: dict[str, object] = {
        "notification_id": "notification-1",
        "topic": "deployments",
        "subject": "Deployment completed",
        "body": "payments-api reached production",
        "priority": NotificationPriority.HIGH,
        "occurred_at": datetime(2026, 8, 13, 9, tzinfo=UTC),
        "metadata": {"service": {"name": "payments"}, "changes": ["code"]},
    }
    values.update(overrides)
    return Notification(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["notification_id", "topic", "subject", "body"])
def test_notification_rejects_blank_required_fields(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        make_notification(**{field: " "})


def test_notification_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_notification(occurred_at=datetime(2026, 8, 13, 9))


def test_notification_rejects_blank_deduplication_key() -> None:
    with pytest.raises(ValueError, match="deduplication_key"):
        make_notification(deduplication_key=" ")


def test_notification_deeply_freezes_metadata() -> None:
    metadata: dict[str, Any] = {"service": {"name": "payments"}, "changes": ["code"]}
    notification = make_notification(metadata=metadata)
    metadata["service"]["name"] = "changed"
    metadata["changes"].append("docs")

    assert notification.metadata["service"]["name"] == "payments"
    assert notification.metadata["changes"] == ("code",)
    with pytest.raises(TypeError):
        notification.metadata["new"] = True  # type: ignore[index]


@pytest.mark.parametrize(
    ("max_concurrency", "window", "message"),
    [(0, 300, "max_concurrency"), (1, -1, "deduplication_window")],
)
def test_policy_rejects_invalid_limits(max_concurrency: int, window: float, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        NotificationPolicy(
            mode=DeliveryMode.FIRST_SUCCESS,
            max_concurrency=max_concurrency,
            deduplication_window_seconds=window,
        )


def test_attempt_deeply_freezes_provider_output() -> None:
    output: dict[str, Any] = {"provider": {"message_id": "msg-1"}}
    attempt = NotificationAttempt(
        "person",
        "email",
        "person@example.com",
        DeliveryState.SUCCEEDED,
        10,
        output=output,
    )
    output["provider"]["message_id"] = "changed"

    assert attempt.output is not None
    assert attempt.output["provider"]["message_id"] == "msg-1"
    with pytest.raises(TypeError):
        attempt.output["new"] = True  # type: ignore[index]


@pytest.mark.parametrize(
    ("recipient", "channel", "address", "duration", "message"),
    [
        ("", "email", "a@example.com", 0, "recipient_id"),
        ("person", "", "a@example.com", 0, "channel"),
        ("person", "email", "", 0, "address"),
        ("person", "email", "a@example.com", -1, "duration_ms"),
    ],
)
def test_attempt_rejects_invalid_audit_fields(
    recipient: str, channel: str, address: str, duration: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        NotificationAttempt(recipient, channel, address, DeliveryState.SUCCEEDED, duration)


def test_report_exposes_delivery_and_failure_summary() -> None:
    success = NotificationAttempt("one", "email", "one@example.com", DeliveryState.SUCCEEDED, 1)
    failure = NotificationAttempt("two", "slack", "U123", DeliveryState.MISSING_PROVIDER, 0)
    suppressed = NotificationAttempt("three", "sms", "+233000000", DeliveryState.SUPPRESSED, 0)

    report = NotificationReport("notification-1", False, (success, failure, suppressed))
    assert report.delivered
    assert report.has_failures
    assert not NotificationReport("notification-2", True, ()).delivered
