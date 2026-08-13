# Architecture

The platform follows Clean Architecture dependency direction and uses provider-specific adapters
behind application ports.

## Dependency rule

Source dependencies point inward:

```text
bootstrap ─┬─> interfaces ─> application ─> domain
           └─> infrastructure ─────────────> application

provider adapters (Port and n8n) ─────────> application/domain
```

- `domain/` contains immutable entities and pure business policy. It does not import application,
  infrastructure, interface, or provider packages.
- `application/ports/` defines abstract inbound and outbound contracts.
- `application/use_cases/` coordinates business operations through those ports.
- `application/services/` performs reusable application-level work with one responsibility.
- `infrastructure/` implements persistence and HTTP ports.
- `interfaces/` translates events or other external inputs into use-case requests.
- `bootstrap/` is the only place that selects and wires default concrete adapters.

Architecture tests in `tests/test_architecture.py` enforce the inward dependency rule.

## Provider clients

`PortClient` and `N8nClient` remain separate intentionally. They are infrastructure adapters for
different external APIs with different authentication, resources, pagination, and failure formats.
A single universal client would couple unrelated providers and violate the Interface Segregation
and Single Responsibility principles.

Application code must not construct or import those clients directly. A composition root supplies
the required adapter through an application port when a use case needs provider behavior.

## Compatibility packages

The existing `notifications.*` and `webhooks.*` modules preserve established imports. They contain
re-exports or thin composition façades only; business rules live in `domain/` and `application/`.
This permits incremental migration without maintaining duplicate implementations.
