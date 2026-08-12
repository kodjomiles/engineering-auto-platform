from __future__ import annotations

from datetime import UTC, datetime

import pytest

from engineering_automation.events import (
    Condition,
    ConditionGroup,
    ConditionMode,
    ConditionOperator,
    EngineeringEvent,
    EventRouter,
    RoutingRule,
)


def make_event(*, source: str = "github") -> EngineeringEvent:
    return EngineeringEvent(
        event_id="evt-123",
        source=source,
        event_type="deployment.completed",
        subject="payments-api",
        occurred_at=datetime(2026, 8, 12, tzinfo=UTC),
        payload={"service": {"tier": 1}},
    )


def source_is(value: str) -> ConditionGroup:
    return ConditionGroup(
        ConditionMode.ALL,
        (Condition("source", ConditionOperator.EQUALS, value),),
    )


def test_router_orders_matches_by_priority_then_identifier() -> None:
    router = EventRouter(
        (
            RoutingRule("z-low", ("slack",), source_is("github"), priority=1),
            RoutingRule("b-high", ("n8n",), source_is("github"), priority=10),
            RoutingRule("a-high", ("port",), source_is("github"), priority=10),
        )
    )

    plan = router.route(make_event())

    assert plan.matched_rule_ids == ("a-high", "b-high", "z-low")
    assert plan.destinations == ("port", "n8n", "slack")


def test_router_skips_disabled_and_non_matching_rules() -> None:
    router = EventRouter(
        (
            RoutingRule("disabled", ("slack",), source_is("github"), enabled=False),
            RoutingRule("wrong-source", ("n8n",), source_is("gitlab")),
        )
    )

    plan = router.route(make_event())

    assert plan.event_id == "evt-123"
    assert plan.matched_rule_ids == ()
    assert plan.destinations == ()


def test_router_deduplicates_destinations_but_records_every_match() -> None:
    router = EventRouter(
        (
            RoutingRule("audit", ("port", "warehouse"), source_is("github"), priority=2),
            RoutingRule("notify", ("port", "slack"), source_is("github"), priority=1),
        )
    )

    plan = router.route(make_event())

    assert plan.matched_rule_ids == ("audit", "notify")
    assert plan.destinations == ("port", "warehouse", "slack")


def test_router_rejects_duplicate_rule_identifiers() -> None:
    with pytest.raises(ValueError, match="identifiers must be unique"):
        EventRouter(
            (
                RoutingRule("duplicate", ("port",), source_is("github")),
                RoutingRule("duplicate", ("n8n",), source_is("gitlab")),
            )
        )


def test_rule_replacement_is_atomic_when_validation_fails() -> None:
    original = RoutingRule("original", ("port",), source_is("github"))
    router = EventRouter((original,))
    invalid = (
        RoutingRule("duplicate", ("port",), source_is("github")),
        RoutingRule("duplicate", ("n8n",), source_is("gitlab")),
    )

    with pytest.raises(ValueError, match="identifiers must be unique"):
        router.replace_rules(invalid)

    assert router.rules == (original,)
    assert router.route(make_event()).destinations == ("port",)
