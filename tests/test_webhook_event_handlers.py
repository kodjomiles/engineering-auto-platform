from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest

from engineering_automation.application.ports.automation import AutomationRegistrar
from engineering_automation.application.use_cases.ingest_webhook import WebhookPayloadError
from engineering_automation.domain.automation import (
    AutomationDefinition,
    AutomationRegistration,
    CatalogReference,
    WorkflowReference,
)
from engineering_automation.events import (
    Condition,
    ConditionGroup,
    ConditionMode,
    ConditionOperator,
    DispatchStatus,
    EngineeringEvent,
    EventDispatcher,
    EventRouter,
    RoutingRule,
)
from engineering_automation.interfaces.event_handlers.automations import (
    AutomationRegistrationEventHandler,
)
from engineering_automation.interfaces.event_handlers.routing import RoutingEventProcessor
from engineering_automation.interfaces.http.webhook_decoder import JsonWebhookEventDecoder


class FakeRegistrar(AutomationRegistrar):
    def __init__(self) -> None:
        self.definitions: list[AutomationDefinition] = []

    async def execute(self, definition: AutomationDefinition) -> AutomationRegistration:
        self.definitions.append(definition)
        return AutomationRegistration(
            definition.identifier,
            WorkflowReference(definition.workflow_id, definition.title, definition.active),
            CatalogReference(definition.identifier),
            True,
        )


def automation_event(*, payload: object | None = None) -> EngineeringEvent:
    return EngineeringEvent(
        event_id="event-1",
        source="github",
        event_type="automation.registration.requested",
        subject="deploy-payments",
        occurred_at=datetime(2030, 1, 1, tzinfo=UTC),
        payload=payload
        if isinstance(payload, dict)
        else {
            "identifier": "deploy-payments",
            "title": "Deploy payments",
            "workflowId": "workflow-42",
            "active": True,
            "properties": {"owner": "platform"},
        },
    )


def test_automation_handler_translates_event_payload_through_registrar_port() -> None:
    registrar = FakeRegistrar()
    output = asyncio.run(AutomationRegistrationEventHandler(registrar)(automation_event()))

    assert output == {
        "automationId": "deploy-payments",
        "workflowId": "workflow-42",
        "catalogId": "deploy-payments",
        "workflowStateChanged": True,
    }
    assert registrar.definitions[0].properties == {"owner": "platform"}


def test_routing_processor_routes_before_dispatching() -> None:
    registrar = FakeRegistrar()
    condition = ConditionGroup(
        ConditionMode.ALL,
        (
            Condition(
                "event_type",
                ConditionOperator.EQUALS,
                "automation.registration.requested",
            ),
        ),
    )
    processor = RoutingEventProcessor(
        EventRouter((RoutingRule("register", ("automation",), condition),)),
        EventDispatcher({"automation": AutomationRegistrationEventHandler(registrar)}),
    )

    report = asyncio.run(processor.process(automation_event()))

    assert report.matched_rule_ids == ("register",)
    assert report.results[0].status is DispatchStatus.SUCCEEDED
    assert report.results[0].output == {
        "automationId": "deploy-payments",
        "workflowId": "workflow-42",
        "catalogId": "deploy-payments",
        "workflowStateChanged": True,
    }


def test_invalid_automation_payload_is_an_isolated_destination_failure() -> None:
    event = automation_event(payload={"identifier": "missing-other-fields"})
    processor = RoutingEventProcessor(
        EventRouter(
            (
                RoutingRule(
                    "all",
                    ("automation",),
                    ConditionGroup(
                        ConditionMode.ALL,
                        (Condition("source", ConditionOperator.EQUALS, "github"),),
                    ),
                ),
            )
        ),
        EventDispatcher({"automation": AutomationRegistrationEventHandler(FakeRegistrar())}),
    )

    report = asyncio.run(processor.process(event))

    assert report.results[0].status is DispatchStatus.FAILED
    assert report.results[0].error is not None
    assert report.results[0].error.startswith("ValidationError:")


def test_json_decoder_builds_strict_timezone_aware_event_after_authentication() -> None:
    raw_body = json.dumps(
        {
            "eventId": "event-1",
            "eventType": "deployment.completed",
            "subject": "payments",
            "occurredAt": "2030-01-01T00:00:00Z",
            "payload": {"commit": "abc123"},
            "labels": {"environment": "production"},
        }
    ).encode()

    decoded = JsonWebhookEventDecoder().decode("github", raw_body)

    assert decoded.event_id == "event-1"
    assert decoded.source == "github"
    assert decoded.occurred_at == datetime(2030, 1, 1, tzinfo=UTC)
    assert decoded.payload == {"commit": "abc123"}


@pytest.mark.parametrize(
    "raw_body",
    [
        b"not-json",
        b'{"eventId":"missing-fields"}',
        b'{"eventId":"event-1","eventType":"x","subject":"y",'
        b'"occurredAt":"2030-01-01T00:00:00","extra":true}',
    ],
)
def test_json_decoder_rejects_malformed_incomplete_or_ambiguous_events(raw_body: bytes) -> None:
    with pytest.raises(WebhookPayloadError, match="payload is invalid"):
        JsonWebhookEventDecoder().decode("github", raw_body)
