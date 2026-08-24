"""Application boundaries for inbound webhook authentication and processing."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from engineering_automation.domain.inbound_webhooks import (
    WebhookIngestionRequest,
    WebhookIngestionResult,
)
from engineering_automation.events.models import DispatchReport, EngineeringEvent


class WebhookSecretProvider(Protocol):
    """Resolve source-specific signing secrets without exposing storage details."""

    def get_secret(self, source: str) -> bytes | None: ...


class WebhookReceiptStore(Protocol):
    """Atomically claim webhook identifiers for an idempotency window."""

    async def claim(self, source: str, webhook_id: str, expires_at: datetime) -> bool: ...

    async def release(self, source: str, webhook_id: str) -> None: ...


class EngineeringEventProcessor(Protocol):
    """Process one authenticated provider-neutral engineering event."""

    async def process(self, event: EngineeringEvent) -> DispatchReport: ...


class WebhookEventDecoder(Protocol):
    """Decode authenticated bytes into one provider-neutral event."""

    def decode(self, source: str, raw_body: bytes) -> EngineeringEvent: ...


class WebhookIngestor(Protocol):
    """Inbound port exposed by HTTP or queue interfaces."""

    async def execute(self, request: WebhookIngestionRequest) -> WebhookIngestionResult: ...
