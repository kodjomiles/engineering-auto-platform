from __future__ import annotations

import asyncio
from collections.abc import Iterable

from engineering_automation.webhooks.delivery import WebhookDispatcher
from engineering_automation.webhooks.models import AttemptResult, RetryPolicy, WebhookMessage
from engineering_automation.webhooks.signing import verify
from engineering_automation.webhooks.transport import TransportRequest, TransportResponse


class FakeTransport:
    def __init__(self, outcomes: Iterable[int | Exception]) -> None:
        self._outcomes = iter(outcomes)
        self.requests: list[TransportRequest] = []

    async def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        outcome = next(self._outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return TransportResponse(status_code=outcome)


class SequenceClock:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def make_message() -> WebhookMessage:
    return WebhookMessage.from_payload(
        event_id="evt-123",
        endpoint="https://automation.example.com/webhooks/port",
        payload={"entity": {"identifier": "service-a"}},
        secret="top-secret",
        headers={"X-Tenant": "team-a"},
        timeout_seconds=7,
    )


def test_successful_delivery_stops_after_one_attempt() -> None:
    transport = FakeTransport([202])
    report = asyncio.run(
        WebhookDispatcher(
            transport,
            clock=lambda: 1_700_000_000,
            monotonic=SequenceClock([10.0, 10.025]),
        ).dispatch(make_message())
    )
    assert report.succeeded
    assert report.final_status_code == 202
    assert len(report.attempts) == len(transport.requests) == 1
    assert report.attempts[0].duration_ms == 25


def test_retryable_response_is_retried_then_succeeds() -> None:
    transport = FakeTransport([503, 200])
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    report = asyncio.run(
        WebhookDispatcher(
            transport,
            sleep=record_sleep,
            clock=lambda: 1_700_000_000,
            monotonic=SequenceClock([1.0, 1.01, 2.0, 2.02]),
        ).dispatch(make_message(), RetryPolicy(initial_delay_seconds=2))
    )
    assert report.succeeded
    assert delays == [2]
    assert [attempt.result for attempt in report.attempts] == [
        AttemptResult.RETRYABLE_FAILURE,
        AttemptResult.SUCCEEDED,
    ]


def test_terminal_response_is_not_retried() -> None:
    transport = FakeTransport([422])
    report = asyncio.run(
        WebhookDispatcher(
            transport,
            clock=lambda: 1_700_000_000,
            monotonic=SequenceClock([1.0, 1.0]),
        ).dispatch(make_message(), RetryPolicy(max_attempts=5))
    )
    assert not report.succeeded
    assert report.attempts[0].result is AttemptResult.TERMINAL_FAILURE
    assert len(transport.requests) == 1


def test_transport_exception_is_recorded_and_retried() -> None:
    transport = FakeTransport([TimeoutError("upstream timed out"), 204])

    async def no_wait(_: float) -> None:
        return None

    report = asyncio.run(
        WebhookDispatcher(
            transport,
            sleep=no_wait,
            clock=lambda: 1_700_000_000,
            monotonic=SequenceClock([1.0, 1.1, 2.0, 2.0]),
        ).dispatch(make_message())
    )
    assert report.succeeded
    assert report.attempts[0].status_code is None
    assert report.attempts[0].error == "TimeoutError: upstream timed out"


def test_retry_exhaustion_returns_failed_report() -> None:
    transport = FakeTransport([500, 502, 503])
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    report = asyncio.run(
        WebhookDispatcher(
            transport,
            sleep=record_sleep,
            clock=lambda: 1_700_000_000,
            monotonic=SequenceClock([1, 1, 2, 2, 3, 3]),
        ).dispatch(
            make_message(),
            RetryPolicy(max_attempts=3, initial_delay_seconds=1, multiplier=3),
        )
    )
    assert not report.succeeded
    assert report.final_status_code == 503
    assert delays == [1, 3]
    assert report.attempts[-1].next_delay_seconds is None


def test_request_contains_signed_delivery_headers() -> None:
    transport = FakeTransport([200])
    message = make_message()
    asyncio.run(
        WebhookDispatcher(
            transport,
            clock=lambda: 1_700_000_000,
            monotonic=SequenceClock([1, 1]),
        ).dispatch(message)
    )
    request = transport.requests[0]
    headers = dict(request.headers)
    assert request.endpoint == message.endpoint
    assert request.body == message.body
    assert request.timeout_seconds == 7
    assert headers["Content-Type"] == "application/json"
    assert headers["Idempotency-Key"] == "evt-123"
    assert headers["X-Tenant"] == "team-a"
    assert verify(
        message.secret,
        int(headers["X-Automation-Timestamp"]),
        request.body,
        headers["X-Automation-Signature"],
    )


def test_custom_headers_can_override_defaults_deliberately() -> None:
    message = WebhookMessage.from_payload(
        event_id="evt-1",
        endpoint="https://example.com/hook",
        payload={},
        secret="secret",
        headers={"User-Agent": "custom-agent"},
    )
    transport = FakeTransport([200])
    asyncio.run(
        WebhookDispatcher(
            transport,
            clock=lambda: 1,
            monotonic=SequenceClock([1, 1]),
        ).dispatch(message)
    )
    assert dict(transport.requests[0].headers)["User-Agent"] == "custom-agent"
