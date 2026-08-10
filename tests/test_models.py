from __future__ import annotations

import pytest

from engineering_automation.webhooks.models import RetryPolicy, WebhookMessage


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(1, 1.0), (2, 2.0), (3, 4.0), (4, 5.0)],
)
def test_retry_delay_grows_and_respects_cap(attempt: int, expected: float) -> None:
    policy = RetryPolicy(max_attempts=5, initial_delay_seconds=1, multiplier=2, max_delay_seconds=5)
    assert policy.delay_after(attempt) == expected


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_attempts": 0}, "max_attempts"),
        ({"initial_delay_seconds": -1}, "initial_delay_seconds"),
        ({"multiplier": 0.5}, "multiplier"),
        ({"max_delay_seconds": -1}, "max_delay_seconds"),
    ],
)
def test_retry_policy_rejects_invalid_values(kwargs: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        RetryPolicy(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("attempt", [0, 3, 4])
def test_delay_rejects_attempts_that_cannot_be_retried(attempt: int) -> None:
    with pytest.raises(ValueError, match="non-final"):
        RetryPolicy(max_attempts=3).delay_after(attempt)


@pytest.mark.parametrize("status", [408, 425, 429, 500, 503, 599])
def test_retryable_statuses(status: int) -> None:
    assert RetryPolicy.is_retryable_status(status)


@pytest.mark.parametrize("status", [200, 301, 400, 401, 404, 422, 600])
def test_terminal_statuses(status: int) -> None:
    assert not RetryPolicy.is_retryable_status(status)


def test_message_encodes_payload_canonically() -> None:
    first = WebhookMessage.from_payload(
        event_id="evt-1",
        endpoint="https://example.com/hooks",
        payload={"b": 2, "a": {"value": "✓"}},
        secret="secret",
    )
    second = WebhookMessage.from_payload(
        event_id="evt-1",
        endpoint="https://example.com/hooks",
        payload={"a": {"value": "✓"}, "b": 2},
        secret="secret",
    )
    assert first.body == second.body == b'{"a":{"value":"\xe2\x9c\x93"},"b":2}'


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("event_id", " ", "event_id"),
        ("endpoint", "example.com/hook", "absolute"),
        ("endpoint", "ftp://example.com/hook", "absolute"),
        ("secret", "", "secret"),
        ("timeout_seconds", 0, "timeout_seconds"),
    ],
)
def test_message_rejects_invalid_contracts(field: str, value: object, message: str) -> None:
    kwargs: dict[str, object] = {
        "event_id": "evt-1",
        "endpoint": "https://example.com/hook",
        "payload": {"ok": True},
        "secret": "secret",
        "timeout_seconds": 5,
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=message):
        WebhookMessage.from_payload(**kwargs)  # type: ignore[arg-type]


def test_headers_are_copied_and_immutable() -> None:
    headers = {"X-Tenant": "alpha"}
    message = WebhookMessage.from_payload(
        event_id="evt-1",
        endpoint="https://example.com/hook",
        payload={},
        secret="secret",
        headers=headers,
    )
    headers["X-Tenant"] = "changed"
    assert message.headers["X-Tenant"] == "alpha"
    with pytest.raises(TypeError):
        message.headers["X-Tenant"] = "blocked"  # type: ignore[index]
