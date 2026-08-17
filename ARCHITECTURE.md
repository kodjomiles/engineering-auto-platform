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

## Register an automation

`RegisterAutomation` demonstrates the dependency rule across both providers:

```text
AutomationDefinition
        │
        v
RegisterAutomation ──> WorkflowManager port ──> N8nWorkflowManager ──> N8nClient
        │
        └────────────> AutomationCatalog port ─> PortAutomationCatalog ─> PortClient
```

The use case reads the current workflow state before making changes. It updates n8n only when the
desired activation state differs, then upserts the Port catalog entity. If catalog registration
fails after changing the workflow, it attempts to restore the original state. A failed restoration
raises `AutomationRollbackError`, which retains both the registration and rollback failures for
diagnosis. Gateway identity and state checks prevent an adapter from silently reporting success for
the wrong resource.

This orchestration belongs in the application layer because the ordering and compensation are
business workflow rules. Provider payload translation stays in `infrastructure/adapters/`, and
`bootstrap/automation.py` performs the concrete wiring.

## Reconcile automation definitions

`ReconcileAutomations` composes the single-item use case rather than bypassing it:

```text
desired definitions ─> ReconcileAutomations ─> AutomationRegistrar port
                              │                          │
                              │ bounded concurrency      └─> RegisterAutomation
                              │ failure isolation                    │
                              v                                      v
                 AutomationReconciliationReport             Port and n8n ports
```

The coordinator rejects duplicate automation identifiers before it performs any external write.
Independent definitions run concurrently up to a configured limit, while `asyncio.gather` retains
their input order in the final immutable report. An error for one definition becomes a failed
outcome rather than cancelling unrelated work. `RegisterAutomation` still owns provider ordering,
gateway validation, and compensation for every individual item.

This separation keeps batch execution policy independent from provider details and allows another
single-registration implementation to be supplied through `AutomationRegistrar` without changing
the reconciliation use case.

## Compatibility packages

The existing `notifications.*` and `webhooks.*` modules preserve established imports. They contain
re-exports or thin composition façades only; business rules live in `domain/` and `application/`.
This permits incremental migration without maintaining duplicate implementations.
