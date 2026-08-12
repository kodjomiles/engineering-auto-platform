"""Concrete async HTTP transport for outbound webhooks."""

from __future__ import annotations

import httpx

from engineering_automation.webhooks.transport import TransportRequest, TransportResponse


class HttpxWebhookTransport:
    """Send webhook requests through a reusable ``httpx.AsyncClient``."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._closed = False

    async def send(self, request: TransportRequest) -> TransportResponse:
        if self._closed:
            raise RuntimeError("transport is closed")
        response = await self._client.post(
            request.endpoint,
            content=request.body,
            headers=dict(request.headers),
            timeout=request.timeout_seconds,
        )
        return TransportResponse(status_code=response.status_code)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> HttpxWebhookTransport:
        if self._closed:
            raise RuntimeError("transport is closed")
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        await self.aclose()
