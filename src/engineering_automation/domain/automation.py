"""Provider-neutral automation registration entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
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


class ReconciliationState(str, Enum):
    """Outcome of reconciling one automation definition."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AutomationReconciliation:
    """Auditable outcome for one definition in a reconciliation run."""

    automation_id: str
    state: ReconciliationState
    registration: AutomationRegistration | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        automation_id = self.automation_id.strip()
        if not automation_id:
            raise ValueError("automation_id cannot be empty")
        object.__setattr__(self, "automation_id", automation_id)

        if self.state is ReconciliationState.SUCCEEDED:
            if self.registration is None or self.error is not None:
                raise ValueError("successful reconciliation requires only a registration")
            if self.registration.automation_id != automation_id:
                raise ValueError("registration automation_id must match reconciliation")
        elif self.state is ReconciliationState.FAILED:
            error = (self.error or "").strip()
            if self.registration is not None or not error:
                raise ValueError("failed reconciliation requires only an error")
            object.__setattr__(self, "error", error)
        else:
            raise ValueError(f"unsupported reconciliation state: {self.state!r}")


@dataclass(frozen=True, slots=True)
class AutomationReconciliationReport:
    """Ordered outcomes from reconciling a collection of automations."""

    outcomes: tuple[AutomationReconciliation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcomes", tuple(self.outcomes))

    @property
    def succeeded(self) -> int:
        return sum(outcome.state is ReconciliationState.SUCCEEDED for outcome in self.outcomes)

    @property
    def failed(self) -> int:
        return len(self.outcomes) - self.succeeded

    @property
    def has_failures(self) -> bool:
        return self.failed > 0
