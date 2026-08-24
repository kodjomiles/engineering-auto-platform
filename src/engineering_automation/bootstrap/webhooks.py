"""Inbound webhook composition root."""

from __future__ import annotations

from collections.abc import Mapping

from engineering_automation.application.ports.automation import AutomationRegistrar
from engineering_automation.application.ports.inbound_webhooks import WebhookReceiptStore
from engineering_automation.application.use_cases.ingest_webhook import IngestWebhook
from engineering_automation.events import (
    Condition,
    ConditionGroup,
    ConditionMode,
    ConditionOperator,
    EventDispatcher,
    EventRouter,
    RoutingRule,
)
from engineering_automation.infrastructure.persistence.memory_webhook_receipts import (
    InMemoryWebhookReceiptStore,
)
from engineering_automation.infrastructure.security.webhook_secrets import (
    StaticWebhookSecretProvider,
)
from engineering_automation.interfaces.event_handlers.automations import (
    AutomationRegistrationEventHandler,
)
from engineering_automation.interfaces.event_handlers.routing import RoutingEventProcessor
from engineering_automation.interfaces.http.webhook_decoder import JsonWebhookEventDecoder

AUTOMATION_REGISTRATION_EVENT = "automation.registration.requested"
AUTOMATION_REGISTRATION_DESTINATION = "automation.register"


def build_webhook_ingestor(
    registrar: AutomationRegistrar,
    secrets: Mapping[str, str],
    *,
    max_age_seconds: int = 300,
    future_tolerance_seconds: int = 30,
    receipt_ttl_seconds: int = 86400,
    receipt_store: WebhookReceiptStore | None = None,
) -> IngestWebhook:
    """Wire secure ingestion to the platform's first production event route."""

    event_type_matches = ConditionGroup(
        ConditionMode.ALL,
        (
            Condition(
                "event_type",
                ConditionOperator.EQUALS,
                AUTOMATION_REGISTRATION_EVENT,
            ),
        ),
    )
    router = EventRouter(
        (
            RoutingRule(
                "register-requested-automation",
                (AUTOMATION_REGISTRATION_DESTINATION,),
                event_type_matches,
                priority=100,
            ),
        )
    )
    dispatcher = EventDispatcher(
        {AUTOMATION_REGISTRATION_DESTINATION: AutomationRegistrationEventHandler(registrar)}
    )
    return IngestWebhook(
        StaticWebhookSecretProvider(secrets),
        receipt_store if receipt_store is not None else InMemoryWebhookReceiptStore(),
        JsonWebhookEventDecoder(),
        RoutingEventProcessor(router, dispatcher),
        max_age_seconds=max_age_seconds,
        future_tolerance_seconds=future_tolerance_seconds,
        receipt_ttl_seconds=receipt_ttl_seconds,
    )
