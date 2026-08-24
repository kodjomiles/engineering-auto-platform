from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from engineering_automation.infrastructure.persistence.memory_webhook_receipts import (
    InMemoryWebhookReceiptStore,
)
from engineering_automation.infrastructure.security.webhook_secrets import (
    StaticWebhookSecretProvider,
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def test_receipt_claim_is_source_scoped_and_can_be_released() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    store = InMemoryWebhookReceiptStore(clock=lambda: now)
    expires = now + timedelta(minutes=5)

    assert asyncio.run(store.claim("GitHub", "delivery-1", expires))
    assert not asyncio.run(store.claim("github", "delivery-1", expires))
    assert asyncio.run(store.claim("gitlab", "delivery-1", expires))
    asyncio.run(store.release(" GITHUB ", "delivery-1"))
    assert asyncio.run(store.claim("github", "delivery-1", expires))


def test_expired_receipt_can_be_claimed_again() -> None:
    clock = MutableClock(datetime(2030, 1, 1, tzinfo=UTC))
    store = InMemoryWebhookReceiptStore(clock=clock)
    first_expiry = clock.value + timedelta(seconds=1)

    assert asyncio.run(store.claim("github", "delivery-1", first_expiry))
    clock.value += timedelta(seconds=2)
    assert asyncio.run(store.claim("github", "delivery-1", clock.value + timedelta(seconds=10)))


def test_receipt_store_rejects_invalid_keys_and_expiry() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    store = InMemoryWebhookReceiptStore(clock=lambda: now)

    with pytest.raises(ValueError, match="source"):
        asyncio.run(store.claim(" ", "delivery-1", now + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="webhook_id"):
        asyncio.run(store.claim("github", " ", now + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(store.claim("github", "delivery-1", datetime(2030, 1, 1)))
    with pytest.raises(ValueError, match="future"):
        asyncio.run(store.claim("github", "delivery-1", now))


def test_static_secret_provider_normalizes_sources_and_hides_unknown_sources() -> None:
    provider = StaticWebhookSecretProvider({" GitHub ": "secret"})

    assert provider.get_secret("github") == b"secret"
    assert provider.get_secret("GITHUB") == b"secret"
    assert provider.get_secret("gitlab") is None


@pytest.mark.parametrize(
    "secrets",
    [
        {},
        {" ": "secret"},
        {"github": ""},
        {"github": "one", " GitHub ": "two"},
    ],
)
def test_static_secret_provider_rejects_ambiguous_configuration(
    secrets: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        StaticWebhookSecretProvider(secrets)
