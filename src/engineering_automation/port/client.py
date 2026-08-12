"""Async Port API client with cached organization authentication."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from engineering_automation.port.config import PortConfig
from engineering_automation.port.errors import PortApiError, PortResponseError
from engineering_automation.port.models import Entity, EntitySearchPage

Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class _AccessToken:
    value: str
    expires_at: float


class PortClient:
    """Call a focused, production-useful subset of Port's REST API."""

    def __init__(
        self,
        config: PortConfig,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Clock = time.time,
    ) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.api_base_url,
            timeout=config.timeout_seconds,
            headers={"Accept": "application/json"},
        )
        self._owns_client = client is None
        self._clock = clock
        self._token: _AccessToken | None = None
        self._token_lock = asyncio.Lock()
        self._closed = False

    async def upsert_entity(
        self,
        blueprint_identifier: str,
        entity: Entity,
        *,
        merge: bool = True,
        create_missing_related_entities: bool = False,
        validation_only: bool = False,
        run_id: str | None = None,
    ) -> Mapping[str, Any]:
        """Create or update one catalog entity."""

        blueprint = self._path_identifier("blueprint_identifier", blueprint_identifier)
        params = {
            "upsert": "true",
            "merge": self._boolean(merge),
            "create_missing_related_entities": self._boolean(create_missing_related_entities),
            "validation_only": self._boolean(validation_only),
        }
        if run_id:
            params["run_id"] = run_id
        response = await self._request(
            "POST",
            f"/v1/blueprints/{blueprint}/entities",
            json=entity.to_payload(),
            params=params,
        )
        return self._json_object(response)

    async def execute_action(
        self,
        action_identifier: str,
        properties: Mapping[str, Any],
        *,
        entity_identifier: str | None = None,
        run_as: str | None = None,
    ) -> Mapping[str, Any]:
        """Execute a Port self-service action and return its run object."""

        action = self._path_identifier("action_identifier", action_identifier)
        payload: dict[str, Any] = {"properties": dict(properties)}
        if entity_identifier is not None:
            payload["entity"] = entity_identifier
        params = {"run_as": run_as} if run_as else None
        response = await self._request(
            "POST",
            f"/v1/actions/{action}/runs",
            json=payload,
            params=params,
        )
        body = self._json_object(response)
        run = body.get("run")
        if not isinstance(run, dict):
            raise PortResponseError("Port action response is missing a run object")
        return run

    async def search_entities_page(
        self,
        blueprint_identifier: str,
        *,
        query: Mapping[str, Any] | None = None,
        include: Sequence[str] = (),
        exclude: Sequence[str] = (),
        limit: int = 200,
        cursor: str | None = None,
    ) -> EntitySearchPage:
        """Fetch one cursor-based page of blueprint entities."""

        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        blueprint = self._path_identifier("blueprint_identifier", blueprint_identifier)
        payload: dict[str, Any] = {"limit": limit}
        if query is not None:
            payload["query"] = dict(query)
        if include:
            payload["include"] = list(include)
        if exclude:
            payload["exclude"] = list(exclude)
        if cursor:
            payload["from"] = cursor

        response = await self._request(
            "POST",
            f"/v1/blueprints/{blueprint}/entities/search",
            json=payload,
        )
        body = self._json_object(response)
        raw_entities = body.get("entities")
        if not isinstance(raw_entities, list) or not all(
            isinstance(entity, dict) for entity in raw_entities
        ):
            raise PortResponseError("Port search response is missing an entities array")
        next_cursor = body.get("next")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise PortResponseError("Port search response contains an invalid next cursor")
        return EntitySearchPage(entities=tuple(raw_entities), next_cursor=next_cursor)

    async def iter_entities(
        self,
        blueprint_identifier: str,
        *,
        query: Mapping[str, Any] | None = None,
        include: Sequence[str] = (),
        exclude: Sequence[str] = (),
        page_size: int = 200,
    ) -> AsyncIterator[Mapping[str, Any]]:
        """Yield every matching entity across Port search pages."""

        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            page = await self.search_entities_page(
                blueprint_identifier,
                query=query,
                include=include,
                exclude=exclude,
                limit=page_size,
                cursor=cursor,
            )
            if page.next_cursor in seen_cursors:
                raise PortResponseError("Port search returned a repeated pagination cursor")
            for entity in page.entities:
                yield entity
            if page.next_cursor is None:
                return
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> PortClient:
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

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        if self._closed:
            raise RuntimeError("client is closed")
        token = await self._access_token()
        response = await self._client.request(
            method,
            self._url(path),
            json=json,
            params=params,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=self._config.timeout_seconds,
        )
        if response.status_code == 401:
            self._token = None
            token = await self._access_token()
            response = await self._client.request(
                method,
                self._url(path),
                json=json,
                params=params,
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                timeout=self._config.timeout_seconds,
            )
        if response.is_error:
            raise self._api_error(response)
        return response

    async def _access_token(self) -> str:
        if self._token_is_fresh():
            assert self._token is not None
            return self._token.value
        async with self._token_lock:
            if self._token_is_fresh():
                assert self._token is not None
                return self._token.value
            response = await self._client.post(
                self._url("/v1/auth/access_token"),
                json={
                    "clientId": self._config.client_id,
                    "clientSecret": self._config.client_secret,
                },
                headers={"Accept": "application/json"},
                timeout=self._config.timeout_seconds,
            )
            if response.is_error:
                raise self._api_error(response)
            body = self._json_object(response)
            token = body.get("accessToken")
            expires_in = body.get("expiresIn")
            if not isinstance(token, str) or not token:
                raise PortResponseError("Port authentication response is missing accessToken")
            if (
                isinstance(expires_in, bool)
                or not isinstance(expires_in, (int, float))
                or expires_in <= 0
            ):
                raise PortResponseError("Port authentication response has invalid expiresIn")
            usable_lifetime = max(
                0.0,
                float(expires_in) - self._config.token_refresh_skew_seconds,
            )
            self._token = _AccessToken(token, self._clock() + usable_lifetime)
            return token

    def _token_is_fresh(self) -> bool:
        return self._token is not None and self._clock() < self._token.expires_at

    def _url(self, path: str) -> str:
        return f"{self._config.api_base_url}{path}"

    @staticmethod
    def _path_identifier(name: str, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{name} cannot be empty")
        return quote(normalized, safe="")

    @staticmethod
    def _boolean(value: bool) -> str:
        return "true" if value else "false"

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise PortResponseError("Port returned a non-JSON response") from exc
        if not isinstance(body, dict):
            raise PortResponseError("Port returned a JSON value that is not an object")
        return body

    @staticmethod
    def _api_error(response: httpx.Response) -> PortApiError:
        try:
            body = response.json()
        except ValueError:
            body = None
        message = response.text or response.reason_phrase or "request failed"
        error_code: str | None = None
        details: Any = None
        if isinstance(body, dict):
            candidate_message = body.get("message") or body.get("error")
            if isinstance(candidate_message, str):
                message = candidate_message
            candidate_code = body.get("error")
            if isinstance(candidate_code, str):
                error_code = candidate_code
            details = body
        return PortApiError(
            status_code=response.status_code,
            message=message,
            error_code=error_code,
            request_id=response.headers.get("x-request-id"),
            details=details,
        )
