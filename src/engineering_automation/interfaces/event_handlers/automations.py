"""Translate routed engineering events into automation registrations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from engineering_automation.application.ports.automation import AutomationRegistrar
from engineering_automation.events import EngineeringEvent
from engineering_automation.interfaces.http.schemas import AutomationInput


class AutomationRegistrationEventHandler:
    """Register the automation definition carried by an event payload."""

    def __init__(self, registrar: AutomationRegistrar) -> None:
        self._registrar = registrar

    async def __call__(self, event: EngineeringEvent) -> Mapping[str, Any]:
        definition = AutomationInput.model_validate(dict(event.payload)).to_domain()
        registration = await self._registrar.execute(definition)
        return {
            "automationId": registration.automation_id,
            "workflowId": registration.workflow.identifier,
            "catalogId": registration.catalog.identifier,
            "workflowStateChanged": registration.workflow_state_changed,
        }
