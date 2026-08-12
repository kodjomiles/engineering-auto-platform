"""Explicit failure types exposed by the Port client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(eq=False)
class PortApiError(RuntimeError):
    """An unsuccessful response returned by Port."""

    status_code: int
    message: str
    error_code: str | None = None
    request_id: str | None = None
    details: Any = None

    def __str__(self) -> str:
        prefix = f"Port API returned HTTP {self.status_code}"
        if self.error_code:
            prefix += f" ({self.error_code})"
        return f"{prefix}: {self.message}"


class PortResponseError(RuntimeError):
    """A successful Port response did not contain its documented fields."""
