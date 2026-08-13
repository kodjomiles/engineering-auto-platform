"""Reliably deliver a signed outbound webhook."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from engineering_automation.application.ports.webhooks import TransportRequest, WebhookTransport
from engineering_automation.domain.webhook_signing import sign
from engineering_automation.domain.webhooks import (
    AttemptResult,
    DeliveryAttempt,
    DeliveryReport,
    RetryPolicy,
    WebhookMessage,
)

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class DeliverWebhook:
    """Apply signing and retry policy through an abstract transport port."""

    def __init__(
        self,
        transport: WebhookTransport,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.time,
        monotonic: Clock = time.monotonic,
    ) -> None:
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._monotonic = monotonic

    async def dispatch(
        self,
        message: WebhookMessage,
        policy: RetryPolicy | None = None,
    ) -> DeliveryReport:
        active_policy = policy or RetryPolicy()
        attempts: list[DeliveryAttempt] = []

        for attempt_number in range(1, active_policy.max_attempts + 1):
            request = self._build_request(message)
            started_at = self._monotonic()
            try:
                response = await self._transport.send(request)
            except Exception as exc:
                duration_ms = self._duration_ms(started_at)
                has_next = attempt_number < active_policy.max_attempts
                next_delay = active_policy.delay_after(attempt_number) if has_next else None
                attempts.append(
                    DeliveryAttempt(
                        attempt_number,
                        AttemptResult.RETRYABLE_FAILURE,
                        None,
                        f"{type(exc).__name__}: {exc}",
                        duration_ms,
                        next_delay,
                    )
                )
                if next_delay is None:
                    break
                await self._sleep(next_delay)
                continue

            duration_ms = self._duration_ms(started_at)
            if 200 <= response.status_code <= 299:
                attempts.append(
                    DeliveryAttempt(
                        attempt_number,
                        AttemptResult.SUCCEEDED,
                        response.status_code,
                        None,
                        duration_ms,
                        None,
                    )
                )
                break

            retryable = active_policy.is_retryable_status(response.status_code)
            has_next = retryable and attempt_number < active_policy.max_attempts
            next_delay = active_policy.delay_after(attempt_number) if has_next else None
            attempts.append(
                DeliveryAttempt(
                    attempt_number,
                    AttemptResult.RETRYABLE_FAILURE
                    if retryable
                    else AttemptResult.TERMINAL_FAILURE,
                    response.status_code,
                    None,
                    duration_ms,
                    next_delay,
                )
            )
            if next_delay is None:
                break
            await self._sleep(next_delay)

        return DeliveryReport(message.event_id, message.endpoint, tuple(attempts))

    def _build_request(self, message: WebhookMessage) -> TransportRequest:
        timestamp = int(self._clock())
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": message.event_id,
            "User-Agent": "engineering-automation-platform/0.1",
            "X-Automation-Signature": sign(message.secret, timestamp, message.body),
            "X-Automation-Timestamp": str(timestamp),
            **message.headers,
        }
        return TransportRequest(
            message.endpoint,
            message.body,
            tuple(sorted(headers.items())),
            message.timeout_seconds,
        )

    def _duration_ms(self, started_at: float) -> int:
        return max(0, round((self._monotonic() - started_at) * 1000))
