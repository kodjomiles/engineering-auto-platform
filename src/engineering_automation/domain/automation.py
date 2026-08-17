"""Provider-neutral automation registration entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from engineering_automation.domain.values import deep_freeze


@dataclass(frozen=True, slots=True)
class AutomationDefinition:
    """Desired catalog and workflow state for one engineering automation."""

    identifier: str
    title: str
    workflow_id: str
    active: bool = True
    properties: Mapping[str, Any] = field(default_factory=dict)
    relations: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("identifier", "title", "workflow_id"):
            normalized = getattr(self, name).strip()
            if not normalized:
                raise ValueError(f"{name} cannot be empty")
            object.__setattr__(self, name, normalized)
        object.__setattr__(self, "properties", deep_freeze(self.properties))
        object.__setattr__(self, "relations", deep_freeze(self.relations))


@dataclass(frozen=True, slots=True)
class WorkflowReference:
    """Provider-neutral workflow state returned by a workflow gateway."""

    identifier: str
    name: str
    active: bool

    def __post_init__(self) -> None:
        identifier = self.identifier.strip()
        name = self.name.strip()
        if not identifier:
            raise ValueError("workflow identifier cannot be empty")
        if not name:
            raise ValueError("workflow name cannot be empty")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "name", name)


@dataclass(frozen=True, slots=True)
class CatalogReference:
    """Provider-neutral catalog record returned by a catalog gateway."""

    identifier: str

    def __post_init__(self) -> None:
        identifier = self.identifier.strip()
        if not identifier:
            raise ValueError("catalog identifier cannot be empty")
        object.__setattr__(self, "identifier", identifier)


@dataclass(frozen=True, slots=True)
class AutomationRegistration:
    """Completed registration across workflow and catalog boundaries."""

    automation_id: str
    workflow: WorkflowReference
    catalog: CatalogReference
    workflow_state_changed: bool

    def __post_init__(self) -> None:
        automation_id = self.automation_id.strip()
        if not automation_id:
            raise ValueError("automation_id cannot be empty")
        object.__setattr__(self, "automation_id", automation_id)
