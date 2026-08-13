"""Process-local implementation of the deduplication port."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

Clock = Callable[[], float]


class InMemoryDeduplicationStore:
    """Atomically retain deduplication keys until their time window expires."""

    def __init__(self, *, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._expirations: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def claim(self, key: str, ttl_seconds: float) -> bool:
        normalized = key.strip()
        if not normalized:
            raise ValueError("deduplication key cannot be empty")
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds cannot be negative")

        async with self._lock:
            now = self._clock()
            self._expirations = {
                stored_key: expires_at
                for stored_key, expires_at in self._expirations.items()
                if expires_at > now
            }
            if normalized in self._expirations:
                return False
            self._expirations[normalized] = now + ttl_seconds
            return True
