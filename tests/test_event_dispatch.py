from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from engineering_automation.events import (
    DispatchStatus,
    EngineeringEvent,
    EventDispatcher,
    RoutePlan,
)


class SequenceClock:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def make_event() -> EngineeringEvent:
    return EngineeringEvent(
        event_id="evt-123",
        source="github",
        event_type="deployment.completed",
        subject="payments-api",
        occurred_at=datetime(2026, 8, 12, tzinfo=UTC),
    )


def make_plan(*destinations: str) -> RoutePlan:
    return RoutePlan("evt-123", ("route-deployments",), destinations)


def test_dispatch_delivers_to_each_destination_in_route_order() -> None:
    calls: list[str] = []

    def handler(name: str) -> Any:
        async def invoke(event: EngineeringEvent) -> Mapping[str, Any]:
            calls.append(f"{name}:{event.event_id}")
            return {"destination": name}

        return invoke

    report = asyncio.run(
        EventDispatcher(
            {"port": handler("port"), "n8n": handler("n8n")},
            monotonic=SequenceClock((1.0, 1.01, 2.0, 2.02)),
        ).dispatch(make_event(), make_plan("port", "n8n"))
    )

    assert report.succeeded
    assert [result.destination for result in report.results] == ["port", "n8n"]
    assert [result.duration_ms for result in report.results] == [10, 20]
    assert set(calls) == {"port:evt-123", "n8n:evt-123"}


def test_dispatch_isolates_handler_failure() -> None:
    async def fail(_: EngineeringEvent) -> None:
        raise RuntimeError("provider unavailable")

    async def succeed(_: EngineeringEvent) -> Mapping[str, Any]:
        return {"accepted": True}

    report = asyncio.run(
        EventDispatcher(
            {"port": fail, "n8n": succeed},
            monotonic=SequenceClock((1.0, 1.01, 2.0, 2.01)),
        ).dispatch(make_event(), make_plan("port", "n8n"))
    )

    assert not report.succeeded
    assert report.results[0].status is DispatchStatus.FAILED
    assert report.results[0].error == "RuntimeError: provider unavailable"
    assert report.results[1].status is DispatchStatus.SUCCEEDED


def test_dispatch_records_missing_handler_without_blocking_registered_handlers() -> None:
    async def succeed(_: EngineeringEvent) -> None:
        return None

    report = asyncio.run(
        EventDispatcher(
            {"port": succeed},
            monotonic=SequenceClock((1.0, 1.0)),
        ).dispatch(make_event(), make_plan("unknown", "port"))
    )

    assert report.results[0].status is DispatchStatus.MISSING_HANDLER
    assert report.results[0].duration_ms == 0
    assert report.results[1].status is DispatchStatus.SUCCEEDED


def test_dispatch_respects_concurrency_limit() -> None:
    async def run() -> int:
        active = 0
        peak = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def gated(_: EngineeringEvent) -> None:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if peak == 2:
                started.set()
            await release.wait()
            active -= 1

        dispatcher = EventDispatcher(
            {name: gated for name in ("one", "two", "three", "four")},
            max_concurrency=2,
        )
        task = asyncio.create_task(
            dispatcher.dispatch(make_event(), make_plan("one", "two", "three", "four"))
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        assert active == 2
        release.set()
        report = await task
        assert report.succeeded
        return peak

    assert asyncio.run(run()) == 2


def test_dispatch_rejects_plan_for_different_event() -> None:
    with pytest.raises(ValueError, match="different event"):
        asyncio.run(EventDispatcher({}).dispatch(make_event(), RoutePlan("other", (), ())))


@pytest.mark.parametrize("max_concurrency", [0, -1])
def test_dispatcher_rejects_invalid_concurrency(max_concurrency: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        EventDispatcher({}, max_concurrency=max_concurrency)


def test_dispatcher_rejects_blank_or_colliding_normalized_names() -> None:
    async def handler(_: EngineeringEvent) -> None:
        return None

    with pytest.raises(ValueError, match="cannot be empty"):
        EventDispatcher({" ": handler})
    with pytest.raises(ValueError, match="unique"):
        EventDispatcher({"port": handler, " port ": handler})


def test_empty_route_returns_unsuccessful_empty_report() -> None:
    report = asyncio.run(EventDispatcher({}).dispatch(make_event(), make_plan()))
    assert report.event_id == "evt-123"
    assert report.matched_rule_ids == ("route-deployments",)
    assert report.results == ()
    assert not report.succeeded
