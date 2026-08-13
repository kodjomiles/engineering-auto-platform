from __future__ import annotations

import pytest

from engineering_automation.n8n import N8nConfig, N8nWebhookTarget
from engineering_automation.webhooks.models import RetryPolicy


def test_api_config_normalizes_base_url() -> None:
    config = N8nConfig(" https://automation.example.com/ ", "api-key")
    assert config.base_url == "https://automation.example.com"
    assert config.api_base_url == "https://automation.example.com/api/v1"


@pytest.mark.parametrize("base_url", ["", "automation.example.com", "ftp://example.com"])
def test_api_config_rejects_invalid_base_url(base_url: str) -> None:
    with pytest.raises(ValueError, match="absolute HTTP"):
        N8nConfig(base_url, "api-key")


@pytest.mark.parametrize(
    ("api_key", "timeout", "message"),
    [(" ", 15, "api_key"), ("api-key", 0, "timeout_seconds")],
)
def test_api_config_rejects_invalid_credentials_and_timeout(
    api_key: str, timeout: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        N8nConfig("https://automation.example.com", api_key, timeout)


def test_webhook_target_copies_headers_and_policy() -> None:
    headers = {" X-Workflow ": " deploy "}
    policy = RetryPolicy(max_attempts=5)
    target = N8nWebhookTarget(
        "https://automation.example.com/webhook/deploy/",
        "secret",
        headers=headers,
        retry_policy=policy,
    )
    headers[" X-Workflow "] = "changed"

    assert target.endpoint == "https://automation.example.com/webhook/deploy"
    assert target.headers == {"X-Workflow": "deploy"}
    assert target.retry_policy is policy
    with pytest.raises(TypeError):
        target.headers["new"] = "blocked"  # type: ignore[index]


@pytest.mark.parametrize(
    ("endpoint", "secret", "timeout", "message"),
    [
        ("webhook/path", "secret", 10, "absolute HTTP"),
        ("https://example.com/hook", "", 10, "secret"),
        ("https://example.com/hook", "secret", -1, "timeout_seconds"),
    ],
)
def test_webhook_target_rejects_invalid_values(
    endpoint: str, secret: str, timeout: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        N8nWebhookTarget(endpoint, secret, timeout_seconds=timeout)
