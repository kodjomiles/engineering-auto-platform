"""Typed HTTP contracts and domain translations for the automation API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from engineering_automation.domain.automation import (
    AutomationDefinition,
    AutomationReconciliation,
    AutomationReconciliationReport,
    AutomationRegistration,
    CatalogReference,
    ReconciliationState,
    WorkflowReference,
)
from engineering_automation.domain.inbound_webhooks import WebhookIngestionResult
from engineering_automation.events.models import (
    DestinationResult,
    DispatchStatus,
    EngineeringEvent,
)


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    """Base contract with strict fields and camel-case JSON names."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class AutomationInput(ApiModel):
    """Desired catalog record and n8n workflow activation state."""

    identifier: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=512)
    workflow_id: str = Field(min_length=1, max_length=256)
    active: bool = True
    properties: dict[str, Any] = Field(default_factory=dict)
    relations: dict[str, Any] = Field(default_factory=dict)

    def to_domain(self) -> AutomationDefinition:
        return AutomationDefinition(
            identifier=self.identifier,
            title=self.title,
            workflow_id=self.workflow_id,
            active=self.active,
            properties=self.properties,
            relations=self.relations,
        )


class WorkflowResponse(ApiModel):
    identifier: str
    name: str
    active: bool

    @classmethod
    def from_domain(cls, workflow: WorkflowReference) -> WorkflowResponse:
        return cls(identifier=workflow.identifier, name=workflow.name, active=workflow.active)


class CatalogResponse(ApiModel):
    identifier: str

    @classmethod
    def from_domain(cls, catalog: CatalogReference) -> CatalogResponse:
        return cls(identifier=catalog.identifier)


class RegistrationResponse(ApiModel):
    automation_id: str
    workflow: WorkflowResponse
    catalog: CatalogResponse
    workflow_state_changed: bool

    @classmethod
    def from_domain(cls, registration: AutomationRegistration) -> RegistrationResponse:
        return cls(
            automation_id=registration.automation_id,
            workflow=WorkflowResponse.from_domain(registration.workflow),
            catalog=CatalogResponse.from_domain(registration.catalog),
            workflow_state_changed=registration.workflow_state_changed,
        )


class ReconciliationRequest(ApiModel):
    automations: list[AutomationInput] = Field(min_length=1, max_length=100)


class ReconciliationOutcomeResponse(ApiModel):
    automation_id: str
    state: ReconciliationState
    registration: RegistrationResponse | None = None
    error: str | None = None

    @classmethod
    def from_domain(
        cls,
        outcome: AutomationReconciliation,
    ) -> ReconciliationOutcomeResponse:
        registration = (
            RegistrationResponse.from_domain(outcome.registration)
            if outcome.registration is not None
            else None
        )
        return cls(
            automation_id=outcome.automation_id,
            state=outcome.state,
            registration=registration,
            error=outcome.error,
        )


class ReconciliationResponse(ApiModel):
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    outcomes: list[ReconciliationOutcomeResponse]

    @classmethod
    def from_domain(cls, report: AutomationReconciliationReport) -> ReconciliationResponse:
        return cls(
            succeeded=report.succeeded,
            failed=report.failed,
            outcomes=[
                ReconciliationOutcomeResponse.from_domain(outcome) for outcome in report.outcomes
            ],
        )


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"
    version: str


class ApiError(ApiModel):
    code: str
    message: str


class ApiErrorResponse(ApiModel):
    detail: ApiError


class WebhookEventInput(ApiModel):
    """Provider-neutral event carried by a signed webhook request."""

    event_id: str = Field(min_length=1, max_length=256)
    event_type: str = Field(min_length=1, max_length=256)
    subject: str = Field(min_length=1, max_length=512)
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)

    def to_domain(self, source: str) -> EngineeringEvent:
        return EngineeringEvent(
            event_id=self.event_id,
            source=source,
            event_type=self.event_type,
            subject=self.subject,
            occurred_at=self.occurred_at,
            payload=self.payload,
            labels=self.labels,
        )


class DestinationResponse(ApiModel):
    destination: str
    status: DispatchStatus
    duration_ms: int = Field(ge=0)
    output: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, result: DestinationResult) -> DestinationResponse:
        return cls(
            destination=result.destination,
            status=result.status,
            duration_ms=result.duration_ms,
            output=dict(result.output) if result.output is not None else None,
            error=result.error,
        )


class WebhookIngestionResponse(ApiModel):
    webhook_id: str
    event_id: str
    state: Literal["accepted", "duplicate"]
    matched_rule_ids: list[str]
    destinations: list[DestinationResponse]

    @classmethod
    def from_domain(cls, result: WebhookIngestionResult) -> WebhookIngestionResponse:
        dispatch = result.dispatch
        return cls(
            webhook_id=result.webhook_id,
            event_id=result.event_id,
            state=result.state.value,
            matched_rule_ids=list(dispatch.matched_rule_ids) if dispatch is not None else [],
            destinations=(
                [DestinationResponse.from_domain(item) for item in dispatch.results]
                if dispatch is not None
                else []
            ),
        )
