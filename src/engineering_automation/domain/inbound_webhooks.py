"""Immutable contracts for authenticated inbound engineering webhooks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from engineering_automation.events.models import DispatchReport


class WebhookIngestionState(StrEnum):
    """Externally visible outcome of an idempotent ingestion attempt."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class WebhookIngestionRequest:
    """Signed request data required by the ingestion use case."""

    webhook_id: str
    timestamp: int
    signature: str
    raw_body: bytes
    source: str

    def __post_init__(self) -> None:
        for name in ("webhook_id", "signature", "source"):
            normalized = getattr(self, name).strip()
            if not normalized:
                raise ValueError(f"{name} cannot be empty")
            if name == "source":
                normalized = normalized.lower()
            object.__setattr__(self, name, normalized)
        if self.timestamp < 0:
            raise ValueError("timestamp cannot be negative")
        if not self.raw_body:
            raise ValueError("raw_body cannot be empty")


@dataclass(frozen=True, slots=True)
class WebhookIngestionResult:
    """Idempotent ingestion result and optional routing audit report."""

    webhook_id: str
    event_id: str
    state: WebhookIngestionState
    dispatch: DispatchReport | None = None

    def __post_init__(self) -> None:
        if not self.webhook_id.strip():
            raise ValueError("webhook_id cannot be empty")
        if not self.event_id.strip():
            raise ValueError("event_id cannot be empty")
        if self.state is WebhookIngestionState.ACCEPTED and self.dispatch is None:
            raise ValueError("accepted ingestion requires a dispatch report")
        if self.state is WebhookIngestionState.DUPLICATE and self.dispatch is not None:
            raise ValueError("duplicate ingestion cannot include a dispatch report")
