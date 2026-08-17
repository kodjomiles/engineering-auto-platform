from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI

from engineering_automation.application.use_cases.reconcile_automations import (
    ReconcileAutomations,
)
from engineering_automation.domain.automation import (
    AutomationDefinition,
    AutomationReconciliation,
    AutomationReconciliationReport,
    AutomationRegistration,
    CatalogReference,
    ReconciliationState,
    WorkflowReference,
)
from engineering_automation.interfaces.http.api import create_app

API_KEY = "test-api-key"
AUTH_HEADERS = {"X-API-Key": API_KEY}


@asynccontextmanager
async def api_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: Any = None,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        async with api_client(app) as client:
            return await client.request(method, path, json=json, headers=headers)

    return asyncio.run(send())


def registration(identifier: str, *, changed: bool = True) -> AutomationRegistration:
    return AutomationRegistration(
        identifier,
        WorkflowReference(f"workflow-{identifier}", f"Workflow {identifier}", True),
        CatalogReference(identifier),
        changed,
    )


class FakeRegistrar:
    def __init__(self) -> None:
        self.definitions: list[AutomationDefinition] = []
        self.error: Exception | None = None

    async def execute(self, definition: AutomationDefinition) -> AutomationRegistration:
        self.definitions.append(definition)
        if self.error is not None:
            raise self.error
        return registration(definition.identifier)


class FakeReconciler:
    def __init__(self) -> None:
        self.definitions: tuple[AutomationDefinition, ...] = ()
        self.error: Exception | None = None

    async def execute(
        self,
        definitions: Iterable[AutomationDefinition],
    ) -> AutomationReconciliationReport:
        self.definitions = tuple(definitions)
        if self.error is not None:
            raise self.error
        outcomes = tuple(
            AutomationReconciliation(
                definition.identifier,
                ReconciliationState.SUCCEEDED,
                registration=registration(definition.identifier),
            )
            for definition in self.definitions
        )
        return AutomationReconciliationReport(outcomes)


def automation_payload(identifier: str = "automation-1") -> dict[str, Any]:
    return {
        "identifier": identifier,
        "title": "Deploy service",
        "workflowId": f"workflow-{identifier}",
        "active": True,
        "properties": {"owner": "platform"},
        "relations": {"service": "payments"},
    }


def test_health_and_documentation_are_available_without_authentication() -> None:
    app = create_app(FakeRegistrar(), FakeReconciler(), api_key=API_KEY)

    assert request(app, "GET", "/health").json() == {"status": "ok", "version": "0.1.0"}
    assert request(app, "GET", "/docs").status_code == 200
    assert request(app, "GET", "/redoc").status_code == 200
    schema_response = request(app, "GET", "/openapi.json")

    assert schema_response.status_code == 200
    schema = schema_response.json()
    assert schema["info"]["title"] == "Engineering Automation API"
    assert set(schema["paths"]) == {
        "/health",
        "/v1/automations/register",
        "/v1/automations/reconcile",
    }
    assert schema["components"]["securitySchemes"]["AutomationApiKey"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Service API key configured by the operator.",
    }
    assert schema["paths"]["/v1/automations/register"]["post"]["security"] == [
        {"AutomationApiKey": []}
    ]
    register_responses = schema["paths"]["/v1/automations/register"]["post"]["responses"]
    reconcile_responses = schema["paths"]["/v1/automations/reconcile"]["post"]["responses"]
    assert "409" not in register_responses
    assert {"200", "401", "409", "422", "502"}.issubset(reconcile_responses)
    assert "PORT_CLIENT_SECRET" not in schema_response.text
    assert "N8N_API_KEY" not in schema_response.text


