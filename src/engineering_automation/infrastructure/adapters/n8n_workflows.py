"""n8n implementation of the workflow manager port."""

from __future__ import annotations

from typing import Protocol

from engineering_automation.domain.automation import WorkflowReference
from engineering_automation.n8n.models import Workflow


class N8nWorkflowClient(Protocol):
    """Subset of N8nClient required by this adapter."""

    async def get_workflow(self, workflow_id: str) -> Workflow: ...

    async def activate_workflow(self, workflow_id: str) -> Workflow: ...

    async def deactivate_workflow(self, workflow_id: str) -> Workflow: ...


class N8nWorkflowManager:
    """Translate n8n workflow responses into provider-neutral references."""

    def __init__(self, client: N8nWorkflowClient) -> None:
        self._client = client

    async def get(self, workflow_id: str) -> WorkflowReference:
        return self._reference(await self._client.get_workflow(workflow_id))

    async def set_active(self, workflow_id: str, active: bool) -> WorkflowReference:
        if active:
            workflow = await self._client.activate_workflow(workflow_id)
        else:
            workflow = await self._client.deactivate_workflow(workflow_id)
        return self._reference(workflow)

    @staticmethod
    def _reference(workflow: Workflow) -> WorkflowReference:
        return WorkflowReference(workflow.identifier, workflow.name, workflow.active)
