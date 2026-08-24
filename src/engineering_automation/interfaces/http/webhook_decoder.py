"""Decode authenticated webhook JSON into provider-neutral events."""

from __future__ import annotations

from pydantic import ValidationError

from engineering_automation.application.use_cases.ingest_webhook import WebhookPayloadError
from engineering_automation.events import EngineeringEvent
from engineering_automation.interfaces.http.schemas import WebhookEventInput


class JsonWebhookEventDecoder:
    """Validate strict camel-case JSON after signature authentication succeeds."""

    def decode(self, source: str, raw_body: bytes) -> EngineeringEvent:
        try:
            return WebhookEventInput.model_validate_json(raw_body).to_domain(source)
        except (ValidationError, ValueError) as error:
            raise WebhookPayloadError("webhook event payload is invalid") from error
