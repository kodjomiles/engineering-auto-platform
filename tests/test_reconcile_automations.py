from __future__ import annotations

import asyncio

import pytest

from engineering_automation.application.use_cases.reconcile_automations import (
    ReconcileAutomations,
)
from engineering_automation.domain.automation import (
    AutomationDefinition,
    AutomationRegistration,
    CatalogReference,
    ReconciliationState,
    WorkflowReference,
)


def definition(identifier: str) -> AutomationDefinition:
    return AutomationDefinition(
        identifier,
        f"Automation {identifier}",
        f"workflow-{identifier}",
    )


def registration(identifier: str) -> AutomationRegistration:
    return AutomationRegistration(
        identifier,
        WorkflowReference(f"workflow-{identifier}", f"Workflow {identifier}", True),
        CatalogReference(identifier),
        True,
    )


class FakeRegistrar:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures: set[str] = set()
        self.results: dict[str, AutomationRegistration] = {}
        self.active = 0
        self.max_active = 0

    async def execute(self, item: AutomationDefinition) -> AutomationRegistration:
        self.calls.append(item.identifier)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.001)
            if item.identifier in self.failures:
                raise RuntimeError(f"cannot reconcile {item.identifier}")
            return self.results.get(item.identifier, registration(item.identifier))
        finally:
            self.active -= 1


def test_reconciles_with_bounded_concurrency_and_stable_output_order() -> None:
    registrar = FakeRegistrar()
    definitions = tuple(definition(f"automation-{index}") for index in range(6))

    report = asyncio.run(ReconcileAutomations(registrar, max_concurrency=2).execute(definitions))

    assert registrar.max_active == 2
    assert [outcome.automation_id for outcome in report.outcomes] == [
        item.identifier for item in definitions
    ]
    assert report.succeeded == 6
    assert not report.has_failures


def test_failure_is_isolated_and_recorded_without_stopping_other_items() -> None:
    registrar = FakeRegistrar()
    registrar.failures.add("automation-2")

    report = asyncio.run(
        ReconcileAutomations(registrar).execute(
            (definition("automation-1"), definition("automation-2"), definition("automation-3"))
        )
    )

    assert registrar.calls == ["automation-1", "automation-2", "automation-3"]
    assert [outcome.state for outcome in report.outcomes] == [
        ReconciliationState.SUCCEEDED,
        ReconciliationState.FAILED,
        ReconciliationState.SUCCEEDED,
    ]
    assert report.outcomes[1].error == "RuntimeError: cannot reconcile automation-2"
    assert report.failed == 1


def test_invalid_registrar_result_becomes_an_auditable_failure() -> None:
    registrar = FakeRegistrar()
    registrar.results["automation-1"] = registration("another-automation")

    report = asyncio.run(ReconcileAutomations(registrar).execute((definition("automation-1"),)))

    assert report.outcomes[0].state is ReconciliationState.FAILED
    assert "registration automation_id must match" in (report.outcomes[0].error or "")


def test_duplicate_identifiers_are_rejected_before_any_registration() -> None:
    registrar = FakeRegistrar()

    with pytest.raises(ValueError, match="duplicate automation identifiers: automation-1"):
        asyncio.run(
            ReconcileAutomations(registrar).execute(
                (definition("automation-1"), definition("automation-1"))
            )
        )

    assert registrar.calls == []


def test_empty_reconciliation_returns_an_empty_successful_report() -> None:
    report = asyncio.run(ReconcileAutomations(FakeRegistrar()).execute(()))

    assert report.outcomes == ()
    assert report.succeeded == 0
    assert report.failed == 0
    assert not report.has_failures


def test_rejects_non_positive_concurrency() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        ReconcileAutomations(FakeRegistrar(), max_concurrency=0)
