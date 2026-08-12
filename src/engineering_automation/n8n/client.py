"""Async client for a focused subset of the n8n public API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx

from engineering_automation.n8n.config import N8nConfig
from engineering_automation.n8n.errors import N8nApiError, N8nResponseError
from engineering_automation.n8n.models import Execution, Workflow, WorkflowPage


class N8nClient:
    """Manage workflows and inspect executions using n8n API keys."""

    def __init__(self, config: N8nConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.api_base_url,
            timeout=config.timeout_seconds,
            headers={"Accept": "application/json"},
        )
        self._owns_client = client is None
        self._closed = False

    async def get_workflow(self, workflow_id: str) -> Workflow:
        response = await self._request("GET", f"/workflows/{self._identifier(workflow_id)}")
        return Workflow.from_payload(self._json_object(response))

    async def list_workflows_page(
        self,
        *,
        active: bool | None = None,
        tags: Sequence[str] = (),
        limit: int = 100,
        cursor: str | None = None,
    ) -> WorkflowPage:
        if not 1 <= limit <= 250:
            raise ValueError("limit must be between 1 and 250")
        params: dict[str, str] = {"limit": str(limit)}
        if active is not None:
            params["active"] = "true" if active else "false"
        normalized_tags = [tag.strip() for tag in tags if tag.strip()]
        if normalized_tags:
            params["tags"] = ",".join(normalized_tags)
        if cursor:
            params["cursor"] = cursor

        response = await self._request("GET", "/workflows", params=params)
        body = self._json_object(response)
        raw_workflows = body.get("data")
        if not isinstance(raw_workflows, list) or not all(
            isinstance(workflow, dict) for workflow in raw_workflows
        ):
            raise N8nResponseError("n8n workflows response is missing a data array")
        next_cursor = body.get("nextCursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise N8nResponseError("n8n workflows response has an invalid nextCursor")
        return WorkflowPage(
            workflows=tuple(Workflow.from_payload(workflow) for workflow in raw_workflows),
            next_cursor=next_cursor,
        )

    async def iter_workflows(
        self,
        *,
        active: bool | None = None,
        tags: Sequence[str] = (),
        page_size: int = 100,
    ) -> AsyncIterator[Workflow]:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            page = await self.list_workflows_page(
                active=active,
                tags=tags,
                limit=page_size,
                cursor=cursor,
            )
            for workflow in page.workflows:
                yield workflow
            if page.next_cursor is None:
                return
            if page.next_cursor in seen_cursors:
                raise N8nResponseError("n8n workflows response repeated a pagination cursor")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor

    async def activate_workflow(self, workflow_id: str) -> Workflow:
        return await self._change_activation(workflow_id, "activate")

    async def deactivate_workflow(self, workflow_id: str) -> Workflow:
        return await self._change_activation(workflow_id, "deactivate")

    async def get_execution(self, execution_id: str, *, include_data: bool = False) -> Execution:
        response = await self._request(
            "GET",
            f"/executions/{self._identifier(execution_id)}",
            params={"includeData": "true" if include_data else "false"},
        )
        return Execution.from_payload(self._json_object(response))

    async def delete_execution(self, execution_id: str) -> Execution:
        response = await self._request("DELETE", f"/executions/{self._identifier(execution_id)}")
        return Execution.from_payload(self._json_object(response))

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> N8nClient:
        if self._closed:
            raise RuntimeError("client is closed")
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        await self.aclose()

    async def _change_activation(self, workflow_id: str, action: str) -> Workflow:
        response = await self._request(
            "POST",
            f"/workflows/{self._identifier(workflow_id)}/{action}",
        )
        return Workflow.from_payload(self._json_object(response))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        if self._closed:
            raise RuntimeError("client is closed")
        response = await self._client.request(
            method,
            f"{self._config.api_base_url}{path}",
            params=params,
            headers={
                "Accept": "application/json",
                "X-N8N-API-KEY": self._config.api_key,
            },
            timeout=self._config.timeout_seconds,
        )
        if response.is_error:
            raise self._api_error(response)
        return response

    @staticmethod
    def _identifier(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("identifier cannot be empty")
        return quote(normalized, safe="")

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise N8nResponseError("n8n returned a non-JSON response") from exc
        if not isinstance(body, dict):
            raise N8nResponseError("n8n returned a JSON value that is not an object")
        return body

    @staticmethod
    def _api_error(response: httpx.Response) -> N8nApiError:
        try:
            body = response.json()
        except ValueError:
            body = None
        message = response.text or response.reason_phrase or "request failed"
        if isinstance(body, dict):
            candidate = body.get("message") or body.get("error")
            if isinstance(candidate, str):
                message = candidate
        return N8nApiError(
            status_code=response.status_code,
            message=message,
            request_id=response.headers.get("x-request-id"),
            details=body,
        )
