"""Persistence adapters implementing application ports."""

from engineering_automation.infrastructure.persistence.memory_webhook_receipts import (
    InMemoryWebhookReceiptStore,
)

__all__ = ["InMemoryWebhookReceiptStore"]
