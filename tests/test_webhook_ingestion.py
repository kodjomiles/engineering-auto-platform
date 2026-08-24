from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from engineering_automation.application.use_cases.ingest_webhook import (
    IngestWebhook,
    WebhookAuthenticationError,
    WebhookProcessingError,
)
from engineering_automation.domain.inbound_webhooks import (
    WebhookIngestionRequest,
    WebhookIngestionState,
)
from engineering_automation.domain.webhook_signing import sign
from engineering_automation.events import (
    DestinationResult,
    DispatchReport,
    DispatchStatus,
    EngineeringEvent,
)
from engineering_automation.infrastructure.persistence.memory_webhook_receipts import (
    InMemoryWebhookReceiptStore,
)
from engineering_automation.infrastructure.security.webhook_secrets import (
    StaticWebhookSecretProvider,
)

NOW = 2_000_000_000
BODY = b'{"eventId":"event-1"}'


def event(*, source: str = "github", event_id: str = "event-1") -> EngineeringEvent:
    return EngineeringEvent(
        event_id=event_id,
        source=source,
        event_type="deployment.completed",
        subject="payments",
        occurred_at=datetime(2033, 5, 18, tzinfo=UTC),
    )


def successful_report(event_id: str = "event-1") -> DispatchReport:
    return DispatchReport(
        event_id,
        ("notify",),
        (
            DestinationResult(
                "notifications",
                DispatchStatus.SUCCEEDED,
                4,
                {"delivered": 2},
            ),
        ),
    )


class RecordingProcessor:
    def __init__(self, report: DispatchReport | None = None) -> None:
        self.events: list[EngineeringEvent] = []
        self.report = report or successful_report()
        self.error: BaseException | None = None

    async def process(self, value: EngineeringEvent) -> DispatchReport:
        self.events.append(value)
        if self.error is not None:
            raise self.error
        return self.report


class EventDecoder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self.error: Exception | None = None

    def decode(self, source: str, raw_body: bytes) -> EngineeringEvent:
        self.calls.append((source, raw_body))
        if self.error is not None:
            raise self.error
        return event(source=source)


def ingestor(processor: RecordingProcessor) -> IngestWebhook:
    instant = datetime.fromtimestamp(NOW, tz=UTC)
    return IngestWebhook(
        StaticWebhookSecretProvider({"github": "github-secret", "gitlab": "gitlab-secret"}),
        InMemoryWebhookReceiptStore(clock=lambda: instant),
        EventDecoder(),
        processor,
        max_age_seconds=300,
        future_tolerance_seconds=30,
        receipt_ttl_seconds=3600,
        clock=lambda: NOW,
    )


def request_for(
    *,
    source: str = "github",
    webhook_id: str = "delivery-1",
    timestamp: int = NOW,
    secret: str = "github-secret",
    signature: str | None = None,
) -> WebhookIngestionRequest:
    return WebhookIngestionRequest(
        webhook_id,
        timestamp,
        signature or sign(secret.encode(), timestamp, BODY),
        BODY,
        source,
    )


def test_valid_webhook_is_processed_once_and_duplicates_are_acknowledged() -> None:
    processor = RecordingProcessor()
    use_case = ingestor(processor)

    first = asyncio.run(use_case.execute(request_for()))
    duplicate = asyncio.run(use_case.execute(request_for()))

    assert first.state is WebhookIngestionState.ACCEPTED
    assert first.dispatch == successful_report()
    assert duplicate.state is WebhookIngestionState.DUPLICATE
    assert duplicate.dispatch is None
    assert [item.event_id for item in processor.events] == ["event-1"]


def test_webhook_identifier_is_scoped_by_normalized_source() -> None:
    processor = RecordingProcessor()
    use_case = ingestor(processor)
    github = request_for()
    gitlab = request_for(source="gitlab", secret="gitlab-secret")

    github_result = asyncio.run(use_case.execute(github))
    gitlab_result = asyncio.run(use_case.execute(gitlab))

    assert github_result.state is WebhookIngestionState.ACCEPTED
    assert gitlab_result.state is WebhookIngestionState.ACCEPTED
    assert [item.source for item in processor.events] == ["github", "gitlab"]


