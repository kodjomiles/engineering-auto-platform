"""Event dispatcher adapter for n8n production webhook workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from engineering_automation.application.ports.webhooks import WebhookDelivery
from engineering_automation.domain.webhooks import WebhookMessage
from engineering_automation.events.models import EngineeringEvent
from engineering_automation.n8n.config import N8nWebhookTarget
from engineering_automation.n8n.errors import N8nWebhookError


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class N8nWebhookHandler:
    """Deliver engineering events to an active n8n Webhook node."""

    def __init__(self, target: N8nWebhookTarget, dispatcher: WebhookDelivery) -> None:
        self._target = target
        self._dispatcher = dispatcher

    async def __call__(self, event: EngineeringEvent) -> Mapping[str, Any]:
        message = WebhookMessage.from_payload(
            event_id=event.event_id,
            endpoint=self._target.endpoint,
            secret=self._target.secret,
            headers=self._target.headers,
            timeout_seconds=self._target.timeout_seconds,
            payload={
                "event_id": event.event_id,
                "source": event.source,
                "event_type": event.event_type,
                "subject": event.subject,
                "occurred_at": event.occurred_at.isoformat(),
                "payload": _json_safe(event.payload),
                "labels": dict(event.labels),
            },
        )
        report = await self._dispatcher.dispatch(message, self._target.retry_policy)
        if not report.succeeded:
            raise N8nWebhookError(
                endpoint=report.endpoint,
                attempts=len(report.attempts),
                status_code=report.final_status_code,
            )
        return {
            "attempts": len(report.attempts),
            "status_code": report.final_status_code,
        }
