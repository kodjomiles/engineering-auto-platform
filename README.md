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

## Development

The project requires Python 3.12 or newer and Poetry.

```bash
poetry install
poetry run pytest
poetry run ruff format --check .
poetry run ruff check .
poetry run mypy src tests
```

## Package layout

```text
src/engineering_automation/
└── webhooks/
    ├── delivery.py   # retry orchestration and delivery reporting
    ├── models.py     # immutable domain contracts
    ├── signing.py    # canonical encoding and HMAC signatures
    └── transport.py  # protocol implemented by future HTTP adapters
```

Provider-specific integrations will live outside the core. A Port adapter and
an n8n adapter can therefore share the same delivery, signing, and retry rules
without duplicating them.
