from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from engineering_automation.notifications import (
    ContactPoint,
    DeliveryMode,
    DeliveryState,
    Notification,
    NotificationPolicy,
    NotificationPriority,
    NotificationReport,
    NotificationService,
    RecipientPreferences,
)


class SequenceClock:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def make_notification(**overrides: object) -> Notification:
    values: dict[str, object] = {
        "notification_id": "notification-1",
        "topic": "deployments",
        "subject": "Deployment completed",
        "body": "payments-api reached production",
        "priority": NotificationPriority.HIGH,
        "occurred_at": datetime(2026, 8, 13, 9, tzinfo=UTC),
    }
    values.update(overrides)
    return Notification(**values)  # type: ignore[arg-type]


def recipient(
    identifier: str = "person-1",
    *points: ContactPoint,
    minimum: NotificationPriority = NotificationPriority.LOW,
    muted: frozenset[str] = frozenset(),
) -> RecipientPreferences:
    return RecipientPreferences(
        identifier,
        points or (ContactPoint("email", f"{identifier}@example.com"),),
        minimum_priority=minimum,
        muted_topics=muted,
    )


def test_fan_out_calls_all_eligible_providers_in_auditable_order() -> None:
    calls: list[str] = []

    def provider(name: str) -> Any:
        async def send(_: Notification, point: ContactPoint) -> Mapping[str, Any]:
            calls.append(f"{name}:{point.address}")
            return {"provider": name, "message_id": f"{name}-1"}

        return send

    recipients = (
        recipient(
            "one",
            ContactPoint("email", "one@example.com"),
            ContactPoint("slack", "U001"),
        ),
        recipient("two", ContactPoint("email", "two@example.com")),
    )
    report = asyncio.run(
        NotificationService(
            {"email": provider("email"), "slack": provider("slack")},
            monotonic=SequenceClock((1, 1.01, 2, 2.01, 3, 3.01)),
        ).publish(make_notification(), recipients)
    )

    assert report.delivered
    assert not report.has_failures
    assert [(attempt.recipient_id, attempt.channel) for attempt in report.attempts] == [
        ("one", "email"),
        ("one", "slack"),
        ("two", "email"),
    ]
    assert {attempt.duration_ms for attempt in report.attempts} == {10}
    assert set(calls) == {"email:one@example.com", "slack:U001", "email:two@example.com"}


def test_provider_failure_is_isolated_from_other_channels() -> None:
    async def fail(_: Notification, __: ContactPoint) -> None:
        raise RuntimeError("email unavailable")

    async def succeed(_: Notification, __: ContactPoint) -> Mapping[str, Any]:
        return {"message_id": "slack-1"}

    report = asyncio.run(
        NotificationService({"email": fail, "slack": succeed}).publish(
            make_notification(),
            (
                recipient(
                    "one",
                    ContactPoint("email", "one@example.com"),
                    ContactPoint("slack", "U001"),
                ),
            ),
        )
    )

    assert report.delivered
    assert report.has_failures
    assert report.attempts[0].state is DeliveryState.FAILED
    assert report.attempts[0].error == "RuntimeError: email unavailable"
    assert report.attempts[1].state is DeliveryState.SUCCEEDED


def test_missing_provider_is_recorded_without_invocation() -> None:
    report = asyncio.run(
        NotificationService({}).publish(
            make_notification(),
            (recipient("one", ContactPoint("pager", "team-primary")),),
        )
    )
    assert report.attempts[0].state is DeliveryState.MISSING_PROVIDER
    assert report.attempts[0].duration_ms == 0
    assert report.has_failures


@pytest.mark.parametrize(
    ("preferences", "reason"),
    [
        (
            recipient("one", minimum=NotificationPriority.CRITICAL),
            "below recipient minimum",
        ),
        (
            recipient("one", muted=frozenset({"deployments"})),
            "topic is muted",
        ),
        (
            recipient("one", ContactPoint("email", "one@example.com", enabled=False)),
            "contact point is disabled",
        ),
    ],
)
def test_preferences_suppress_delivery(preferences: RecipientPreferences, reason: str) -> None:
    calls = 0

    async def provider(_: Notification, __: ContactPoint) -> None:
        nonlocal calls
        calls += 1

    report = asyncio.run(
        NotificationService({"email": provider}).publish(make_notification(), (preferences,))
    )
    assert calls == 0
    assert report.attempts[0].state is DeliveryState.SUPPRESSED
    assert reason in (report.attempts[0].error or "")
    assert not report.has_failures


