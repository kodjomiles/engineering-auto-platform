"""Port request and response domain models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Entity:
    """Entity payload accepted by Port's catalog API."""

    identifier: str
    title: str | None = None
    icon: str | None = None
    team: str | tuple[str, ...] | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)
    relations: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("identifier cannot be empty")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "identifier": self.identifier,
            "properties": dict(self.properties),
            "relations": dict(self.relations),
        }
        if self.title is not None:
            payload["title"] = self.title
        if self.icon is not None:
            payload["icon"] = self.icon
        if self.team is not None:
            payload["team"] = list(self.team) if isinstance(self.team, tuple) else self.team
        return payload


@dataclass(frozen=True, slots=True)
class EntitySearchPage:
    """One page returned by Port's blueprint entity search."""

    entities: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
