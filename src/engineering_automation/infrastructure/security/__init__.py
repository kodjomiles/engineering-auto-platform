"""Security adapters for application authentication ports."""

from engineering_automation.infrastructure.security.webhook_secrets import (
    StaticWebhookSecretProvider,
)

__all__ = ["StaticWebhookSecretProvider"]
