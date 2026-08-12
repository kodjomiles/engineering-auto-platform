"""Validated configuration for n8n API and webhook access."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from urllib.parse import urlsplit

from engineering_automation.webhooks.models import RetryPolicy


def _absolute_url(name: str, value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute HTTP or HTTPS URL")
    return normalized


@dataclass(frozen=True, slots=True)
class N8nConfig:
    """Connection settings for one n8n public API instance."""

    base_url: str
    api_key: str = field(repr=False)
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _absolute_url("base_url", self.base_url))
        if not self.api_key.strip():
            raise ValueError("api_key cannot be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

    @property
    def api_base_url(self) -> str:
        return f"{self.base_url}/api/v1"


@dataclass(frozen=True, slots=True)
class N8nWebhookTarget:
    """Production webhook endpoint and delivery behavior for one workflow."""

    endpoint: str
    secret: str = field(repr=False)
    timeout_seconds: float = 10.0
    headers: Mapping[str, str] = field(default_factory=dict)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", _absolute_url("endpoint", self.endpoint))
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
