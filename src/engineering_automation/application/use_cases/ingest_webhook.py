"""Authenticate, deduplicate, and process one inbound engineering webhook."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from engineering_automation.application.ports.inbound_webhooks import (
    EngineeringEventProcessor,
    WebhookEventDecoder,
    WebhookReceiptStore,
    WebhookSecretProvider,
)
from engineering_automation.domain.inbound_webhooks import (
    WebhookIngestionRequest,
    WebhookIngestionResult,
    WebhookIngestionState,
)
from engineering_automation.domain.webhook_signing import verify
from engineering_automation.events.models import DispatchReport

Clock = Callable[[], float]


class WebhookAuthenticationError(Exception):
    """Raised when source, timestamp, or signature authentication fails."""


class WebhookProcessingError(Exception):
    """Raised when an authenticated event cannot complete routed processing."""

    def __init__(self, report: DispatchReport) -> None:
        self.report = report
        super().__init__("one or more routed destinations failed")


class WebhookPayloadError(Exception):
    """Raised when authenticated request bytes do not describe a valid event."""


class IngestWebhook:
    """Coordinate authentication and at-most-once processing within a retention window."""

    def __init__(
        self,
        secrets: WebhookSecretProvider,
        receipts: WebhookReceiptStore,
        decoder: WebhookEventDecoder,
        processor: EngineeringEventProcessor,
        *,
        max_age_seconds: int = 300,
        future_tolerance_seconds: int = 30,
        receipt_ttl_seconds: int = 86400,
        clock: Clock = time.time,
    ) -> None:
        if max_age_seconds < 1:
            raise ValueError("max_age_seconds must be at least 1")
        if future_tolerance_seconds < 0:
            raise ValueError("future_tolerance_seconds cannot be negative")
        if receipt_ttl_seconds < max_age_seconds:
            raise ValueError("receipt_ttl_seconds cannot be less than max_age_seconds")
        self._secrets = secrets
        self._receipts = receipts
        self._decoder = decoder
        self._processor = processor
        self._max_age_seconds = max_age_seconds
        self._future_tolerance_seconds = future_tolerance_seconds
        self._receipt_ttl_seconds = receipt_ttl_seconds
        self._clock = clock

    async def execute(self, request: WebhookIngestionRequest) -> WebhookIngestionResult:
        now = int(self._clock())
        self._authenticate(request, now)
        try:
            event = self._decoder.decode(request.source, request.raw_body)
        except WebhookPayloadError:
            raise
        except Exception as error:
            raise WebhookPayloadError("webhook event payload is invalid") from error
        expires_at = datetime.fromtimestamp(now, tz=UTC) + timedelta(
            seconds=self._receipt_ttl_seconds
        )
        claimed = await self._receipts.claim(
            request.source,
            request.webhook_id,
            expires_at,
        )
        if not claimed:
            return WebhookIngestionResult(
                request.webhook_id,
                event.event_id,
                WebhookIngestionState.DUPLICATE,
            )

        try:
            report = await self._processor.process(event)
            if report.results and not report.succeeded:
                raise WebhookProcessingError(report)
        except BaseException:
            await self._receipts.release(request.source, request.webhook_id)
            raise

        return WebhookIngestionResult(
            request.webhook_id,
            event.event_id,
            WebhookIngestionState.ACCEPTED,
            report,
        )

    def _authenticate(self, request: WebhookIngestionRequest, now: int) -> None:
        age = now - request.timestamp
        if age > self._max_age_seconds or age < -self._future_tolerance_seconds:
            raise WebhookAuthenticationError("webhook timestamp is outside the accepted window")
        secret = self._secrets.get_secret(request.source)
        if secret is None or not verify(
            secret,
            request.timestamp,
            request.raw_body,
            request.signature,
        ):
            raise WebhookAuthenticationError("webhook authentication failed")
