# Engineering automation platform

A typed Python platform for routing engineering events to systems such as Port,
n8n, and notification providers.

The project is being developed in small, production-oriented increments. The
first increment provides a framework-independent webhook delivery core with:

- canonical JSON payload encoding;
- HMAC-SHA256 request signing;
- idempotency and timestamp headers;
- bounded exponential retry delays;
- retryable and terminal HTTP-status handling;
- immutable delivery reports for auditability; and
- an injectable transport boundary that keeps tests offline and deterministic.

The second increment adds an async HTTP transport and an authenticated Port API
client with region-aware endpoints, token caching, catalog entity upserts,
cursor-safe entity search, and self-service action execution.

The third increment adds a provider-neutral engineering event engine with:

- deeply immutable event and dispatch contracts;
- nested `all` and `any` condition groups over event fields and payloads;
- equality, membership, text, existence, and ordered comparisons;
- deterministic priority-based routing and destination deduplication;
- bounded concurrent delivery to registered async handlers;
- failure isolation for independent destinations; and
- ordered, audit-ready dispatch reports.

## Development

The project requires Python 3.12 or newer and Poetry.

```bash
poetry install
poetry run pytest
poetry run ruff format --check .
poetry run ruff check .
poetry run mypy src tests
poetry build
```

The same quality gates run automatically for every pull request and every push
to `main`.

## Package layout

```text
src/engineering_automation/
├── events/
│   ├── conditions.py       # safe field resolution and condition evaluation
│   ├── dispatch.py         # bounded, failure-isolated handler execution
│   ├── models.py           # immutable event and routing contracts
│   └── router.py           # deterministic rule evaluation
├── port/                   # authenticated catalog and action operations
└── webhooks/
    ├── delivery.py         # retry orchestration and delivery reporting
    ├── httpx_transport.py  # production async HTTP transport
    ├── models.py           # immutable domain contracts
    ├── signing.py          # canonical encoding and HMAC signatures
    └── transport.py        # transport protocol
```

Provider-specific integrations live outside the event and webhook cores. Port,
n8n, and notification adapters can therefore share the same filtering,
routing, delivery, signing, and retry rules without duplicating them.
