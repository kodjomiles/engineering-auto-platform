"""Concurrent in-memory receipt storage for inbound webhook idempotency."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


class InMemoryWebhookReceiptStore:
    """Claim source-scoped webhook identifiers atomically until their expiry."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._receipts: dict[tuple[str, str], datetime] = {}
        self._lock = asyncio.Lock()

    async def claim(self, source: str, webhook_id: str, expires_at: datetime) -> bool:
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        key = self._key(source, webhook_id)
        async with self._lock:
            now = self._clock()
            self._purge(now)
            if key in self._receipts:
                return False
            if expires_at <= now:
                raise ValueError("expires_at must be in the future")
            self._receipts[key] = expires_at
            return True

    async def release(self, source: str, webhook_id: str) -> None:
        async with self._lock:
            self._receipts.pop(self._key(source, webhook_id), None)

    def _purge(self, now: datetime) -> None:
        expired = [key for key, expires_at in self._receipts.items() if expires_at <= now]
        for key in expired:
            del self._receipts[key]

    @staticmethod
    def _key(source: str, webhook_id: str) -> tuple[str, str]:
        normalized_source = source.strip().lower()
        normalized_id = webhook_id.strip()
        if not normalized_source:
            raise ValueError("source cannot be empty")
        if not normalized_id:
            raise ValueError("webhook_id cannot be empty")
        return normalized_source, normalized_id
