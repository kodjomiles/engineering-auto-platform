from __future__ import annotations

from datetime import UTC, datetime

import pytest

from engineering_automation.events import (
    Condition,
    ConditionGroup,
    ConditionMode,
    ConditionOperator,
    EngineeringEvent,
    evaluate_condition,
    evaluate_group,
)


def make_event() -> EngineeringEvent:
    return EngineeringEvent(
        event_id="evt-123",
        source="github",
        event_type="deployment.completed",
        subject="payments-api",
        occurred_at=datetime(2026, 8, 12, 14, tzinfo=UTC),
        payload={
            "service": {"name": "payments", "tier": 1},
            "changes": ["code", "docs"],
            "count": 5,
            "enabled": True,
        },
        labels={"team": "platform", "environment": "production"},
    )


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (Condition("source", ConditionOperator.EQUALS, "github"), True),
        (Condition("source", ConditionOperator.NOT_EQUALS, "gitlab"), True),
        (Condition("payload.service.name", ConditionOperator.EQUALS, "payments"), True),
        (Condition("payload.changes.1", ConditionOperator.EQUALS, "docs"), True),
        (Condition("payload.changes.-1", ConditionOperator.EXISTS, False), True),
        (Condition("payload.missing", ConditionOperator.EXISTS, False), True),
        (Condition("payload.service", ConditionOperator.EXISTS, True), True),
        (Condition("source", ConditionOperator.IN, ("github", "gitlab")), True),
        (Condition("payload.changes", ConditionOperator.CONTAINS, "code"), True),
        (Condition("subject", ConditionOperator.CONTAINS, "payments"), True),
        (Condition("payload.service", ConditionOperator.CONTAINS, "tier"), True),
        (Condition("subject", ConditionOperator.STARTS_WITH, "payments"), True),
        (Condition("subject", ConditionOperator.ENDS_WITH, "api"), True),
        (Condition("payload.count", ConditionOperator.GREATER_THAN, 4), True),
        (Condition("payload.count", ConditionOperator.LESS_THAN, 6), True),
        (Condition("payload.missing", ConditionOperator.NOT_EQUALS, "anything"), True),
        (Condition("payload.missing", ConditionOperator.EQUALS, None), False),
        (Condition("payload.count", ConditionOperator.CONTAINS, 5), False),
        (Condition("payload.count", ConditionOperator.STARTS_WITH, "5"), False),
        (Condition("payload.count", ConditionOperator.GREATER_THAN, "4"), False),
        (Condition("payload.changes.nope", ConditionOperator.EXISTS, True), False),
        (Condition("unknown", ConditionOperator.EXISTS, True), False),
    ],
)
def test_condition_operators_are_safe_and_predictable(condition: Condition, expected: bool) -> None:
    assert evaluate_condition(make_event(), condition) is expected


def test_all_group_requires_every_condition_to_match() -> None:
    group = ConditionGroup(
        ConditionMode.ALL,
        (
            Condition("source", ConditionOperator.EQUALS, "github"),
            Condition("labels.environment", ConditionOperator.EQUALS, "production"),
        ),
    )
    assert evaluate_group(make_event(), group)


def test_any_group_requires_at_least_one_condition_to_match() -> None:
    group = ConditionGroup(
        ConditionMode.ANY,
        (
            Condition("source", ConditionOperator.EQUALS, "gitlab"),
            Condition("labels.team", ConditionOperator.EQUALS, "platform"),
        ),
    )
    assert evaluate_group(make_event(), group)


def test_groups_can_be_nested() -> None:
    group = ConditionGroup(
        ConditionMode.ALL,
        (
            Condition("source", ConditionOperator.EQUALS, "github"),
            ConditionGroup(
                ConditionMode.ANY,
                (
                    Condition("payload.service.tier", ConditionOperator.EQUALS, 2),
                    Condition("payload.enabled", ConditionOperator.EQUALS, True),
                ),
            ),
        ),
    )
    assert evaluate_group(make_event(), group)
