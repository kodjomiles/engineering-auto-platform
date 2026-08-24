"""Durable SQLite receipt storage for inbound webhook idempotency."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

Clock = Callable[[], datetime]


class SqliteWebhookReceiptStore:
    """Atomically claim source-scoped webhook identifiers across processes."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Clock | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not str(database_path).strip():
            raise ValueError("database_path cannot be empty")
        path = Path(database_path)
        if str(path) == ":memory:":
            raise ValueError("database_path must identify a durable SQLite file")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._database_path = path
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout_seconds = timeout_seconds

    async def claim(self, source: str, webhook_id: str, expires_at: datetime) -> bool:
        normalized_source, normalized_id = self._key(source, webhook_id)
        now = self._aware_timestamp(self._clock(), name="clock")
        expiry = self._aware_timestamp(expires_at, name="expires_at")
        if expiry <= now:
            raise ValueError("expires_at must be in the future")
        return await asyncio.to_thread(
            self._claim,
            normalized_source,
            normalized_id,
            now,
            expiry,
        )

    async def release(self, source: str, webhook_id: str) -> None:
        normalized_source, normalized_id = self._key(source, webhook_id)
        await asyncio.to_thread(self._release, normalized_source, normalized_id)

    def _claim(
        self,
        source: str,
        webhook_id: str,
        now: int,
        expires_at: int,
    ) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM webhook_receipts WHERE expires_at <= ?",
                (now,),
            )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO webhook_receipts (source, webhook_id, expires_at)
                VALUES (?, ?, ?)
                """,
                (source, webhook_id, expires_at),
            )
            connection.commit()
            return cursor.rowcount == 1

    def _release(self, source: str, webhook_id: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM webhook_receipts WHERE source = ? AND webhook_id = ?",
                (source, webhook_id),
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self._database_path,
            timeout=self._timeout_seconds,
            isolation_level=None,
        )
        connection.execute(f"PRAGMA busy_timeout = {int(self._timeout_seconds * 1000)}")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_receipts (
                source TEXT NOT NULL,
                webhook_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (source, webhook_id)
            ) WITHOUT ROWID
            """
        )
        return connection

    @staticmethod
    def _aware_timestamp(value: datetime, *, name: str) -> int:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")
        return int(value.timestamp() * 1_000_000)

    @staticmethod
    def _key(source: str, webhook_id: str) -> tuple[str, str]:
        normalized_source = source.strip().lower()
        normalized_id = webhook_id.strip()
        if not normalized_source:
            raise ValueError("source cannot be empty")
        if not normalized_id:
            raise ValueError("webhook_id cannot be empty")
        return normalized_source, normalized_id
