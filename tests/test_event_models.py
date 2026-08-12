from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from engineering_automation.events import (
    Condition,
    ConditionGroup,
    ConditionMode,
    ConditionOperator,
    DestinationResult,
    DispatchReport,
    DispatchStatus,
    EngineeringEvent,
    RoutingRule,
)


def make_event() -> EngineeringEvent:
    return EngineeringEvent(
        event_id="evt-123",
        source="github",
        event_type="deployment.completed",
        subject="payments-api",
        occurred_at=datetime(2026, 8, 12, 14, tzinfo=UTC),
        payload={"service": {"name": "payments"}, "changes": ["code", "docs"]},
        labels={"team": "platform"},
    )


@pytest.mark.parametrize("field", ["event_id", "source", "event_type", "subject"])
def test_event_rejects_empty_identity_fields(field: str) -> None:
    values: dict[str, object] = {
        "event_id": "evt-123",
        "source": "github",
        "event_type": "deployment.completed",
        "subject": "payments-api",
        "occurred_at": datetime(2026, 8, 12, tzinfo=UTC),
    }
    values[field] = " "

    with pytest.raises(ValueError, match=field):
        EngineeringEvent(**values)  # type: ignore[arg-type]


def test_event_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EngineeringEvent(
            event_id="evt-123",
            source="github",
            event_type="deployment.completed",
            subject="payments-api",
            occurred_at=datetime(2026, 8, 12),
        )


def test_event_detaches_and_deeply_freezes_input_data() -> None:
    payload: dict[str, Any] = {"service": {"name": "payments"}, "changes": ["code"]}
    labels = {" team ": " platform "}
    event = EngineeringEvent(
        event_id="evt-123",
        source="github",
        event_type="deployment.completed",
        subject="payments-api",
        occurred_at=datetime(2026, 8, 12, tzinfo=UTC),
        payload=payload,
        labels=labels,
    )

    payload["service"]["name"] = "changed"
    payload["changes"].append("docs")
    labels[" team "] = "changed"

    assert event.payload["service"]["name"] == "payments"
    assert event.payload["changes"] == ("code",)
    assert event.labels == {"team": "platform"}
    with pytest.raises(TypeError):
        event.payload["new"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        event.payload["service"]["name"] = "blocked"


@pytest.mark.parametrize("field", ["", " ", ".payload", "payload.", "payload..name"])
def test_condition_rejects_invalid_field_paths(field: str) -> None:
    with pytest.raises(ValueError, match="condition field"):
        Condition(field, ConditionOperator.EQUALS, "value")


def test_exists_condition_requires_boolean_value() -> None:
    with pytest.raises(ValueError, match="boolean"):
        Condition("payload.service", ConditionOperator.EXISTS, "yes")


@pytest.mark.parametrize("value", ["github", 3, None])
def test_in_condition_requires_non_string_collection(value: object) -> None:
    with pytest.raises(ValueError, match="collection"):
        Condition("source", ConditionOperator.IN, value)


def test_condition_group_cannot_be_empty() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        ConditionGroup(ConditionMode.ALL, ())


def make_group() -> ConditionGroup:
    return ConditionGroup(
        ConditionMode.ALL,
        (Condition("source", ConditionOperator.EQUALS, "github"),),
    )


@pytest.mark.parametrize(
    ("identifier", "destinations", "message"),
    [
        (" ", ("port",), "identifier"),
        ("github-events", (), "at least one"),
        ("github-events", (" ",), "at least one"),
        ("github-events", ("port", " port "), "unique"),
    ],
)
def test_routing_rule_rejects_invalid_configuration(
    identifier: str, destinations: tuple[str, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        RoutingRule(identifier, destinations, make_group())


def test_destination_result_freezes_output() -> None:
    output = {"entity": {"identifier": "payments"}}
    result = DestinationResult("port", DispatchStatus.SUCCEEDED, 12, output=output)
    output["entity"]["identifier"] = "changed"

    assert result.output is not None
    assert result.output["entity"]["identifier"] == "payments"
    with pytest.raises(TypeError):
        result.output["new"] = True  # type: ignore[index]


@pytest.mark.parametrize(
    ("destination", "duration", "message"),
    [(" ", 0, "destination"), ("port", -1, "duration_ms")],
)
def test_destination_result_rejects_invalid_values(
    destination: str, duration: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        DestinationResult(destination, DispatchStatus.SUCCEEDED, duration)


def test_dispatch_report_succeeds_only_when_every_destination_succeeds() -> None:
    success = DestinationResult("port", DispatchStatus.SUCCEEDED, 1)
    failure = DestinationResult("n8n", DispatchStatus.FAILED, 1, error="failed")

    assert DispatchReport("evt-123", (), (success,)).succeeded
    assert not DispatchReport("evt-123", (), (success, failure)).succeeded
    assert not DispatchReport("evt-123", (), ()).succeeded
