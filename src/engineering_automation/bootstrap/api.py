"""Environment-driven composition root for the FastAPI service."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from fastapi import FastAPI

from engineering_automation.application.use_cases.reconcile_automations import (
    ReconcileAutomations,
)
from engineering_automation.bootstrap.automation import build_automation_registration
from engineering_automation.bootstrap.webhooks import build_webhook_ingestor
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
    webhook_secrets: Mapping[str, str] = field(repr=False)
    port_region: PortRegion = PortRegion.EU
    port_base_url: str | None = None
    max_concurrency: int = 5
    webhook_max_age_seconds: int = 300
    webhook_future_tolerance_seconds: int = 30
    webhook_receipt_ttl_seconds: int = 86400

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
        max_concurrency = cls._integer_setting(
            "AUTOMATION_MAX_CONCURRENCY",
            concurrency_value,
            minimum=1,
        )

        webhook_secrets_value = required("WEBHOOK_SECRETS_JSON")
        try:
            decoded_secrets = json.loads(webhook_secrets_value)
        except json.JSONDecodeError as error:
            raise ValueError("WEBHOOK_SECRETS_JSON must be valid JSON") from error
        if not isinstance(decoded_secrets, dict) or not decoded_secrets:
            raise ValueError("WEBHOOK_SECRETS_JSON must be a non-empty object")
        webhook_secrets: dict[str, str] = {}
        for source, secret in decoded_secrets.items():
            if not isinstance(source, str) or not source.strip():
                raise ValueError("WEBHOOK_SECRETS_JSON source names must be non-empty strings")
            if not isinstance(secret, str) or not secret:
                raise ValueError("WEBHOOK_SECRETS_JSON secrets must be non-empty strings")
            normalized = source.strip().lower()
            if normalized in webhook_secrets:
                raise ValueError("WEBHOOK_SECRETS_JSON source names must be unique")
            webhook_secrets[normalized] = secret

        webhook_max_age_seconds = cls._integer_setting(
            "WEBHOOK_MAX_AGE_SECONDS",
            values.get("WEBHOOK_MAX_AGE_SECONDS", "300"),
            minimum=1,
        )
        webhook_future_tolerance_seconds = cls._integer_setting(
            "WEBHOOK_FUTURE_TOLERANCE_SECONDS",
            values.get("WEBHOOK_FUTURE_TOLERANCE_SECONDS", "30"),
            minimum=0,
        )
        webhook_receipt_ttl_seconds = cls._integer_setting(
            "WEBHOOK_RECEIPT_TTL_SECONDS",
            values.get("WEBHOOK_RECEIPT_TTL_SECONDS", "86400"),
            minimum=webhook_max_age_seconds,
        )

        return cls(
            api_key=required("AUTOMATION_API_KEY"),
            port_client_id=required("PORT_CLIENT_ID"),
            port_client_secret=required("PORT_CLIENT_SECRET"),
            port_blueprint=required("PORT_AUTOMATION_BLUEPRINT"),
            n8n_base_url=required("N8N_BASE_URL"),
            n8n_api_key=required("N8N_API_KEY"),
            webhook_secrets=webhook_secrets,
            port_region=region,
            port_base_url=values.get("PORT_BASE_URL") or None,
            max_concurrency=max_concurrency,
            webhook_max_age_seconds=webhook_max_age_seconds,
            webhook_future_tolerance_seconds=webhook_future_tolerance_seconds,
            webhook_receipt_ttl_seconds=webhook_receipt_ttl_seconds,
        )

    @staticmethod
    def _integer_setting(name: str, value: str, *, minimum: int) -> int:
        try:
            parsed = int(value.strip())
        except ValueError as error:
            raise ValueError(f"{name} must be an integer") from error
        if parsed < minimum:
            raise ValueError(f"{name} must be at least {minimum}")
        return parsed


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
    webhook_ingestor = build_webhook_ingestor(
        registrar,
        settings.webhook_secrets,
        max_age_seconds=settings.webhook_max_age_seconds,
        future_tolerance_seconds=settings.webhook_future_tolerance_seconds,
        receipt_ttl_seconds=settings.webhook_receipt_ttl_seconds,
    )

    async def close_clients() -> None:
        await asyncio.gather(port_client.aclose(), n8n_client.aclose())

    return create_app(
        registrar,
        reconciler,
        api_key=settings.api_key,
        webhook_ingestor=webhook_ingestor,
        close=close_clients,
    )
