"""Authenticated FastAPI adapter for automation application ports."""

from __future__ import annotations

import hmac
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path,
    Request,
    Response,
    Security,
    status,
)
from fastapi.security import APIKeyHeader

from engineering_automation.application.ports.automation import (
    AutomationReconciler,
    AutomationRegistrar,
)
from engineering_automation.application.ports.inbound_webhooks import WebhookIngestor
from engineering_automation.application.use_cases.ingest_webhook import (
    WebhookAuthenticationError,
    WebhookPayloadError,
    WebhookProcessingError,
)
from engineering_automation.domain.inbound_webhooks import (
    WebhookIngestionRequest,
    WebhookIngestionState,
)
from engineering_automation.interfaces.http.schemas import (
    ApiErrorResponse,
    AutomationInput,
    HealthResponse,
    ReconciliationRequest,
    ReconciliationResponse,
    RegistrationResponse,
    WebhookIngestionResponse,
)

LOGGER = logging.getLogger(__name__)
CloseCallback = Callable[[], Awaitable[None]]
API_KEY_HEADER = APIKeyHeader(
    name="X-API-Key",
    scheme_name="AutomationApiKey",
    description="Service API key configured by the operator.",
    auto_error=False,
)
WEBHOOK_SIGNATURE_HEADER = APIKeyHeader(
    name="X-Webhook-Signature",
    scheme_name="WebhookSignature",
    description=(
        "HMAC-SHA256 of `<X-Webhook-Timestamp>.<raw request body>` using the source secret."
    ),
    auto_error=False,
)


def create_app(
    registrar: AutomationRegistrar,
    reconciler: AutomationReconciler,
    *,
    api_key: str,
    webhook_ingestor: WebhookIngestor | None = None,
    close: CloseCallback | None = None,
) -> FastAPI:
    """Create an API whose concrete provider dependencies are supplied externally."""

    expected_api_key = api_key.strip()
    if not expected_api_key:
        raise ValueError("api_key cannot be empty")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if close is not None:
                await close()

    app = FastAPI(
        title="Engineering Automation API",
        summary="Coordinate Port catalog records and n8n workflow state.",
        description=(
            "Register individual engineering automations or reconcile a collection of desired "
            "definitions. Automation operations require the `X-API-Key` header; inbound events "
            "use source-specific HMAC signatures."
        ),
        version="0.1.0",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "Operations", "description": "Service health and readiness."},
            {
                "name": "Automations",
                "description": "Register and reconcile Port/n8n automation definitions.",
            },
            {
                "name": "Webhooks",
                "description": "Authenticate and idempotently process engineering events.",
            },
        ],
    )

    def authorize(
        supplied_api_key: Annotated[str | None, Security(API_KEY_HEADER)],
    ) -> None:
        if supplied_api_key is None or not hmac.compare_digest(
            supplied_api_key.encode(),
            expected_api_key.encode(),
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "unauthorized", "message": "a valid API key is required"},
                headers={"WWW-Authenticate": "ApiKey"},
            )

    common_error_responses: dict[int | str, dict[str, Any]] = {
        401: {"model": ApiErrorResponse, "description": "Missing or invalid API key."},
        502: {"model": ApiErrorResponse, "description": "An upstream provider failed."},
    }
    reconciliation_error_responses = {
        **common_error_responses,
        409: {"model": ApiErrorResponse, "description": "Conflicting automation definitions."},
    }
    router = APIRouter(
        prefix="/v1/automations",
        tags=["Automations"],
        dependencies=[Depends(authorize)],
    )

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["Operations"],
        summary="Check service health",
    )
    async def health() -> HealthResponse:
        return HealthResponse(version=app.version)

    @router.post(
        "/register",
        response_model=RegistrationResponse,
        responses=common_error_responses,
        summary="Register one automation",
    )
    async def register(request: AutomationInput) -> RegistrationResponse:
        try:
            registration = await registrar.execute(request.to_domain())
        except Exception as error:
            LOGGER.exception("automation registration failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "registration_failed",
                    "message": "the automation could not be registered",
                },
            ) from error
        return RegistrationResponse.from_domain(registration)

    @router.post(
        "/reconcile",
        response_model=ReconciliationResponse,
        responses=reconciliation_error_responses,
        summary="Reconcile automation definitions",
    )
    async def reconcile(request: ReconciliationRequest) -> ReconciliationResponse:
        try:
            report = await reconciler.execute(
                automation.to_domain() for automation in request.automations
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "conflicting_definitions", "message": str(error)},
            ) from error
        except Exception as error:
            LOGGER.exception("automation reconciliation failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "reconciliation_failed",
                    "message": "the automations could not be reconciled",
                },
            ) from error
        return ReconciliationResponse.from_domain(report)

    app.include_router(router)

    webhook_error_responses: dict[int | str, dict[str, Any]] = {
        401: {"model": ApiErrorResponse, "description": "Webhook authentication failed."},
        502: {"model": ApiErrorResponse, "description": "Routed event processing failed."},
        503: {"model": ApiErrorResponse, "description": "Webhook ingestion is not configured."},
    }

    @app.post(
        "/v1/webhooks/events/{source}",
        response_model=WebhookIngestionResponse,
        status_code=status.HTTP_202_ACCEPTED,
        responses=webhook_error_responses,
        tags=["Webhooks"],
        summary="Ingest a signed engineering event",
    )
    async def ingest_webhook(
        source: Annotated[
            str,
            Path(
                min_length=1,
                max_length=64,
                pattern=r"^[a-z0-9][a-z0-9._-]*$",
            ),
        ],
        http_request: Request,
        http_response: Response,
        webhook_id: Annotated[
            str,
            Header(alias="X-Webhook-Id", min_length=1, max_length=256),
        ],
        timestamp: Annotated[int, Header(alias="X-Webhook-Timestamp", ge=0)],
        signature: Annotated[str | None, Security(WEBHOOK_SIGNATURE_HEADER)],
    ) -> WebhookIngestionResponse:
        if webhook_ingestor is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "webhook_ingestion_unavailable",
                    "message": "webhook ingestion is not configured",
                },
            )
        if signature is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "invalid_webhook",
                    "message": "webhook authentication failed",
                },
            )
        raw_body = await http_request.body()
        ingestion_request = WebhookIngestionRequest(
            webhook_id,
            timestamp,
            signature,
            raw_body,
            source,
        )
        try:
            result = await webhook_ingestor.execute(ingestion_request)
        except WebhookAuthenticationError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "invalid_webhook",
                    "message": "webhook authentication failed",
                },
            ) from error
        except WebhookPayloadError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "invalid_webhook_payload",
                    "message": "webhook event payload is invalid",
                },
            ) from error
        except WebhookProcessingError as error:
            LOGGER.warning(
                "webhook processing failed",
                extra={"webhook_id": webhook_id, "source": source},
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "webhook_processing_failed",
                    "message": "the event could not be processed",
                },
            ) from error
        except Exception as error:
            LOGGER.exception("webhook ingestion failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "webhook_processing_failed",
                    "message": "the event could not be processed",
                },
            ) from error

        if result.state is WebhookIngestionState.DUPLICATE:
            http_response.status_code = status.HTTP_200_OK
        return WebhookIngestionResponse.from_domain(result)

    return app
