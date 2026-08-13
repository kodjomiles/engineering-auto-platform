"""Outbound webhook delivery and transport ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from engineering_automation.domain.webhooks import DeliveryReport, RetryPolicy, WebhookMessage


@dataclass(frozen=True, slots=True)
class TransportRequest:
    """HTTP-agnostic request accepted by a concrete transport."""

    endpoint: str
    body: bytes
    headers: tuple[tuple[str, str], ...]
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class TransportResponse:
    """Minimum response information required by retry orchestration."""

    status_code: int


class WebhookTransport(Protocol):
    """Outbound port implemented by HTTP or queue infrastructure."""

    async def send(self, request: TransportRequest) -> TransportResponse: ...


class WebhookDelivery(Protocol):
    """Inbound port used by interfaces that need reliable delivery."""

    async def dispatch(
        self,
        message: WebhookMessage,
        policy: RetryPolicy | None = None,
    ) -> DeliveryReport: ...
