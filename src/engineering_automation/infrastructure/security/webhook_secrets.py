"""Environment-compatible source secret provider."""

from __future__ import annotations

from collections.abc import Mapping


class StaticWebhookSecretProvider:
    """Resolve immutable source-specific secrets with normalized source names."""

    def __init__(self, secrets: Mapping[str, str | bytes]) -> None:
        normalized: dict[str, bytes] = {}
        for source, secret in secrets.items():
            name = str(source).strip().lower()
            value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
            if not name:
                raise ValueError("webhook source cannot be empty")
            if not value:
                raise ValueError(f"webhook secret for {name} cannot be empty")
            if name in normalized:
                raise ValueError("webhook sources must be unique after normalization")
            normalized[name] = value
        if not normalized:
            raise ValueError("at least one webhook source secret is required")
        self._secrets = normalized

    def get_secret(self, source: str) -> bytes | None:
        return self._secrets.get(source.strip().lower())
