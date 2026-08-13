from __future__ import annotations

import asyncio

import pytest

from engineering_automation.notifications import InMemoryDeduplicationStore


class MutableClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_store_rejects_invalid_claims() -> None:
    store = InMemoryDeduplicationStore()
    with pytest.raises(ValueError, match="key"):
        asyncio.run(store.claim(" ", 10))
    with pytest.raises(ValueError, match="ttl_seconds"):
        asyncio.run(store.claim("alert", -1))


def test_claim_is_rejected_until_window_expires() -> None:
    clock = MutableClock()
    store = InMemoryDeduplicationStore(clock=clock)

    async def exercise() -> tuple[bool, bool, bool]:
        first = await store.claim("deploy:production", 30)
        second = await store.claim("deploy:production", 30)
        clock.value = 130
        third = await store.claim("deploy:production", 30)
        return first, second, third

    assert asyncio.run(exercise()) == (True, False, True)


def test_zero_length_window_allows_immediate_reclaim() -> None:
    store = InMemoryDeduplicationStore(clock=lambda: 100)

    async def exercise() -> tuple[bool, bool]:
        return await store.claim("alert", 0), await store.claim("alert", 0)

    assert asyncio.run(exercise()) == (True, True)


def test_concurrent_claims_have_exactly_one_winner() -> None:
    store = InMemoryDeduplicationStore(clock=lambda: 100)

    async def exercise() -> list[bool]:
        return list(await asyncio.gather(*(store.claim("same", 30) for _ in range(20))))

    results = asyncio.run(exercise())
    assert results.count(True) == 1
    assert results.count(False) == 19
