from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import httpx
import pytest

from engineering_automation.port.client import PortClient
from engineering_automation.port.config import PortConfig
from engineering_automation.port.errors import PortApiError, PortResponseError
from engineering_automation.port.models import Entity, EntitySearchPage

Handler = Callable[[httpx.Request], httpx.Response]


def run_client[T](handler: Handler, operation: Callable[[PortClient], Awaitable[T]]) -> T:
    async def exercise() -> T:
        config = PortConfig("client-id", "client-secret")
        async with httpx.AsyncClient(
            base_url=config.api_base_url,
            transport=httpx.MockTransport(handler),
        ) as http_client:
            client = PortClient(config, client=http_client, clock=lambda: 100.0)
            return await operation(client)

    return asyncio.run(exercise())


def auth_response(token: str = "token-1", expires_in: int = 900) -> httpx.Response:
    return httpx.Response(
        200,
        json={"ok": True, "accessToken": token, "expiresIn": expires_in, "tokenType": "Bearer"},
    )


def request_json(request: httpx.Request) -> object:
    return json.loads(request.content)


def test_upsert_authenticates_and_sends_merge_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/auth/access_token":
            return auth_response()
        return httpx.Response(201, json={"ok": True, "entity": {"identifier": "service-a"}})

    async def operation(client: PortClient) -> object:
        return await client.upsert_entity(
            "service/type",
            Entity("service-a", properties={"language": "Python"}),
            run_id="run-1",
        )

    result = run_client(handler, operation)
    assert result == {"ok": True, "entity": {"identifier": "service-a"}}
    assert request_json(requests[0]) == {
        "clientId": "client-id",
        "clientSecret": "client-secret",
    }
    upsert = requests[1]
    assert upsert.url.raw_path.split(b"?", 1)[0] == b"/v1/blueprints/service%2Ftype/entities"
    assert dict(upsert.url.params) == {
        "upsert": "true",
        "merge": "true",
        "create_missing_related_entities": "false",
        "validation_only": "false",
        "run_id": "run-1",
    }
    assert upsert.headers["Authorization"] == "Bearer token-1"
    assert request_json(upsert) == {
        "identifier": "service-a",
        "properties": {"language": "Python"},
        "relations": {},
    }


def test_token_is_reused_for_multiple_requests() -> None:
    auth_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        if request.url.path == "/v1/auth/access_token":
            auth_calls += 1
            return auth_response()
        return httpx.Response(201, json={"ok": True})

    async def operation(client: PortClient) -> int:
        await client.upsert_entity("service", Entity("one"))
        await client.upsert_entity("service", Entity("two"))
        return auth_calls

    assert run_client(handler, operation) == 1


def test_unauthorized_response_refreshes_token_once() -> None:
    issued_tokens = iter(("expired-token", "fresh-token"))
    authorization_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/access_token":
            return auth_response(next(issued_tokens))
        authorization_headers.append(request.headers["Authorization"])
        if len(authorization_headers) == 1:
            return httpx.Response(401, json={"error": "Unauthorized"})
        return httpx.Response(201, json={"ok": True})

    async def operation(client: PortClient) -> object:
        return await client.upsert_entity("service", Entity("one"))

    assert run_client(handler, operation) == {"ok": True}
    assert authorization_headers == ["Bearer expired-token", "Bearer fresh-token"]


def test_execute_action_returns_run_and_encodes_inputs() -> None:
    action_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/access_token":
            return auth_response()
        action_requests.append(request)
        return httpx.Response(202, json={"ok": True, "run": {"id": "run-123"}})

    async def operation(client: PortClient) -> object:
        return await client.execute_action(
            "deploy/service",
            {"environment": "production"},
            entity_identifier="payments",
            run_as="developer@example.com",
        )

    assert run_client(handler, operation) == {"id": "run-123"}
    request = action_requests[0]
    assert request.url.raw_path.split(b"?", 1)[0] == b"/v1/actions/deploy%2Fservice/runs"
    assert request.url.params["run_as"] == "developer@example.com"
    assert request_json(request) == {
        "properties": {"environment": "production"},
        "entity": "payments",
    }


