"""Ports required by automation registration use cases."""

from __future__ import annotations

from typing import Protocol

from engineering_automation.domain.automation import (
    AutomationDefinition,
    AutomationRegistration,
    CatalogReference,
    WorkflowReference,
)


class AutomationCatalog(Protocol):
    """Register provider-neutral automation definitions in a catalog."""

    async def upsert(self, definition: AutomationDefinition) -> CatalogReference: ...


class WorkflowManager(Protocol):
    """Read and change provider-neutral workflow activation state."""

    async def get(self, workflow_id: str) -> WorkflowReference: ...

    async def set_active(self, workflow_id: str, active: bool) -> WorkflowReference: ...


class AutomationRegistrar(Protocol):
    """Register one provider-neutral automation definition."""

    async def execute(self, definition: AutomationDefinition) -> AutomationRegistration: ...
