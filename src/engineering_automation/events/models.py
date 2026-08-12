"""Immutable contracts for engineering events and their routing lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any


def _freeze(value: Any) -> Any:
    """Recursively detach mutable event data from its caller."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


class ConditionOperator(StrEnum):
    """Supported comparisons for observable event values."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    EXISTS = "exists"
    IN = "in"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"


class ConditionMode(StrEnum):
    """How conditions inside one group are combined."""

    ALL = "all"
    ANY = "any"


@dataclass(frozen=True, slots=True)
class EngineeringEvent:
    """One provider-neutral event entering the automation platform."""

    event_id: str
    source: str
    event_type: str
    subject: str
    occurred_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("event_id", "source", "event_type", "subject"):
            value = getattr(self, name)
            if not value.strip():
                raise ValueError(f"{name} cannot be empty")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        normalized_labels = {
            str(name).strip(): str(value).strip()
            for name, value in self.labels.items()
            if str(name).strip()
        }
        object.__setattr__(self, "payload", _freeze(self.payload))
        object.__setattr__(self, "labels", MappingProxyType(normalized_labels))


@dataclass(frozen=True, slots=True)
class Condition:
    """One comparison against an event field path."""

    field: str
    operator: ConditionOperator
    value: Any = None

    def __post_init__(self) -> None:
        normalized = self.field.strip()
        if not normalized:
            raise ValueError("condition field cannot be empty")
        if normalized.startswith(".") or normalized.endswith(".") or ".." in normalized:
            raise ValueError("condition field contains an empty path segment")
        if self.operator is ConditionOperator.EXISTS and not isinstance(self.value, bool):
            raise ValueError("exists conditions require a boolean value")
        if self.operator is ConditionOperator.IN and (
            isinstance(self.value, (str, bytes))
            or not isinstance(self.value, (tuple, list, set, frozenset))
        ):
            raise ValueError("in conditions require a collection value")
        object.__setattr__(self, "field", normalized)
        object.__setattr__(self, "value", _freeze(self.value))


@dataclass(frozen=True, slots=True)
class ConditionGroup:
    """A recursively nestable all/any condition group."""

    mode: ConditionMode
    conditions: tuple[Condition | ConditionGroup, ...]

    def __post_init__(self) -> None:
        if not self.conditions:
            raise ValueError("condition group cannot be empty")


@dataclass(frozen=True, slots=True)
class RoutingRule:
    """Map matching events to one or more named destinations."""

    identifier: str
    destinations: tuple[str, ...]
    condition: ConditionGroup
    priority: int = 0
    enabled: bool = True

    def __post_init__(self) -> None:
        identifier = self.identifier.strip()
        if not identifier:
            raise ValueError("rule identifier cannot be empty")
        normalized_destinations = tuple(
            destination.strip() for destination in self.destinations if destination.strip()
        )
        if not normalized_destinations:
            raise ValueError("routing rule requires at least one destination")
        if len(set(normalized_destinations)) != len(normalized_destinations):
            raise ValueError("routing rule destinations must be unique")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "destinations", normalized_destinations)


@dataclass(frozen=True, slots=True)
class RoutePlan:
    """Deterministic result of evaluating an event against routing rules."""

    event_id: str
    matched_rule_ids: tuple[str, ...]
    destinations: tuple[str, ...]


class DispatchStatus(StrEnum):
    """Result of delivering an event to one routed destination."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    MISSING_HANDLER = "missing_handler"


@dataclass(frozen=True, slots=True)
class DestinationResult:
    """Audit record for one destination invocation."""

    destination: str
    status: DispatchStatus
    duration_ms: int
    output: Mapping[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.destination.strip():
            raise ValueError("destination cannot be empty")
        if self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")
        if self.output is not None:
            object.__setattr__(self, "output", _freeze(self.output))


@dataclass(frozen=True, slots=True)
class DispatchReport:
    """Final dispatch result preserving route order."""

    event_id: str
    matched_rule_ids: tuple[str, ...]
    results: tuple[DestinationResult, ...]

    @property
    def succeeded(self) -> bool:
        return bool(self.results) and all(
            result.status is DispatchStatus.SUCCEEDED for result in self.results
        )
