"""Explicit failures exposed by the n8n integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(eq=False)
class N8nApiError(RuntimeError):
    """An unsuccessful response returned by the n8n public API."""

    status_code: int
    message: str
    request_id: str | None = None
    details: Any = None

    def __str__(self) -> str:
        return f"n8n API returned HTTP {self.status_code}: {self.message}"


class N8nResponseError(RuntimeError):
    """A successful n8n response did not contain its expected fields."""


@dataclass(eq=False)
class N8nWebhookError(RuntimeError):
    """A production webhook failed after its configured delivery attempts."""

    endpoint: str
    attempts: int
    status_code: int | None

    def __str__(self) -> str:
        outcome = f"HTTP {self.status_code}" if self.status_code is not None else "no response"
        return f"n8n webhook failed after {self.attempts} attempt(s): {outcome}"