@pytest.mark.parametrize(
    "value",
    [
        request_for(timestamp=NOW - 301),
        request_for(timestamp=NOW + 31),
        request_for(signature="sha256=incorrect"),
        request_for(source="unknown"),
    ],
)
def test_invalid_source_timestamp_or_signature_never_reaches_processor(
    value: WebhookIngestionRequest,
) -> None:
    processor = RecordingProcessor()

    with pytest.raises(WebhookAuthenticationError):
        asyncio.run(ingestor(processor).execute(value))

    assert processor.events == []


def test_boundary_timestamps_are_accepted() -> None:
    processor = RecordingProcessor()
    use_case = ingestor(processor)

    oldest = asyncio.run(use_case.execute(request_for(webhook_id="oldest", timestamp=NOW - 300)))
    furthest_future = asyncio.run(
        use_case.execute(request_for(webhook_id="future", timestamp=NOW + 30))
    )

    assert oldest.state is WebhookIngestionState.ACCEPTED
    assert furthest_future.state is WebhookIngestionState.ACCEPTED


def test_failed_destination_releases_receipt_for_provider_retry() -> None:
    failed_report = DispatchReport(
        "event-1",
        ("notify",),
        (
            DestinationResult(
                "notifications",
                DispatchStatus.FAILED,
                1,
                error="RuntimeError: provider unavailable",
            ),
        ),
    )
    processor = RecordingProcessor(failed_report)
    use_case = ingestor(processor)

    with pytest.raises(WebhookProcessingError) as first:
        asyncio.run(use_case.execute(request_for()))
    with pytest.raises(WebhookProcessingError):
        asyncio.run(use_case.execute(request_for()))

    assert first.value.report == failed_report
    assert len(processor.events) == 2


def test_unexpected_processing_error_releases_receipt() -> None:
    processor = RecordingProcessor()
    processor.error = RuntimeError("temporary failure")
    use_case = ingestor(processor)

    with pytest.raises(RuntimeError, match="temporary failure"):
        asyncio.run(use_case.execute(request_for()))
    processor.error = None
    result = asyncio.run(use_case.execute(request_for()))

    assert result.state is WebhookIngestionState.ACCEPTED
    assert len(processor.events) == 2


def test_concurrent_delivery_claim_is_atomic() -> None:
    async def exercise() -> tuple[WebhookIngestionState, WebhookIngestionState]:
        started = asyncio.Event()
        release = asyncio.Event()

        class GatedProcessor:
            async def process(self, _: EngineeringEvent) -> DispatchReport:
                started.set()
                await release.wait()
                return successful_report()

        instant = datetime.fromtimestamp(NOW, tz=UTC)
        use_case = IngestWebhook(
            StaticWebhookSecretProvider({"github": "github-secret"}),
            InMemoryWebhookReceiptStore(clock=lambda: instant),
            EventDecoder(),
            GatedProcessor(),
            clock=lambda: NOW,
        )
        first_task = asyncio.create_task(use_case.execute(request_for()))
        await started.wait()
        duplicate = await use_case.execute(request_for())
        release.set()
        first = await first_task
        return first.state, duplicate.state

    assert asyncio.run(exercise()) == (
        WebhookIngestionState.ACCEPTED,
        WebhookIngestionState.DUPLICATE,
    )


def test_ingestor_rejects_invalid_security_windows() -> None:
    dependencies = (
        StaticWebhookSecretProvider({"github": "secret"}),
        InMemoryWebhookReceiptStore(),
        EventDecoder(),
        RecordingProcessor(),
    )
    with pytest.raises(ValueError, match="max_age_seconds"):
        IngestWebhook(*dependencies, max_age_seconds=0)
    with pytest.raises(ValueError, match="future_tolerance_seconds"):
        IngestWebhook(*dependencies, future_tolerance_seconds=-1)
    with pytest.raises(ValueError, match="receipt_ttl_seconds"):
        IngestWebhook(
            *dependencies,
            max_age_seconds=300,
            receipt_ttl_seconds=299,
        )
