"""Reconcile a collection of automation definitions with bounded concurrency."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from engineering_automation.application.ports.automation import AutomationRegistrar
from engineering_automation.domain.automation import (
    AutomationDefinition,
    AutomationReconciliation,
    AutomationReconciliationReport,
    ReconciliationState,
)


class ReconcileAutomations:
    """Run independent registrations and retain a result for every definition."""

    def __init__(self, registrar: AutomationRegistrar, *, max_concurrency: int = 5) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._registrar = registrar
        self._max_concurrency = max_concurrency

    async def execute(
        self,
        definitions: Iterable[AutomationDefinition],
    ) -> AutomationReconciliationReport:
        desired = tuple(definitions)
        self._reject_duplicates(desired)
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def reconcile(
            definition: AutomationDefinition,
        ) -> AutomationReconciliation:
            async with semaphore:
                try:
                    registration = await self._registrar.execute(definition)
                    return AutomationReconciliation(
                        automation_id=definition.identifier,
                        state=ReconciliationState.SUCCEEDED,
                        registration=registration,
                    )
                except Exception as error:
                    return AutomationReconciliation(
                        automation_id=definition.identifier,
                        state=ReconciliationState.FAILED,
                        error=f"{type(error).__name__}: {error}",
                    )

        outcomes = await asyncio.gather(*(reconcile(item) for item in desired))
        return AutomationReconciliationReport(tuple(outcomes))

    @staticmethod
    def _reject_duplicates(definitions: tuple[AutomationDefinition, ...]) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for definition in definitions:
            if definition.identifier in seen:
                duplicates.add(definition.identifier)
            seen.add(definition.identifier)
        if duplicates:
            identifiers = ", ".join(sorted(duplicates))
            raise ValueError(f"duplicate automation identifiers: {identifiers}")
