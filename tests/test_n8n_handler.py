from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import UTC, datetime

import pytest

from engineering_automation.events import EngineeringEvent, EventDispatcher, RoutePlan
from engineering_automation.n8n import N8nWebhookError, N8nWebhookHandler, N8nWebhookTarget
from engineering_automation.webhooks.delivery import WebhookDispatcher
from engineering_automation.webhooks.models import RetryPolicy
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
        return TransportResponse(outcome)


async def no_wait(_: float) -> None:
    return None


def make_event() -> EngineeringEvent:
    return EngineeringEvent(
        event_id="evt-123",
        source="github",
        event_type="deployment.completed",
        subject="payments-api",
        occurred_at=datetime(2026, 8, 12, 14, tzinfo=UTC),
        payload={"service": {"name": "payments"}, "changes": ["code"]},
        labels={"team": "platform"},
    )


def make_handler(
    transport: FakeTransport,
    *,
    policy: RetryPolicy | None = None,
) -> N8nWebhookHandler:
    target = N8nWebhookTarget(
        "https://automation.example.com/webhook/deploy",
        "workflow-secret",
        headers={"X-Workflow": "deploy"},
        retry_policy=policy or RetryPolicy(),
    )
    return N8nWebhookHandler(
        target,
        WebhookDispatcher(transport, sleep=no_wait, clock=lambda: 1_700_000_000),
    )


def test_handler_sends_complete_signed_event_payload() -> None:
    transport = FakeTransport([202])
    result = asyncio.run(make_handler(transport)(make_event()))
    request = transport.requests[0]
    headers = dict(request.headers)
    payload = json.loads(request.body)

    assert result == {"attempts": 1, "status_code": 202}
    assert payload == {
        "event_id": "evt-123",
        "event_type": "deployment.completed",
        "labels": {"team": "platform"},
        "occurred_at": "2026-08-12T14:00:00+00:00",
        "payload": {"changes": ["code"], "service": {"name": "payments"}},
        "source": "github",
        "subject": "payments-api",
    }
    assert headers["Idempotency-Key"] == "evt-123"
    assert headers["X-Workflow"] == "deploy"
    assert verify(
        b"workflow-secret",
        int(headers["X-Automation-Timestamp"]),
        request.body,
        headers["X-Automation-Signature"],
    )


def test_handler_retries_transient_failure() -> None:
    transport = FakeTransport([503, 200])
    result = asyncio.run(
        make_handler(transport, policy=RetryPolicy(max_attempts=2, initial_delay_seconds=0))(
            make_event()
        )
    )
    assert result == {"attempts": 2, "status_code": 200}
    assert len(transport.requests) == 2


@pytest.mark.parametrize(
    ("outcomes", "status_code"),
    [([422], 422), ([TimeoutError("timed out"), TimeoutError("timed out")], None)],
)
def test_handler_raises_after_terminal_or_exhausted_delivery(
    outcomes: list[int | Exception], status_code: int | None
) -> None:
    transport = FakeTransport(outcomes)
    policy = RetryPolicy(max_attempts=len(outcomes), initial_delay_seconds=0)

    with pytest.raises(N8nWebhookError) as captured:
        asyncio.run(make_handler(transport, policy=policy)(make_event()))

    assert captured.value.attempts == len(outcomes)
    assert captured.value.status_code == status_code


def test_handler_plugs_into_event_dispatcher() -> None:
    transport = FakeTransport([204])
    event = make_event()
    report = asyncio.run(
        EventDispatcher({"n8n.deploy": make_handler(transport)}).dispatch(
            event,
            RoutePlan(event.event_id, ("production-deployments",), ("n8n.deploy",)),
        )
    )
    assert report.succeeded
    assert report.results[0].output == {"attempts": 1, "status_code": 204}
