from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from engineering_automation.application.errors import (
    AutomationRollbackError,
    GatewayContractError,
)
from engineering_automation.application.use_cases.register_automation import RegisterAutomation
from engineering_automation.domain.automation import (
    AutomationDefinition,
    AutomationRegistration,
    CatalogReference,
    WorkflowReference,
)


class FakeCatalog:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.result = CatalogReference("automation-1")
        self.error: Exception | None = None

    async def upsert(self, definition: AutomationDefinition) -> CatalogReference:
        self.calls.append(f"catalog:{definition.identifier}")
        if self.error:
            raise self.error
        return self.result


class FakeWorkflows:
    def __init__(self, calls: list[str], *, active: bool = False) -> None:
        self.calls = calls
        self.current = WorkflowReference("workflow-1", "Deploy service", active)
        self.get_error: Exception | None = None
        self.set_results: list[WorkflowReference | Exception] = []

    async def get(self, workflow_id: str) -> WorkflowReference:
        self.calls.append(f"get:{workflow_id}")
        if self.get_error:
            raise self.get_error
        return self.current

    async def set_active(self, workflow_id: str, active: bool) -> WorkflowReference:
        self.calls.append(f"set:{workflow_id}:{active}")
        if self.set_results:
            result = self.set_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return WorkflowReference(workflow_id, self.current.name, active)


def definition(*, active: bool = True) -> AutomationDefinition:
    return AutomationDefinition(
        "automation-1",
        "Deploy service",
        "workflow-1",
        active=active,
    )


def execute(
    catalog: FakeCatalog,
    workflows: FakeWorkflows,
    automation: AutomationDefinition | None = None,
) -> AutomationRegistration:
    return asyncio.run(RegisterAutomation(catalog, workflows).execute(automation or definition()))


def test_registers_after_changing_workflow_to_desired_state() -> None:
    calls: list[str] = []
    catalog = FakeCatalog(calls)
    workflows = FakeWorkflows(calls)

    registration = execute(catalog, workflows)

    assert calls == [
        "get:workflow-1",
        "set:workflow-1:True",
        "catalog:automation-1",
    ]
    assert registration.workflow.active
    assert registration.workflow_state_changed


def test_skips_state_change_when_workflow_already_matches() -> None:
    calls: list[str] = []
    catalog = FakeCatalog(calls)
    workflows = FakeWorkflows(calls, active=True)

    registration = execute(catalog, workflows)

    assert calls == ["get:workflow-1", "catalog:automation-1"]
    assert not registration.workflow_state_changed


def test_supports_deactivating_a_workflow() -> None:
    calls: list[str] = []
    catalog = FakeCatalog(calls)
    workflows = FakeWorkflows(calls, active=True)

    registration = execute(catalog, workflows, definition(active=False))

    assert calls[1] == "set:workflow-1:False"
    assert not registration.workflow.active


def test_read_failure_prevents_all_mutation() -> None:
    calls: list[str] = []
    catalog = FakeCatalog(calls)
    workflows = FakeWorkflows(calls)
    workflows.get_error = RuntimeError("n8n unavailable")

    with pytest.raises(RuntimeError, match="n8n unavailable"):
        execute(catalog, workflows)
    assert calls == ["get:workflow-1"]


def test_catalog_failure_restores_original_workflow_state() -> None:
    calls: list[str] = []
    catalog = FakeCatalog(calls)
    catalog.error = RuntimeError("Port unavailable")
    workflows = FakeWorkflows(calls)

    with pytest.raises(RuntimeError, match="Port unavailable"):
        execute(catalog, workflows)

    assert calls == [
        "get:workflow-1",
        "set:workflow-1:True",
        "catalog:automation-1",
        "set:workflow-1:False",
    ]


def test_catalog_failure_does_not_rollback_an_unchanged_workflow() -> None:
    calls: list[str] = []
    catalog = FakeCatalog(calls)
    catalog.error = RuntimeError("Port unavailable")
    workflows = FakeWorkflows(calls, active=True)

    with pytest.raises(RuntimeError, match="Port unavailable"):
        execute(catalog, workflows)
    assert calls == ["get:workflow-1", "catalog:automation-1"]


def test_activation_contract_failure_is_compensated() -> None:
    calls: list[str] = []
    catalog = FakeCatalog(calls)
    workflows = FakeWorkflows(calls)
    workflows.set_results = [
        WorkflowReference("workflow-1", "Deploy", False),
        WorkflowReference("workflow-1", "Deploy", False),
    ]

    with pytest.raises(GatewayContractError, match="did not reach"):
        execute(catalog, workflows)
    assert calls[-1] == "set:workflow-1:False"
    assert not any(call.startswith("catalog:") for call in calls)


def test_catalog_contract_failure_is_compensated() -> None:
    calls: list[str] = []
    catalog = FakeCatalog(calls)
    catalog.result = CatalogReference("wrong-automation")
    workflows = FakeWorkflows(calls)

    with pytest.raises(GatewayContractError, match="catalog gateway returned"):
        execute(catalog, workflows)
    assert calls[-1] == "set:workflow-1:False"


def test_rollback_failure_preserves_both_errors() -> None:
    calls: list[str] = []
    catalog = FakeCatalog(calls)
    registration_error = RuntimeError("Port unavailable")
    rollback_error = RuntimeError("n8n unavailable")
    catalog.error = registration_error
    workflows = FakeWorkflows(calls)
    workflows.set_results = [
        WorkflowReference("workflow-1", "Deploy", True),
        rollback_error,
    ]

    with pytest.raises(AutomationRollbackError) as captured:
        execute(catalog, workflows)

    assert captured.value.registration_error is registration_error
    assert captured.value.rollback_error is rollback_error
    assert "Port unavailable" in str(captured.value)
    assert "n8n unavailable" in str(captured.value)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda catalog, workflows: setattr(
                workflows,
                "current",
                WorkflowReference("wrong-workflow", "Deploy", False),
            ),
            "workflow gateway returned",
        ),
        (
            lambda catalog, workflows: setattr(
                catalog,
                "result",
                CatalogReference("wrong-automation"),
            ),
            "catalog gateway returned",
        ),
    ],
)
def test_rejects_gateway_responses_for_another_resource(
    mutate: Callable[[FakeCatalog, FakeWorkflows], None],
    message: str,
) -> None:
    calls: list[str] = []
    catalog = FakeCatalog(calls)
    workflows = FakeWorkflows(calls, active=True)
    mutate(catalog, workflows)

    with pytest.raises(GatewayContractError, match=message):
        execute(catalog, workflows)
