from __future__ import annotations

import asyncio

import httpx
import pytest

from engineering_automation.webhooks.httpx_transport import HttpxWebhookTransport
from engineering_automation.webhooks.transport import TransportRequest


def test_httpx_transport_forwards_request_contract() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(202)

    async def exercise() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            transport = HttpxWebhookTransport(client)
            response = await transport.send(
                TransportRequest(
                    endpoint="https://hooks.example.com/events",
                    body=b'{"ok":true}',
                    headers=(("Content-Type", "application/json"), ("X-Event", "created")),
                    timeout_seconds=4.5,
                )
            )
            return response.status_code

    assert asyncio.run(exercise()) == 202
    assert captured[0].url == "https://hooks.example.com/events"
    assert captured[0].content == b'{"ok":true}'
    assert captured[0].headers["X-Event"] == "created"


def test_httpx_transport_propagates_network_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            transport = HttpxWebhookTransport(client)
            await transport.send(TransportRequest("https://example.com", b"{}", (), 1.0))

    with pytest.raises(httpx.ConnectError, match="offline"):
        asyncio.run(exercise())


def test_closed_transport_rejects_new_requests() -> None:
    async def exercise() -> None:
        transport = HttpxWebhookTransport()
        await transport.aclose()
        await transport.send(TransportRequest("https://example.com", b"{}", (), 1.0))

    with pytest.raises(RuntimeError, match="closed"):
        asyncio.run(exercise())