def test_search_page_encodes_filters_and_cursor() -> None:
    search_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/access_token":
            return auth_response()
        search_requests.append(request)
        return httpx.Response(
            200,
            json={"ok": True, "entities": [{"identifier": "one"}], "next": "cursor-2"},
        )

    query = {"combinator": "and", "rules": []}

    async def operation(client: PortClient) -> EntitySearchPage:
        return await client.search_entities_page(
            "service",
            query=query,
            include=("$identifier", "language"),
            exclude=("secrets",),
            limit=50,
            cursor="cursor-1",
        )

    page = run_client(handler, operation)
    assert page.entities == ({"identifier": "one"},)
    assert page.next_cursor == "cursor-2"
    assert request_json(search_requests[0]) == {
        "query": query,
        "include": ["$identifier", "language"],
        "exclude": ["secrets"],
        "limit": 50,
        "from": "cursor-1",
    }


def test_iterator_follows_all_search_pages() -> None:
    cursors: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/access_token":
            return auth_response()
        body = request_json(request)
        assert isinstance(body, dict)
        cursors.append(body.get("from"))
        if len(cursors) == 1:
            return httpx.Response(
                200,
                json={"entities": [{"identifier": "one"}], "next": "cursor-2"},
            )
        return httpx.Response(200, json={"entities": [{"identifier": "two"}]})

    async def operation(client: PortClient) -> object:
        return [entity async for entity in client.iter_entities("service", page_size=1)]

    assert run_client(handler, operation) == [
        {"identifier": "one"},
        {"identifier": "two"},
    ]
    assert cursors == [None, "cursor-2"]


def test_iterator_rejects_repeated_cursor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/access_token":
            return auth_response()
        return httpx.Response(200, json={"entities": [], "next": "same"})

    async def operation(client: PortClient) -> object:
        return [entity async for entity in client.iter_entities("service")]

    with pytest.raises(PortResponseError, match="repeated"):
        run_client(handler, operation)


@pytest.mark.parametrize("limit", [0, 1001])
def test_search_rejects_invalid_page_size(limit: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be sent")

    async def operation(client: PortClient) -> object:
        return await client.search_entities_page("service", limit=limit)

    with pytest.raises(ValueError, match="between"):
        run_client(handler, operation)


def test_api_errors_preserve_status_code_and_request_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/access_token":
            return auth_response()
        return httpx.Response(
            422,
            headers={"x-request-id": "req-123"},
            json={"error": "VALIDATION_ERROR", "message": "invalid entity"},
        )

    async def operation(client: PortClient) -> object:
        return await client.upsert_entity("service", Entity("one"))

    with pytest.raises(PortApiError) as captured:
        run_client(handler, operation)
    assert captured.value.status_code == 422
    assert captured.value.error_code == "VALIDATION_ERROR"
    assert captured.value.request_id == "req-123"
    assert str(captured.value) == "Port API returned HTTP 422 (VALIDATION_ERROR): invalid entity"


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": True},
        {"accessToken": "", "expiresIn": 900},
        {"accessToken": "token", "expiresIn": 0},
        {"accessToken": "token", "expiresIn": True},
        {"accessToken": "token", "expiresIn": "900"},
    ],
)
def test_authentication_rejects_malformed_success(payload: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def operation(client: PortClient) -> object:
        return await client.upsert_entity("service", Entity("one"))

    with pytest.raises(PortResponseError):
        run_client(handler, operation)


def test_action_rejects_missing_run_object() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/access_token":
            return auth_response()
        return httpx.Response(202, json={"ok": True})

    async def operation(client: PortClient) -> object:
        return await client.execute_action("deploy", {})

    with pytest.raises(PortResponseError, match="run object"):
        run_client(handler, operation)


def test_injected_http_client_does_not_require_base_url() -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        if request.url.path == "/v1/auth/access_token":
            return auth_response()
        return httpx.Response(201, json={"ok": True})

    async def exercise() -> object:
        config = PortConfig("client", "secret")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = PortClient(config, client=http_client)
            return await client.upsert_entity("service", Entity("one"))

    assert asyncio.run(exercise()) == {"ok": True}
    assert requested_hosts == ["api.port.io", "api.port.io"]


def test_closed_client_rejects_requests() -> None:
    async def exercise() -> None:
        config = PortConfig("client", "secret")
        client = PortClient(config)
        await client.aclose()
        await client.upsert_entity("service", Entity("one"))

    with pytest.raises(RuntimeError, match="closed"):
        asyncio.run(exercise())
