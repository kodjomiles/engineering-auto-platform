"""Compatibility exports for deduplication ports and adapters."""

from engineering_automation.application.ports.notifications import DeduplicationStore
from engineering_automation.infrastructure.persistence.memory_deduplication import (
    InMemoryDeduplicationStore,
)

__all__ = ["DeduplicationStore", "InMemoryDeduplicationStore"]
