from __future__ import annotations

import pytest

from engineering_automation.n8n import Execution, N8nApiError, N8nResponseError, Workflow


def test_workflow_parses_object_and_string_tags() -> None:
    workflow = Workflow.from_payload(
        {
            "id": "workflow-1",
            "name": "Deploy service",
            "active": True,
            "tags": [{"id": "tag-1", "name": "production"}, "platform"],
        }
    )
    assert workflow == Workflow("workflow-1", "Deploy service", True, ("production", "platform"))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"id": 1, "name": "Deploy", "active": True},
        {"id": "1", "name": "", "active": True},
        {"id": "1", "name": "Deploy", "active": "yes"},
        {"id": "1", "name": "Deploy", "active": True, "tags": "production"},
        {"id": "1", "name": "Deploy", "active": True, "tags": [{}]},
    ],
)
def test_workflow_rejects_malformed_payload(payload: dict[str, object]) -> None:
    with pytest.raises(N8nResponseError):
        Workflow.from_payload(payload)


def test_execution_parses_stable_fields() -> None:
    execution = Execution.from_payload(
        {"id": "42", "workflowId": "workflow-1", "status": "success", "finished": True}
    )
    assert execution == Execution("42", "workflow-1", "success", True)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"id": "1", "workflowId": 2, "status": "success", "finished": True},
        {"id": "1", "workflowId": "2", "status": "", "finished": True},
        {"id": "1", "workflowId": "2", "status": "success", "finished": 1},
    ],
)
def test_execution_rejects_malformed_payload(payload: dict[str, object]) -> None:
    with pytest.raises(N8nResponseError):
        Execution.from_payload(payload)


def test_api_error_formats_status_and_message() -> None:
    error = N8nApiError(403, "forbidden", request_id="request-1")
    assert str(error) == "n8n API returned HTTP 403: forbidden"
