"""Application-level orchestration failures."""

from __future__ import annotations

from dataclasses import dataclass


class GatewayContractError(RuntimeError):
    """An outbound gateway returned data for a different resource or state."""


@dataclass(eq=False)
class AutomationRollbackError(RuntimeError):
    """Registration failed and restoring the workflow state also failed."""

    registration_error: Exception
    rollback_error: Exception

    def __str__(self) -> str:
        return (
            "automation registration failed and workflow rollback failed: "
            f"registration={type(self.registration_error).__name__}: {self.registration_error}; "
            f"rollback={type(self.rollback_error).__name__}: {self.rollback_error}"
        )
