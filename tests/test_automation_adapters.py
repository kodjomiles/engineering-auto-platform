from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from engineering_automation.domain.automation import AutomationDefinition
from engineering_automation.infrastructure.adapters.n8n_workflows import N8nWorkflowManager
from engineering_automation.infrastructure.adapters.port_catalog import PortAutomationCatalog
from engineering_automation.n8n.models import Workflow
from engineering_automation.port.models import Entity


class FakePortClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Entity]] = []

    async def upsert_entity(
        self,
        blueprint_identifier: str,
        entity: Entity,
        *,
        merge: bool = True,
        create_missing_related_entities: bool = False,
        validation_only: bool = False,
        run_id: str | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append((blueprint_identifier, entity))
        return {"entity": entity.to_payload()}


class FakeN8nClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_workflow(self, workflow_id: str) -> Workflow:
        self.calls.append(f"get:{workflow_id}")
        return Workflow(workflow_id, "Deploy service", False)

    async def activate_workflow(self, workflow_id: str) -> Workflow:
        self.calls.append(f"activate:{workflow_id}")
        return Workflow(workflow_id, "Deploy service", True)

    async def deactivate_workflow(self, workflow_id: str) -> Workflow:
        self.calls.append(f"deactivate:{workflow_id}")
        return Workflow(workflow_id, "Deploy service", False)


def test_port_adapter_maps_definition_to_catalog_entity() -> None:
    client = FakePortClient()
    adapter = PortAutomationCatalog(client, "engineeringAutomation")
    definition = AutomationDefinition(
        "deploy-service",
        "Deploy service",
        "workflow-1",
        properties={"owner": "platform", "active": "stale"},
        relations={"service": "payments"},
    )

    result = asyncio.run(adapter.upsert(definition))

    blueprint, entity = client.calls[0]
    assert blueprint == "engineeringAutomation"
    assert entity.to_payload() == {
        "identifier": "deploy-service",
        "title": "Deploy service",
        "properties": {
            "owner": "platform",
            "active": True,
            "workflowId": "workflow-1",
        },
        "relations": {"service": "payments"},
    }
    assert result.identifier == "deploy-service"


def test_port_adapter_rejects_blank_blueprint() -> None:
    with pytest.raises(ValueError, match="blueprint_identifier"):
        PortAutomationCatalog(FakePortClient(), " ")


def test_n8n_adapter_maps_workflow_and_selects_activation_operation() -> None:
    client = FakeN8nClient()
    adapter = N8nWorkflowManager(client)

    current = asyncio.run(adapter.get("workflow-1"))
    active = asyncio.run(adapter.set_active("workflow-1", True))
    inactive = asyncio.run(adapter.set_active("workflow-1", False))

    assert current.identifier == "workflow-1"
    assert not current.active
    assert active.active
    assert not inactive.active
    assert client.calls == [
        "get:workflow-1",
        "activate:workflow-1",
        "deactivate:workflow-1",
    ]
