"""Automation registration composition root."""

from engineering_automation.application.use_cases.reconcile_automations import (
    ReconcileAutomations,
)
from engineering_automation.application.use_cases.register_automation import RegisterAutomation
from engineering_automation.infrastructure.adapters.n8n_workflows import N8nWorkflowManager
from engineering_automation.infrastructure.adapters.port_catalog import PortAutomationCatalog
from engineering_automation.n8n.client import N8nClient
from engineering_automation.port.client import PortClient


def build_automation_registration(
    port_client: PortClient,
    n8n_client: N8nClient,
    *,
    blueprint_identifier: str,
) -> RegisterAutomation:
    """Wire provider clients to the automation registration use case."""

    return RegisterAutomation(
        PortAutomationCatalog(port_client, blueprint_identifier),
        N8nWorkflowManager(n8n_client),
    )


def build_automation_reconciliation(
    port_client: PortClient,
    n8n_client: N8nClient,
    *,
    blueprint_identifier: str,
    max_concurrency: int = 5,
) -> ReconcileAutomations:
    """Wire the single-registration workflow into a bounded batch coordinator."""

    registrar = build_automation_registration(
        port_client,
        n8n_client,
        blueprint_identifier=blueprint_identifier,
    )
    return ReconcileAutomations(registrar, max_concurrency=max_concurrency)
