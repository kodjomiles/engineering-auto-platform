"""Domain contracts for outbound webhook delivery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit


class AttemptResult(StrEnum):
    """Observable result of one delivery attempt."""

    SUCCEEDED = "succeeded"
    RETRYABLE_FAILURE = "retryable_failure"
    TERMINAL_FAILURE = "terminal_failure"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential retry policy.

    ``max_attempts`` includes the first request. Delays are applied only after
    unsuccessful attempts for which another attempt remains.
    """

    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    multiplier: float = 2.0
    max_delay_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds cannot be negative")
        if self.multiplier < 1:
            raise ValueError("multiplier must be at least 1")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds cannot be negative")

    def delay_after(self, attempt_number: int) -> float:
        """Return the delay after a failed, non-final attempt."""

        if not 1 <= attempt_number < self.max_attempts:
            raise ValueError("attempt_number must identify a non-final attempt")
        unbounded = self.initial_delay_seconds * self.multiplier ** (attempt_number - 1)
        return min(unbounded, self.max_delay_seconds)

    @staticmethod
    def is_retryable_status(status_code: int) -> bool:
        """Return whether an HTTP response should be attempted again."""

        return status_code in {408, 425, 429} or 500 <= status_code <= 599


@dataclass(frozen=True, slots=True)
class WebhookMessage:
    """A fully encoded webhook message ready for delivery."""

    event_id: str
    endpoint: str
    body: bytes
    secret: bytes = field(repr=False)
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id cannot be empty")
        parsed = urlsplit(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint must be an absolute HTTP or HTTPS URL")
        if not self.secret:
            raise ValueError("secret cannot be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        normalized_headers = {
            str(name).strip(): str(value).strip()
            for name, value in self.headers.items()
            if str(name).strip()
        }
        object.__setattr__(self, "headers", MappingProxyType(normalized_headers))

    @classmethod
    def from_payload(
        cls,
        *,
        event_id: str,
        endpoint: str,
        payload: Mapping[str, Any],
        secret: str,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 10.0,
    ) -> WebhookMessage:
        """Create a message using deterministic JSON encoding."""

        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return cls(
            event_id=event_id,
            endpoint=endpoint,
            body=body,
            secret=secret.encode("utf-8"),
            headers=headers or {},
            timeout_seconds=timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """Audit record for one transport invocation."""

    attempt_number: int
    result: AttemptResult
    status_code: int | None
    error: str | None
    duration_ms: int
    next_delay_seconds: float | None


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    """Final immutable result of dispatching one webhook message."""

    event_id: str
    endpoint: str
    attempts: tuple[DeliveryAttempt, ...]

    @property
    def succeeded(self) -> bool:
        return bool(self.attempts) and self.attempts[-1].result is AttemptResult.SUCCEEDED

    @property
    def final_status_code(self) -> int | None:
        return self.attempts[-1].status_code if self.attempts else None
