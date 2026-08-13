"""Notification entities and value objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any

from engineering_automation.domain.values import deep_freeze


class NotificationPriority(IntEnum):
    """Comparable notification urgency levels."""

    LOW = 10
    NORMAL = 20
    HIGH = 30
    CRITICAL = 40


class DeliveryMode(StrEnum):
    """How eligible contact points are attempted for each recipient."""

    FAN_OUT = "fan_out"
    FIRST_SUCCESS = "first_success"


class DeliveryState(StrEnum):
    """Observable outcome of one contact-point decision or invocation."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    MISSING_PROVIDER = "missing_provider"


@dataclass(frozen=True, slots=True)
class ContactPoint:
    """One address reachable through a named provider channel."""

    channel: str
    address: str
    enabled: bool = True

    def __post_init__(self) -> None:
        channel = self.channel.strip().lower()
        address = self.address.strip()
        if not channel:
            raise ValueError("contact channel cannot be empty")
        if not address:
            raise ValueError("contact address cannot be empty")
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "address", address)


@dataclass(frozen=True, slots=True)
class RecipientPreferences:
    """Ordered contact points and suppression rules for one recipient."""

    recipient_id: str
    contact_points: tuple[ContactPoint, ...]
    minimum_priority: NotificationPriority = NotificationPriority.LOW
    muted_topics: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        recipient_id = self.recipient_id.strip()
        if not recipient_id:
            raise ValueError("recipient_id cannot be empty")
        if not self.contact_points:
            raise ValueError("recipient requires at least one contact point")
        identities = [(point.channel, point.address) for point in self.contact_points]
        if len(set(identities)) != len(identities):
            raise ValueError("recipient contact points must be unique")
        topics = frozenset(topic.strip() for topic in self.muted_topics if topic.strip())
        object.__setattr__(self, "recipient_id", recipient_id)
        object.__setattr__(self, "muted_topics", topics)


@dataclass(frozen=True, slots=True)
class Notification:
    """Provider-neutral message ready for policy evaluation."""

    notification_id: str
    topic: str
    subject: str
    body: str
    priority: NotificationPriority
    occurred_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)
    deduplication_key: str | None = None

    def __post_init__(self) -> None:
        for name in ("notification_id", "topic", "subject", "body"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be empty")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.deduplication_key is not None:
            key = self.deduplication_key.strip()
            if not key:
                raise ValueError("deduplication_key cannot be empty")
            object.__setattr__(self, "deduplication_key", key)
        object.__setattr__(self, "metadata", deep_freeze(self.metadata))


@dataclass(frozen=True, slots=True)
class NotificationPolicy:
    """Delivery strategy and resource limits for one publish operation."""

    mode: DeliveryMode = DeliveryMode.FAN_OUT
    max_concurrency: int = 10
    deduplication_window_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if self.deduplication_window_seconds < 0:
            raise ValueError("deduplication_window_seconds cannot be negative")


@dataclass(frozen=True, slots=True)
class NotificationAttempt:
    """Audit record for one contact-point decision or provider call."""

    recipient_id: str
    channel: str
    address: str
    state: DeliveryState
    duration_ms: int
    output: Mapping[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        for name in ("recipient_id", "channel", "address"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be empty")
        if self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")
        if self.output is not None:
            object.__setattr__(self, "output", deep_freeze(self.output))


@dataclass(frozen=True, slots=True)
class NotificationReport:
    """Final immutable report for a notification publish operation."""

    notification_id: str
    deduplicated: bool
    attempts: tuple[NotificationAttempt, ...]

    @property
    def delivered(self) -> bool:
        return any(attempt.state is DeliveryState.SUCCEEDED for attempt in self.attempts)

    @property
    def has_failures(self) -> bool:
        return any(
            attempt.state in {DeliveryState.FAILED, DeliveryState.MISSING_PROVIDER}
            for attempt in self.attempts
        )
