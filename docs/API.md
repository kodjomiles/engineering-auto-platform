# Engineering Automation API

The HTTP API registers desired n8n workflow state in the Port software catalog. It supports a
single atomic registration workflow, bounded batch reconciliation with per-item audit results, and
authenticated ingestion of provider-neutral engineering events.

## Run the service

Install the pinned dependencies:

```bash
poetry install
```

Set the required environment variables:

```bash
export AUTOMATION_API_KEY="replace-with-a-long-random-service-key"
export PORT_CLIENT_ID="your-port-client-id"
export PORT_CLIENT_SECRET="your-port-client-secret"
export PORT_AUTOMATION_BLUEPRINT="engineeringAutomation"
export N8N_BASE_URL="https://n8n.example.com"
export N8N_API_KEY="your-n8n-api-key"
export WEBHOOK_SECRETS_JSON='{"github":"replace-with-a-long-random-source-secret"}'
```

Optional settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT_REGION` | `eu` | Port API region. Supported values are `eu` and `us`. |
| `PORT_BASE_URL` | Region URL | Port API override for development or testing. |
| `AUTOMATION_MAX_CONCURRENCY` | `5` | Maximum concurrent registrations in one reconciliation. |
| `WEBHOOK_MAX_AGE_SECONDS` | `300` | Oldest accepted signed timestamp. |
| `WEBHOOK_FUTURE_TOLERANCE_SECONDS` | `30` | Allowed provider clock skew into the future. |
| `WEBHOOK_RECEIPT_TTL_SECONDS` | `86400` | Source/id deduplication retention; it must be at least the maximum age. |
| `WEBHOOK_RECEIPT_DATABASE_PATH` | `.data/webhook-receipts.sqlite3` | Durable SQLite file used for source/id receipt claims. |

Start Uvicorn with the environment-backed application factory:

```bash
poetry run uvicorn engineering_automation.bootstrap.api:create_environment_app --factory
```

The default server address is `http://127.0.0.1:8000`.

## Explore the generated documentation

The service generates its API contract directly from the same typed schemas used at runtime:

