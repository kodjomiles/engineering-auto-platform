from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx
import pytest

from engineering_automation.n8n import (
    Execution,
    N8nApiError,
    N8nClient,
    N8nConfig,
    N8nResponseError,
    Workflow,
    WorkflowPage,
)

Handler = Callable[[httpx.Request], httpx.Response]


def run_client[T](handler: Handler, operation: Callable[[N8nClient], Awaitable[T]]) -> T:
    async def exercise() -> T:
        config = N8nConfig("https://automation.example.com", "api-key")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await operation(N8nClient(config, client=http_client))

    return asyncio.run(exercise())


def workflow_payload(identifier: str = "workflow-1", *, active: bool = True) -> dict[str, object]:
    return {
        "id": identifier,
        "name": f"Workflow {identifier}",
        "active": active,
        "tags": [{"name": "platform"}],
    }


def execution_payload(identifier: str = "execution-1") -> dict[str, object]:
    return {
        "id": identifier,
        "workflowId": "workflow-1",
        "status": "success",
        "finished": True,
    }


def test_get_workflow_authenticates_and_encodes_identifier() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=workflow_payload())

    workflow = run_client(handler, lambda client: client.get_workflow(" workflow/1 "))
    request = requests[0]
    assert workflow.identifier == "workflow-1"
    assert request.method == "GET"
    assert request.url.raw_path == b"/api/v1/workflows/workflow%2F1"
    assert request.headers["X-N8N-API-KEY"] == "api-key"


def test_list_workflows_encodes_filters_and_cursor() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [workflow_payload()], "nextCursor": "next"})

    async def operation(client: N8nClient) -> WorkflowPage:
        return await client.list_workflows_page(
            active=True,
            tags=("platform", " production ", ""),
            limit=50,
            cursor="current",
        )

    page = run_client(handler, operation)
    assert page.next_cursor == "next"
    assert page.workflows[0].identifier == "workflow-1"
    assert dict(requests[0].url.params) == {
        "limit": "50",
        "active": "true",
        "tags": "platform,production",
        "cursor": "current",
    }


def test_workflow_iterator_follows_cursor_pages() -> None:
    cursors: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursors.append(request.url.params.get("cursor"))
        if len(cursors) == 1:
            return httpx.Response(
                200, json={"data": [workflow_payload("one")], "nextCursor": "two"}
            )
        return httpx.Response(200, json={"data": [workflow_payload("two")]})

    async def operation(client: N8nClient) -> list[str]:
        return [workflow.identifier async for workflow in client.iter_workflows(page_size=1)]

    assert run_client(handler, operation) == ["one", "two"]
    assert cursors == [None, "two"]


def test_workflow_iterator_rejects_repeated_cursor() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "nextCursor": "same"})

    async def operation(client: N8nClient) -> list[Workflow]:
        return [workflow async for workflow in client.iter_workflows()]

    with pytest.raises(N8nResponseError, match="repeated"):
        run_client(handler, operation)


@pytest.mark.parametrize(("method", "expected_active"), [("activate", True), ("deactivate", False)])
def test_workflow_activation_endpoints(method: str, expected_active: bool) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=workflow_payload(active=expected_active))

    async def operation(client: N8nClient) -> Workflow:
        action = client.activate_workflow if method == "activate" else client.deactivate_workflow
        return await action("workflow-1")

    workflow = run_client(handler, operation)
    assert workflow.active is expected_active
    assert requests[0].method == "POST"
    assert requests[0].url.path == f"/api/v1/workflows/workflow-1/{method}"


def test_get_execution_controls_data_inclusion() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=execution_payload())

    result = run_client(
        handler, lambda client: client.get_execution("execution-1", include_data=True)
    )
    assert result == Execution("execution-1", "workflow-1", "success", True)
    assert requests[0].url.params["includeData"] == "true"


def test_delete_execution_returns_deleted_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=execution_payload())

    result = run_client(handler, lambda client: client.delete_execution("execution-1"))
    assert result.identifier == "execution-1"
    assert requests[0].method == "DELETE"


@pytest.mark.parametrize("limit", [0, 251])
def test_list_workflows_rejects_invalid_limit(limit: int) -> None:
    async def operation(client: N8nClient) -> WorkflowPage:
        return await client.list_workflows_page(limit=limit)

    with pytest.raises(ValueError, match="between 1 and 250"):
        run_client(lambda _: httpx.Response(500), operation)


def test_api_error_preserves_response_context() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "API key rejected"},
            headers={"x-request-id": "request-123"},
        )

    with pytest.raises(N8nApiError) as captured:
        run_client(handler, lambda client: client.get_workflow("one"))
    assert captured.value.status_code == 403
    assert captured.value.message == "API key rejected"
    assert captured.value.request_id == "request-123"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, text="not-json"), "non-JSON"),
        (httpx.Response(200, json=[]), "not an object"),
        (httpx.Response(200, json={}), "data array"),
        (httpx.Response(200, json={"data": [], "nextCursor": 5}), "nextCursor"),
    ],
)
def test_list_workflows_rejects_malformed_responses(response: httpx.Response, message: str) -> None:
    with pytest.raises(N8nResponseError, match=message):
        run_client(lambda _: response, lambda client: client.list_workflows_page())


def test_client_rejects_blank_identifier() -> None:
    with pytest.raises(ValueError, match="identifier"):
        run_client(lambda _: httpx.Response(500), lambda client: client.get_workflow(" "))


def test_client_cannot_be_reused_after_close() -> None:
    async def operation(client: N8nClient) -> None:
        await client.aclose()
        await client.get_workflow("one")

    with pytest.raises(RuntimeError, match="closed"):
        run_client(lambda _: httpx.Response(200, json=workflow_payload()), operation)
