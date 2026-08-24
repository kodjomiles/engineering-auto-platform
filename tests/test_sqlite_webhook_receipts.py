from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from engineering_automation.infrastructure.persistence.sqlite_webhook_receipts import (
    SqliteWebhookReceiptStore,
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def test_receipt_claim_survives_store_recreation(tmp_path: Path) -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    database = tmp_path / "state" / "receipts.sqlite3"
    expires_at = now + timedelta(minutes=5)

    first = SqliteWebhookReceiptStore(database, clock=lambda: now)
    second = SqliteWebhookReceiptStore(database, clock=lambda: now)

    assert asyncio.run(first.claim(" GitHub ", "delivery-1", expires_at))
    assert not asyncio.run(second.claim("github", "delivery-1", expires_at))
    assert asyncio.run(second.claim("gitlab", "delivery-1", expires_at))
    assert database.is_file()


def test_concurrent_store_instances_allow_exactly_one_claim(tmp_path: Path) -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    expires_at = now + timedelta(minutes=5)
    stores = [
        SqliteWebhookReceiptStore(tmp_path / "receipts.sqlite3", clock=lambda: now)
        for _ in range(12)
    ]

    async def claim_from_every_store() -> list[bool]:
        return await asyncio.gather(
            *(store.claim("github", "delivery-1", expires_at) for store in stores)
        )

    results = asyncio.run(claim_from_every_store())

    assert results.count(True) == 1
    assert results.count(False) == 11


def test_release_and_expiry_make_receipts_claimable_again(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2030, 1, 1, tzinfo=UTC))
    store = SqliteWebhookReceiptStore(tmp_path / "receipts.sqlite3", clock=clock)

    assert asyncio.run(store.claim("github", "released", clock.value + timedelta(minutes=1)))
    asyncio.run(store.release(" GITHUB ", "released"))
    assert asyncio.run(store.claim("github", "released", clock.value + timedelta(minutes=1)))

    assert asyncio.run(store.claim("github", "expired", clock.value + timedelta(seconds=1)))
    clock.value += timedelta(seconds=1)
    assert asyncio.run(store.claim("github", "expired", clock.value + timedelta(minutes=1)))


@pytest.mark.parametrize(
    ("source", "webhook_id", "expires_at", "message"),
    [
        (" ", "delivery-1", datetime(2030, 1, 2, tzinfo=UTC), "source"),
        ("github", " ", datetime(2030, 1, 2, tzinfo=UTC), "webhook_id"),
        ("github", "delivery-1", datetime(2030, 1, 2), "timezone-aware"),
        ("github", "delivery-1", datetime(2030, 1, 1, tzinfo=UTC), "future"),
    ],
)
def test_receipt_store_rejects_invalid_claims(
    tmp_path: Path,
    source: str,
    webhook_id: str,
    expires_at: datetime,
    message: str,
) -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    store = SqliteWebhookReceiptStore(tmp_path / "receipts.sqlite3", clock=lambda: now)

    with pytest.raises(ValueError, match=message):
        asyncio.run(store.claim(source, webhook_id, expires_at))


@pytest.mark.parametrize("database_path", ["", ":memory:"])
def test_receipt_store_requires_a_durable_database_path(database_path: str) -> None:
    with pytest.raises(ValueError, match="database_path"):
        SqliteWebhookReceiptStore(database_path)


def test_receipt_store_rejects_naive_clock(tmp_path: Path) -> None:
    store = SqliteWebhookReceiptStore(
        tmp_path / "receipts.sqlite3",
        clock=lambda: datetime(2030, 1, 1),
    )

    with pytest.raises(ValueError, match="clock must be timezone-aware"):
        asyncio.run(
            store.claim(
                "github",
                "delivery-1",
                datetime(2030, 1, 2, tzinfo=UTC),
            )
        )