- Swagger UI: [`/docs`](http://127.0.0.1:8000/docs)
- ReDoc: [`/redoc`](http://127.0.0.1:8000/redoc)
- OpenAPI 3 schema: [`/openapi.json`](http://127.0.0.1:8000/openapi.json)

Swagger UI includes a reusable `AutomationApiKey` security scheme. Select **Authorize** and enter
the configured service API key before trying an automation operation.

The schema also documents `WebhookSignature` for inbound event requests. Webhooks use a distinct
source-specific HMAC contract and do not accept the automation service API key.

## Persist webhook receipts

The environment-backed application stores authenticated webhook receipt claims in SQLite before
dispatching an event. The default `.data/webhook-receipts.sqlite3` path is created on first use,
including its parent directory. Set `WEBHOOK_RECEIPT_DATABASE_PATH` to a persistent filesystem
location in production.

Claims use the normalized source and provider webhook identifier as a composite key. SQLite
transactions allow concurrent workers sharing the same database file to choose exactly one claim
winner. A successful claim remains after a process restart until `WEBHOOK_RECEIPT_TTL_SECONDS`
expires. Failed routed processing releases its claim so the provider can retry safely, and later
claims remove expired rows.

All workers using this adapter must share the same database file. Deployments whose replicas have
independent filesystems should provide another implementation of the `WebhookReceiptStore` port
backed by shared infrastructure. An in-memory SQLite path is rejected because it cannot provide
restart durability.

## Authenticate automation requests

Send the configured key in the `X-API-Key` header:

```text
X-API-Key: replace-with-a-long-random-service-key
```

The health and documentation endpoints do not require authentication. Registration and
reconciliation endpoints return `401 Unauthorized` when the header is missing or incorrect.

## Check service health

`GET /health` is a liveness check. It does not call Port or n8n.

```bash
curl --silent http://127.0.0.1:8000/health
```

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

## Register one automation

`POST /v1/automations/register` aligns one n8n workflow with the requested active state and then
upserts its Port catalog entity. If Port registration fails after n8n changes, the use case attempts
to restore the original workflow state.

```bash
curl --request POST \
  --url http://127.0.0.1:8000/v1/automations/register \
  --header "Content-Type: application/json" \
  --header "X-API-Key: ${AUTOMATION_API_KEY}" \
  --data '{
    "identifier": "deploy-payments",
    "title": "Deploy payments service",
    "workflowId": "n8n-workflow-42",
    "active": true,
    "properties": {
      "owner": "platform",
      "environment": "production"
    },
    "relations": {
      "service": "payments"
    }
  }'
```

Successful response:

```json
{
  "automationId": "deploy-payments",
  "workflow": {
    "identifier": "n8n-workflow-42",
    "name": "Deploy payments service",
    "active": true
  },
  "catalog": {
    "identifier": "deploy-payments"
  },
  "workflowStateChanged": true
}
```

`workflowStateChanged` is `false` when the n8n workflow already had the desired state.

## Reconcile multiple automations

`POST /v1/automations/reconcile` accepts between 1 and 100 definitions. Work is bounded by
`AUTOMATION_MAX_CONCURRENCY`, and outcomes retain request order.

```bash
curl --request POST \
  --url http://127.0.0.1:8000/v1/automations/reconcile \
  --header "Content-Type: application/json" \
  --header "X-API-Key: ${AUTOMATION_API_KEY}" \
  --data '{
    "automations": [
      {
        "identifier": "deploy-payments",
        "title": "Deploy payments service",
        "workflowId": "n8n-workflow-42",
        "active": true
      },
      {
        "identifier": "archive-preview",
        "title": "Archive preview environment",
        "workflowId": "n8n-workflow-99",
        "active": false
      }
    ]
  }'
```

A batch can return `200 OK` with both successful and failed outcomes. One provider failure does not
cancel unrelated automations:

```json
{
  "succeeded": 1,
  "failed": 1,
  "outcomes": [
    {
      "automationId": "deploy-payments",
      "state": "succeeded",
      "registration": {
        "automationId": "deploy-payments",
        "workflow": {
          "identifier": "n8n-workflow-42",
          "name": "Deploy payments service",
          "active": true
        },
        "catalog": {
          "identifier": "deploy-payments"
        },
        "workflowStateChanged": false
      },
      "error": null
    },
    {
      "automationId": "archive-preview",
      "state": "failed",
      "registration": null,
      "error": "RuntimeError: Port unavailable"
    }
  ]
}
```

Duplicate automation identifiers are rejected before any provider operation begins.

## Ingest a signed engineering event

`POST /v1/webhooks/events/{source}` authenticates the exact request bytes before decoding them. Send
these headers:

| Header | Contract |
| --- | --- |
| `X-Webhook-Id` | Non-empty provider delivery identifier, up to 256 characters. |
| `X-Webhook-Timestamp` | Non-negative Unix timestamp in seconds. |
| `X-Webhook-Signature` | Lowercase `sha256=` followed by the HMAC-SHA256 hex digest. |

The signed bytes are `<timestamp>.<raw request body>`. The body sent over HTTP must be byte-for-byte
identical to the body used to calculate the signature:

```python
import hashlib
import hmac


def webhook_signature(secret: str, timestamp: int, body: bytes) -> str:
    signed = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"sha256={digest}"
```

The strict camel-case event body is:

```json
{
  "eventId": "delivery-request-42",
  "eventType": "automation.registration.requested",
  "subject": "deploy-payments",
  "occurredAt": "2030-01-01T00:00:00Z",
  "payload": {
    "identifier": "deploy-payments",
    "title": "Deploy payments service",
    "workflowId": "n8n-workflow-42",
    "active": true,
    "properties": {
      "owner": "platform"
    },
    "relations": {
      "service": "payments"
    }
  },
  "labels": {
    "environment": "production"
  }
}
```

The built-in `automation.registration.requested` route invokes the same compensated registration
workflow as `POST /v1/automations/register`. Other valid event types are accepted with no matched
destinations until an operator wires additional routing rules.

A newly processed webhook returns `202 Accepted`:

```json
{
  "webhookId": "provider-delivery-42",
  "eventId": "delivery-request-42",
  "state": "accepted",
  "matchedRuleIds": [
    "register-requested-automation"
  ],
  "destinations": [
    {
      "destination": "automation.register",
      "status": "succeeded",
      "durationMs": 12,
      "output": {
        "automationId": "deploy-payments",
        "workflowId": "n8n-workflow-42",
        "catalogId": "deploy-payments",
        "workflowStateChanged": true
      },
      "error": null
    }
  ]
}
```

The same source and webhook identifier returns `200 OK` with `state` set to `duplicate`, empty rule
and destination lists, and no second provider call. A failed routed destination returns `502` and
releases the receipt so the provider can retry. The default receipt store is process-local; deploy a
shared `WebhookReceiptStore` adapter before running multiple workers or replicas.

## Handle errors

| Status | Code | Meaning |
| --- | --- | --- |
| `401` | `unauthorized` | `X-API-Key` is missing or incorrect. |
| `409` | `conflicting_definitions` | A reconciliation contains duplicate identifiers. |
| `422` | FastAPI validation details | The JSON shape, type, length, or field name is invalid. |
| `502` | `registration_failed` | A single registration could not complete. |
| `502` | `reconciliation_failed` | The reconciliation coordinator could not run. |
| `401` | `invalid_webhook` | The source, timestamp window, or HMAC signature is invalid. |
| `422` | `invalid_webhook_payload` | Authenticated bytes do not match the event contract. |
| `502` | `webhook_processing_failed` | A routed destination failed; the delivery may be retried. |
| `503` | `webhook_ingestion_unavailable` | The application was created without an ingestion adapter. |

Upstream details are logged internally but are not returned by single-registration `502` responses.
Batch item errors appear in their corresponding audit outcome.
