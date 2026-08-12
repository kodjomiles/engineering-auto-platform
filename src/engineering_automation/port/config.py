"""Configuration contracts for Port API access."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit


class PortRegion(StrEnum):
    """Port API regions supported by the client."""

    EU = "eu"
    US = "us"

    @property
    def base_url(self) -> str:
        if self is PortRegion.US:
            return "https://api.us.port.io"
        return "https://api.port.io"


@dataclass(frozen=True, slots=True)
class PortConfig:
    """Credentials and request behavior for one Port organization."""

    client_id: str
    client_secret: str
    region: PortRegion = PortRegion.EU
    base_url: str | None = None
    timeout_seconds: float = 15.0
    token_refresh_skew_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise ValueError("client_id cannot be empty")
        if not self.client_secret.strip():
            raise ValueError("client_secret cannot be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if self.token_refresh_skew_seconds < 0:
            raise ValueError("token_refresh_skew_seconds cannot be negative")
        if self.base_url is not None:
            normalized = self.base_url.strip().rstrip("/")
            parsed = urlsplit(normalized)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("base_url must be an absolute HTTP or HTTPS URL")
            object.__setattr__(self, "base_url", normalized)

    @property
    def api_base_url(self) -> str:
        return self.base_url or self.region.base_url
