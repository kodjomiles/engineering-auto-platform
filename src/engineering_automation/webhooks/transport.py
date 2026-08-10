"""Transport boundary for outbound HTTP requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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
    """Implemented later by httpx, queue, or test transports."""

    async def send(self, request: TransportRequest) -> TransportResponse:
        """Send one request or raise an exception when no response is received."""
        ...
