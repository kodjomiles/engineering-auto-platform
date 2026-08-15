"""Port implementation of the automation catalog port."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import Any, Protocol

from engineering_automation.domain.automation import AutomationDefinition, CatalogReference
from engineering_automation.port.models import Entity


class PortEntityClient(Protocol):
    """Subset of PortClient required by this adapter."""

    def upsert_entity(
        self,
        blueprint_identifier: str,
        entity: Entity,
        *,
        merge: bool = True,
        create_missing_related_entities: bool = False,
        validation_only: bool = False,
        run_id: str | None = None,
    ) -> Awaitable[Mapping[str, Any]]: ...


class PortAutomationCatalog:
    """Persist automation definitions as Port catalog entities."""

    def __init__(self, client: PortEntityClient, blueprint_identifier: str) -> None:
        blueprint = blueprint_identifier.strip()
        if not blueprint:
            raise ValueError("blueprint_identifier cannot be empty")
        self._client = client
        self._blueprint = blueprint

    async def upsert(self, definition: AutomationDefinition) -> CatalogReference:
        properties = {
            **dict(definition.properties),
            "workflowId": definition.workflow_id,
            "active": definition.active,
        }
        await self._client.upsert_entity(
            self._blueprint,
            Entity(
                identifier=definition.identifier,
                title=definition.title,
                properties=properties,
                relations=definition.relations,
            ),
        )
        return CatalogReference(definition.identifier)
