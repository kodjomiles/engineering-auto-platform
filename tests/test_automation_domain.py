from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType
from typing import Any

import pytest

from engineering_automation.domain.automation import (
    AutomationDefinition,
    AutomationReconciliation,
    AutomationReconciliationReport,
    AutomationRegistration,
    CatalogReference,
    ReconciliationState,
    WorkflowReference,
)


def test_definition_normalizes_identity_and_detaches_nested_values() -> None:
    properties: dict[str, Any] = {
        "owners": ["platform"],
        "metadata": {"tier": 1},
    }
    definition = AutomationDefinition(
        " deploy-service ",
        " Deploy service ",
        " workflow-1 ",
        properties=properties,
        relations={"service": "payments"},
    )
    properties["owners"].append("payments")

    assert definition.identifier == "deploy-service"
    assert definition.title == "Deploy service"
    assert definition.workflow_id == "workflow-1"
    assert definition.properties["owners"] == ("platform",)
    assert isinstance(definition.properties, MappingProxyType)
    assert isinstance(definition.properties["metadata"], MappingProxyType)


@pytest.mark.parametrize("field", ["identifier", "title", "workflow_id"])
def test_definition_rejects_blank_required_values(field: str) -> None:
    values = {
        "identifier": "automation-1",
        "title": "Deploy service",
        "workflow_id": "workflow-1",
    }
    values[field] = "  "

    with pytest.raises(ValueError, match=f"{field} cannot be empty"):
        AutomationDefinition(
            values["identifier"],
            values["title"],
            values["workflow_id"],
        )


def test_references_and_registration_normalize_identifiers() -> None:
    workflow = WorkflowReference(" workflow-1 ", " Deploy service ", True)
    catalog = CatalogReference(" automation-1 ")
    registration = AutomationRegistration(" automation-1 ", workflow, catalog, True)

    assert workflow == WorkflowReference("workflow-1", "Deploy service", True)
    assert catalog.identifier == "automation-1"
    assert registration.automation_id == "automation-1"


@pytest.mark.parametrize(
    "factory, message",
    [
        (lambda: WorkflowReference(" ", "Deploy", True), "workflow identifier"),
        (lambda: WorkflowReference("workflow-1", " ", True), "workflow name"),
        (lambda: CatalogReference(" "), "catalog identifier"),
        (
            lambda: AutomationRegistration(
                " ",
                WorkflowReference("workflow-1", "Deploy", True),
                CatalogReference("automation-1"),
                False,
            ),
            "automation_id",
        ),
    ],
)
def test_references_reject_blank_identity(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def make_registration(identifier: str = "automation-1") -> AutomationRegistration:
    return AutomationRegistration(
        identifier,
        WorkflowReference("workflow-1", "Deploy", True),
        CatalogReference(identifier),
        True,
    )


def test_reconciliation_report_counts_ordered_outcomes() -> None:
    report = AutomationReconciliationReport(
        (
            AutomationReconciliation(
                "automation-1",
                ReconciliationState.SUCCEEDED,
                registration=make_registration(),
            ),
            AutomationReconciliation(
                "automation-2",
                ReconciliationState.FAILED,
                error="RuntimeError: unavailable",
            ),
        )
    )

    assert [outcome.automation_id for outcome in report.outcomes] == [
        "automation-1",
        "automation-2",
    ]
    assert report.succeeded == 1
    assert report.failed == 1
    assert report.has_failures


@pytest.mark.parametrize(
    "outcome, message",
    [
        (
            lambda: AutomationReconciliation(
                "automation-1",
                ReconciliationState.SUCCEEDED,
            ),
            "successful reconciliation",
        ),
        (
            lambda: AutomationReconciliation(
                "automation-1",
                ReconciliationState.FAILED,
            ),
            "failed reconciliation",
        ),
        (
            lambda: AutomationReconciliation(
                "automation-1",
                ReconciliationState.SUCCEEDED,
                registration=make_registration("another-automation"),
            ),
            "must match",
        ),
    ],
)
def test_reconciliation_rejects_inconsistent_outcomes(
    outcome: Callable[[], AutomationReconciliation],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        outcome()
