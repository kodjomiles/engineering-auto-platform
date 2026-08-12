"""Deterministic event-to-destination routing."""

from __future__ import annotations

from collections.abc import Iterable

from engineering_automation.events.conditions import evaluate_group
from engineering_automation.events.models import EngineeringEvent, RoutePlan, RoutingRule


class EventRouter:
    """Evaluate immutable routing rules by priority and identifier."""

    def __init__(self, rules: Iterable[RoutingRule]) -> None:
        self._rules = self._prepare_rules(rules)

    @property
    def rules(self) -> tuple[RoutingRule, ...]:
        return self._rules

    def replace_rules(self, rules: Iterable[RoutingRule]) -> None:
        """Atomically replace the complete routing configuration."""

        self._rules = self._prepare_rules(rules)

    def route(self, event: EngineeringEvent) -> RoutePlan:
        matched_rule_ids: list[str] = []
        destinations: list[str] = []
        seen_destinations: set[str] = set()

        for rule in self._rules:
            if not rule.enabled or not evaluate_group(event, rule.condition):
                continue
            matched_rule_ids.append(rule.identifier)
            for destination in rule.destinations:
                if destination not in seen_destinations:
                    destinations.append(destination)
                    seen_destinations.add(destination)

        return RoutePlan(
            event_id=event.event_id,
            matched_rule_ids=tuple(matched_rule_ids),
            destinations=tuple(destinations),
        )

    @staticmethod
    def _prepare_rules(rules: Iterable[RoutingRule]) -> tuple[RoutingRule, ...]:
        prepared = tuple(rules)
        identifiers = [rule.identifier for rule in prepared]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("routing rule identifiers must be unique")
        return tuple(sorted(prepared, key=lambda rule: (-rule.priority, rule.identifier)))
