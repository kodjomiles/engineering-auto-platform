"""Compatibility exports for webhook transport ports."""

from engineering_automation.application.ports.webhooks import (
    TransportRequest,
    TransportResponse,
    WebhookTransport,
)

__all__ = ["TransportRequest", "TransportResponse", "WebhookTransport"]