def test_automation_routes_require_a_valid_api_key() -> None:
    app = create_app(FakeRegistrar(), FakeReconciler(), api_key=API_KEY)

    missing = request(
        app,
        "POST",
        "/v1/automations/register",
        json=automation_payload(),
    )
    invalid = request(
        app,
        "POST",
        "/v1/automations/register",
        json=automation_payload(),
        headers={"X-API-Key": "wrong"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert missing.json() == {
        "detail": {
            "code": "unauthorized",
            "message": "a valid API key is required",
        }
    }
    assert missing.headers["www-authenticate"] == "ApiKey"


def test_register_translates_camel_case_request_and_response_contracts() -> None:
    registrar = FakeRegistrar()
    app = create_app(registrar, FakeReconciler(), api_key=API_KEY)

    response = request(
        app,
        "POST",
        "/v1/automations/register",
        json=automation_payload(),
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {
        "automationId": "automation-1",
        "workflow": {
            "identifier": "workflow-automation-1",
            "name": "Workflow automation-1",
            "active": True,
        },
        "catalog": {"identifier": "automation-1"},
        "workflowStateChanged": True,
    }
    definition = registrar.definitions[0]
    assert definition.workflow_id == "workflow-automation-1"
    assert definition.properties == {"owner": "platform"}
    assert definition.relations == {"service": "payments"}


def test_request_validation_rejects_blank_and_unknown_fields() -> None:
    payload = automation_payload()
    payload["identifier"] = " "
    payload["unexpected"] = True
    app = create_app(FakeRegistrar(), FakeReconciler(), api_key=API_KEY)

    response = request(
        app,
        "POST",
        "/v1/automations/register",
        json=payload,
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert {error["type"] for error in errors} == {"string_too_short", "extra_forbidden"}


def test_registration_failure_returns_a_safe_upstream_error() -> None:
    registrar = FakeRegistrar()
    registrar.error = RuntimeError("secret provider detail")
    app = create_app(registrar, FakeReconciler(), api_key=API_KEY)

    response = request(
        app,
        "POST",
        "/v1/automations/register",
        json=automation_payload(),
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": {
            "code": "registration_failed",
            "message": "the automation could not be registered",
        }
    }
    assert "secret provider detail" not in response.text


def test_reconcile_returns_ordered_success_and_failure_outcomes() -> None:
    class PartialReconciler(FakeReconciler):
        async def execute(
            self,
            definitions: Iterable[AutomationDefinition],
        ) -> AutomationReconciliationReport:
            self.definitions = tuple(definitions)
            return AutomationReconciliationReport(
                (
                    AutomationReconciliation(
                        "automation-1",
                        ReconciliationState.SUCCEEDED,
                        registration=registration("automation-1", changed=False),
                    ),
                    AutomationReconciliation(
                        "automation-2",
                        ReconciliationState.FAILED,
                        error="RuntimeError: Port unavailable",
                    ),
                )
            )

    reconciler = PartialReconciler()
    app = create_app(FakeRegistrar(), reconciler, api_key=API_KEY)

    response = request(
        app,
        "POST",
        "/v1/automations/reconcile",
        json={
            "automations": [
                automation_payload("automation-1"),
                automation_payload("automation-2"),
            ]
        },
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert [outcome["automationId"] for outcome in body["outcomes"]] == [
        "automation-1",
        "automation-2",
    ]
    assert body["outcomes"][0]["registration"]["workflowStateChanged"] is False
    assert body["outcomes"][1]["error"] == "RuntimeError: Port unavailable"
    assert [item.identifier for item in reconciler.definitions] == [
        "automation-1",
        "automation-2",
    ]


def test_duplicate_reconciliation_returns_conflict_without_provider_calls() -> None:
    registrar = FakeRegistrar()
    app = create_app(
        registrar,
        ReconcileAutomations(registrar),
        api_key=API_KEY,
    )
    duplicate = automation_payload("automation-1")

    response = request(
        app,
        "POST",
        "/v1/automations/reconcile",
        json={"automations": [duplicate, duplicate]},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "conflicting_definitions"
    assert registrar.definitions == []


def test_lifespan_closes_supplied_resources() -> None:
    closed = False

    async def close() -> None:
        nonlocal closed
        closed = True

    app = create_app(
        FakeRegistrar(),
        FakeReconciler(),
        api_key=API_KEY,
        close=close,
    )

    async def exercise() -> None:
        async with api_client(app):
            assert not closed

    asyncio.run(exercise())
    assert closed
