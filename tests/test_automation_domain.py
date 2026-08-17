from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType
from typing import Any

import pytest

from engineering_automation.domain.automation import (
    AutomationDefinition,
    AutomationRegistration,
    CatalogReference,
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
