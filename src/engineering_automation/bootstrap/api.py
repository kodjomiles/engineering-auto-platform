"""Environment-driven composition root for the FastAPI service."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from fastapi import FastAPI

from engineering_automation.application.use_cases.reconcile_automations import (
    ReconcileAutomations,
)
from engineering_automation.bootstrap.automation import build_automation_registration
from engineering_automation.interfaces.http.api import create_app
from engineering_automation.n8n.client import N8nClient
from engineering_automation.n8n.config import N8nConfig
from engineering_automation.port.client import PortClient
from engineering_automation.port.config import PortConfig, PortRegion


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Validated environment settings for the HTTP composition root."""

    api_key: str = field(repr=False)
    port_client_id: str
    port_client_secret: str = field(repr=False)
    port_blueprint: str
    n8n_base_url: str
    n8n_api_key: str = field(repr=False)
    port_region: PortRegion = PortRegion.EU
    port_base_url: str | None = None
    max_concurrency: int = 5

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> ApiSettings:
        def required(name: str) -> str:
            value = values.get(name, "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            return value

        region_value = values.get("PORT_REGION", PortRegion.EU.value).strip().lower()
        try:
            region = PortRegion(region_value)
        except ValueError as error:
            raise ValueError("PORT_REGION must be 'eu' or 'us'") from error

        concurrency_value = values.get("AUTOMATION_MAX_CONCURRENCY", "5").strip()
        try:
            max_concurrency = int(concurrency_value)
        except ValueError as error:
            raise ValueError("AUTOMATION_MAX_CONCURRENCY must be an integer") from error
        if max_concurrency < 1:
            raise ValueError("AUTOMATION_MAX_CONCURRENCY must be at least 1")

        return cls(
            api_key=required("AUTOMATION_API_KEY"),
            port_client_id=required("PORT_CLIENT_ID"),
            port_client_secret=required("PORT_CLIENT_SECRET"),
            port_blueprint=required("PORT_AUTOMATION_BLUEPRINT"),
            n8n_base_url=required("N8N_BASE_URL"),
            n8n_api_key=required("N8N_API_KEY"),
            port_region=region,
            port_base_url=values.get("PORT_BASE_URL") or None,
            max_concurrency=max_concurrency,
        )


def create_environment_app() -> FastAPI:
    """Build the production API from process environment variables."""

    settings = ApiSettings.from_mapping(os.environ)
    port_client = PortClient(
        PortConfig(
            client_id=settings.port_client_id,
            client_secret=settings.port_client_secret,
            region=settings.port_region,
            base_url=settings.port_base_url,
        )
    )
    n8n_client = N8nClient(N8nConfig(base_url=settings.n8n_base_url, api_key=settings.n8n_api_key))
    registrar = build_automation_registration(
        port_client,
        n8n_client,
        blueprint_identifier=settings.port_blueprint,
    )
    reconciler = ReconcileAutomations(
        registrar,
        max_concurrency=settings.max_concurrency,
    )

    async def close_clients() -> None:
        await asyncio.gather(port_client.aclose(), n8n_client.aclose())

    return create_app(
        registrar,
        reconciler,
        api_key=settings.api_key,
        close=close_clients,
    )
