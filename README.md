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

The fourth increment connects that engine to n8n with an API-key-authenticated
management client and a production webhook adapter. It supports cursor-safe
workflow discovery, workflow activation and deactivation, execution inspection
and deletion, signed event payloads, idempotency headers, and bounded retries.

The fifth increment adds provider-neutral notification orchestration with
recipient preferences, priority and topic suppression, fan-out and ordered
fallback delivery, atomic time-window deduplication, bounded concurrency,
failure isolation, and immutable audit reports.

The sixth increment proves the architecture across two external systems with a
provider-neutral automation-registration use case. It aligns a desired n8n
workflow activation state, records the automation in Port, validates every
gateway response, and restores the original workflow state if registration
fails. Port and n8n details remain isolated in infrastructure adapters.

The seventh increment adds batch automation reconciliation. It processes
desired definitions with configurable bounded concurrency, rejects duplicate
identifiers before performing writes, isolates failures between automations,
and returns an immutable report in the same order as the input. Each item
reuses the single-registration workflow and its compensation guarantees.

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
├── domain/                 # immutable entities and pure policy
├── application/
│   ├── ports/              # abstract dependency boundaries
│   ├── services/           # focused application services
│   └── use_cases/          # business operation orchestration
├── infrastructure/         # concrete provider, HTTP, and persistence adapters
├── interfaces/             # inbound event adapters
├── bootstrap/              # concrete dependency composition
├── port/                   # Port provider adapter
├── n8n/                    # n8n provider adapter
├── events/                 # event domain and compatibility API
├── notifications/          # compatibility exports and façade
└── webhooks/               # compatibility exports
```

Provider-specific integrations live outside the domain and application cores.
Port and n8n remain separate clients because their APIs and authentication are
different, while use cases depend only on narrow ports. See
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the dependency rules and rationale.