def test_first_success_uses_ordered_fallback_and_skips_remainder() -> None:
    calls: list[str] = []

    async def email(_: Notification, __: ContactPoint) -> None:
        calls.append("email")
        raise RuntimeError("email unavailable")

    async def slack(_: Notification, __: ContactPoint) -> None:
        calls.append("slack")

    async def sms(_: Notification, __: ContactPoint) -> None:
        calls.append("sms")

    report = asyncio.run(
        NotificationService({"email": email, "slack": slack, "sms": sms}).publish(
            make_notification(),
            (
                recipient(
                    "one",
                    ContactPoint("email", "one@example.com"),
                    ContactPoint("slack", "U001"),
                    ContactPoint("sms", "+233000000"),
                ),
            ),
            NotificationPolicy(mode=DeliveryMode.FIRST_SUCCESS),
        )
    )

    assert calls == ["email", "slack"]
    assert [attempt.state for attempt in report.attempts] == [
        DeliveryState.FAILED,
        DeliveryState.SUCCEEDED,
        DeliveryState.SUPPRESSED,
    ]
    assert report.attempts[2].error == "earlier contact point succeeded"


def test_first_success_can_fall_through_missing_and_disabled_channels() -> None:
    async def sms(_: Notification, __: ContactPoint) -> None:
        return None

    report = asyncio.run(
        NotificationService({"sms": sms}).publish(
            make_notification(),
            (
                recipient(
                    "one",
                    ContactPoint("email", "one@example.com", enabled=False),
                    ContactPoint("slack", "U001"),
                    ContactPoint("sms", "+233000000"),
                ),
            ),
            NotificationPolicy(mode=DeliveryMode.FIRST_SUCCESS),
        )
    )
    assert [attempt.state for attempt in report.attempts] == [
        DeliveryState.SUPPRESSED,
        DeliveryState.MISSING_PROVIDER,
        DeliveryState.SUCCEEDED,
    ]


def test_deduplication_prevents_repeated_delivery() -> None:
    calls = 0

    async def provider(_: Notification, __: ContactPoint) -> None:
        nonlocal calls
        calls += 1

    async def exercise() -> tuple[bool, bool]:
        service = NotificationService({"email": provider})
        notification = make_notification(deduplication_key="deployment:payments:production")
        first = await service.publish(notification, (recipient(),))
        duplicate = await service.publish(notification, (recipient(),))
        return first.deduplicated, duplicate.deduplicated

    assert asyncio.run(exercise()) == (False, True)
    assert calls == 1


def test_concurrent_duplicate_publish_has_one_delivery_winner() -> None:
    calls = 0

    async def provider(_: Notification, __: ContactPoint) -> None:
        nonlocal calls
        calls += 1

    async def exercise() -> list[bool]:
        service = NotificationService({"email": provider})
        notification = make_notification(deduplication_key="same")
        reports = await asyncio.gather(
            *(service.publish(notification, (recipient(),)) for _ in range(10))
        )
        return [report.deduplicated for report in reports]

    results = asyncio.run(exercise())
    assert results.count(False) == 1
    assert results.count(True) == 9
    assert calls == 1


def test_notification_without_key_is_never_deduplicated() -> None:
    calls = 0

    async def provider(_: Notification, __: ContactPoint) -> None:
        nonlocal calls
        calls += 1

    async def exercise() -> None:
        service = NotificationService({"email": provider})
        await service.publish(make_notification(), (recipient(),))
        await service.publish(make_notification(), (recipient(),))

    asyncio.run(exercise())
    assert calls == 2


def test_service_respects_global_concurrency_limit() -> None:
    async def exercise() -> int:
        active = 0
        peak = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def gated(_: Notification, __: ContactPoint) -> None:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if peak == 2:
                started.set()
            await release.wait()
            active -= 1

        contacts = tuple(ContactPoint("email", f"person-{index}@example.com") for index in range(4))
        service = NotificationService({"email": gated})
        task = asyncio.create_task(
            service.publish(
                make_notification(),
                (recipient("one", *contacts),),
                NotificationPolicy(max_concurrency=2),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        assert active == 2
        release.set()
        report = await task
        assert len(report.attempts) == 4
        return peak

    assert asyncio.run(exercise()) == 2


def test_service_rejects_duplicate_recipient_identifiers() -> None:
    with pytest.raises(ValueError, match="recipient identifiers"):
        asyncio.run(
            NotificationService({}).publish(
                make_notification(),
                (recipient("same"), recipient("same")),
            )
        )


def test_service_rejects_blank_or_colliding_provider_channels() -> None:
    async def provider(_: Notification, __: ContactPoint) -> None:
        return None

    with pytest.raises(ValueError, match="cannot be empty"):
        NotificationService({" ": provider})
    with pytest.raises(ValueError, match="unique"):
        NotificationService({"email": provider, " EMAIL ": provider})


def test_empty_recipient_list_returns_empty_report() -> None:
    calls = 0

    async def provider(_: Notification, __: ContactPoint) -> None:
        nonlocal calls
        calls += 1

    async def exercise() -> tuple[NotificationReport, NotificationReport]:
        service = NotificationService({"email": provider})
        notification = make_notification(deduplication_key="recipient-resolution")
        empty = await service.publish(notification, ())
        delivered = await service.publish(notification, (recipient(),))
        return empty, delivered

    report, later = asyncio.run(exercise())
    assert report.attempts == ()
    assert not report.delivered
    assert not report.has_failures
    assert not later.deduplicated
    assert calls == 1
