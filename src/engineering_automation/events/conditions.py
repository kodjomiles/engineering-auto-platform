"""Condition evaluation over public engineering event fields."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from engineering_automation.events.models import (
    Condition,
    ConditionGroup,
    ConditionMode,
    ConditionOperator,
    EngineeringEvent,
)

_MISSING = object()


def resolve_field(event: EngineeringEvent, path: str) -> Any:
    """Resolve a dotted field path, returning an internal missing sentinel."""

    roots: dict[str, Any] = {
        "event_id": event.event_id,
        "source": event.source,
        "event_type": event.event_type,
        "subject": event.subject,
        "occurred_at": event.occurred_at,
        "payload": event.payload,
        "labels": event.labels,
    }
    segments = path.split(".")
    current: Any = roots.get(segments[0], _MISSING)
    for segment in segments[1:]:
        if isinstance(current, Mapping):
            current = current.get(segment, _MISSING)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            try:
                index = int(segment)
                if index < 0:
                    return _MISSING
                current = current[index]
            except (ValueError, IndexError):
                return _MISSING
        else:
            return _MISSING
        if current is _MISSING:
            return _MISSING
    return current


def evaluate_condition(event: EngineeringEvent, condition: Condition) -> bool:
    """Evaluate one condition without raising on incompatible event values."""

    actual = resolve_field(event, condition.field)
    operator = condition.operator

    if operator is ConditionOperator.EXISTS:
        exists = actual is not _MISSING
        return exists is condition.value
    if actual is _MISSING:
        return operator is ConditionOperator.NOT_EQUALS
    if operator is ConditionOperator.EQUALS:
        return bool(actual == condition.value)
    if operator is ConditionOperator.NOT_EQUALS:
        return bool(actual != condition.value)
    if operator is ConditionOperator.IN:
        return actual in condition.value
    if operator is ConditionOperator.CONTAINS:
        try:
            return condition.value in actual
        except TypeError:
            return False
    if operator is ConditionOperator.STARTS_WITH:
        return (
            isinstance(actual, str)
            and isinstance(condition.value, str)
            and actual.startswith(condition.value)
        )
    if operator is ConditionOperator.ENDS_WITH:
        return (
            isinstance(actual, str)
            and isinstance(condition.value, str)
            and actual.endswith(condition.value)
        )
    if operator is ConditionOperator.GREATER_THAN:
        return _ordered_compare(actual, condition.value, greater=True)
    if operator is ConditionOperator.LESS_THAN:
        return _ordered_compare(actual, condition.value, greater=False)
    return False


def evaluate_group(event: EngineeringEvent, group: ConditionGroup) -> bool:
    """Evaluate a nested condition group with short-circuit semantics."""

    def evaluate(item: Condition | ConditionGroup) -> bool:
        if isinstance(item, ConditionGroup):
            return evaluate_group(event, item)
        return evaluate_condition(event, item)

    if group.mode is ConditionMode.ALL:
        return all(evaluate(item) for item in group.conditions)
    return any(evaluate(item) for item in group.conditions)


def _ordered_compare(actual: Any, expected: Any, *, greater: bool) -> bool:
    try:
        return bool(actual > expected if greater else actual < expected)
    except TypeError:
        return False
