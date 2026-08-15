"""Register an automation across workflow and catalog gateways."""

from __future__ import annotations

from engineering_automation.application.errors import (
    AutomationRollbackError,
    GatewayContractError,
)
from engineering_automation.application.ports.automation import AutomationCatalog, WorkflowManager
from engineering_automation.domain.automation import (
    AutomationDefinition,
    AutomationRegistration,
    CatalogReference,
    WorkflowReference,
)


class RegisterAutomation:
    """Synchronize desired workflow state before catalog registration."""

    def __init__(self, catalog: AutomationCatalog, workflows: WorkflowManager) -> None:
        self._catalog = catalog
        self._workflows = workflows

    async def execute(self, definition: AutomationDefinition) -> AutomationRegistration:
        original = await self._workflows.get(definition.workflow_id)
        self._validate_workflow(original, definition.workflow_id)

        workflow = original
        state_changed = original.active is not definition.active
        if state_changed:
            try:
                workflow = await self._workflows.set_active(
                    definition.workflow_id,
                    definition.active,
                )
                self._validate_workflow(workflow, definition.workflow_id, definition.active)
            except Exception as activation_error:
                await self._restore_workflow(definition, original, activation_error)
                raise

        try:
            catalog = await self._catalog.upsert(definition)
            self._validate_catalog(catalog, definition.identifier)
        except Exception as registration_error:
            if state_changed:
                await self._restore_workflow(definition, original, registration_error)
            raise

        return AutomationRegistration(
            automation_id=definition.identifier,
            workflow=workflow,
            catalog=catalog,
            workflow_state_changed=state_changed,
        )

    async def _restore_workflow(
        self,
        definition: AutomationDefinition,
        original: WorkflowReference,
        operation_error: Exception,
    ) -> None:
        try:
            restored = await self._workflows.set_active(
                definition.workflow_id,
                original.active,
            )
            self._validate_workflow(
                restored,
                definition.workflow_id,
                original.active,
            )
        except Exception as rollback_error:
            raise AutomationRollbackError(
                operation_error,
                rollback_error,
            ) from operation_error

    @staticmethod
    def _validate_workflow(
        workflow: WorkflowReference,
        expected_id: str,
        expected_active: bool | None = None,
    ) -> None:
        if workflow.identifier != expected_id:
            raise GatewayContractError(
                f"workflow gateway returned {workflow.identifier!r} for {expected_id!r}"
            )
        if expected_active is not None and workflow.active is not expected_active:
            raise GatewayContractError(
                f"workflow {expected_id!r} did not reach active={expected_active}"
            )

    @staticmethod
    def _validate_catalog(catalog: CatalogReference, expected_id: str) -> None:
        if catalog.identifier != expected_id:
            raise GatewayContractError(
                f"catalog gateway returned {catalog.identifier!r} for {expected_id!r}"
            )
