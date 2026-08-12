"""Concurrent, failure-isolated delivery of routed events."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from engineering_automation.events.models import (
    DestinationResult,
    DispatchReport,
    DispatchStatus,
    EngineeringEvent,
    RoutePlan,
)

Clock = Callable[[], float]


EventHandler = Callable[[EngineeringEvent], Awaitable[Mapping[str, Any] | None]]


class EventDispatcher:
    """Invoke routed handlers concurrently while preserving route order."""

    def __init__(
        self,
        handlers: Mapping[str, EventHandler],
        *,
        max_concurrency: int = 10,
        monotonic: Clock = time.monotonic,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        normalized: dict[str, EventHandler] = {}
        for name, handler in handlers.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("handler names cannot be empty")
            if normalized_name in normalized:
                raise ValueError("handler names must be unique after normalization")
            normalized[normalized_name] = handler
        self._handlers = normalized
        self._max_concurrency = max_concurrency
        self._monotonic = monotonic

    async def dispatch(self, event: EngineeringEvent, plan: RoutePlan) -> DispatchReport:
        if plan.event_id != event.event_id:
            raise ValueError("route plan belongs to a different event")

        semaphore = asyncio.Semaphore(self._max_concurrency)
        tasks = [self._invoke(destination, event, semaphore) for destination in plan.destinations]
        results = tuple(await asyncio.gather(*tasks))
        return DispatchReport(
            event_id=event.event_id,
            matched_rule_ids=plan.matched_rule_ids,
            results=results,
        )

    async def _invoke(
        self,
        destination: str,
        event: EngineeringEvent,
        semaphore: asyncio.Semaphore,
    ) -> DestinationResult:
        handler = self._handlers.get(destination)
        if handler is None:
            return DestinationResult(
                destination=destination,
                status=DispatchStatus.MISSING_HANDLER,
                duration_ms=0,
                error=f"no handler registered for {destination}",
            )

        async with semaphore:
            started_at = self._monotonic()
            try:
                output = await handler(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return DestinationResult(
                    destination=destination,
                    status=DispatchStatus.FAILED,
                    duration_ms=self._duration_ms(started_at),
                    error=f"{type(exc).__name__}: {exc}",
                )
            return DestinationResult(
                destination=destination,
                status=DispatchStatus.SUCCEEDED,
                duration_ms=self._duration_ms(started_at),
                output=dict(output) if output is not None else None,
            )

    def _duration_ms(self, started_at: float) -> int:
        return max(0, round((self._monotonic() - started_at) * 1000))
