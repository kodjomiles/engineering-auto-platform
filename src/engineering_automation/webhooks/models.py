"""Compatibility exports for webhook domain entities."""

from engineering_automation.domain.webhooks import (
    AttemptResult,
    DeliveryAttempt,
    DeliveryReport,
    RetryPolicy,
    WebhookMessage,
)

__all__ = [
    "AttemptResult",
    "DeliveryAttempt",
    "DeliveryReport",
    "RetryPolicy",
    "WebhookMessage",
]
