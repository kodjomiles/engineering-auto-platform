"""Immutable n8n workflow and execution response models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from engineering_automation.n8n.errors import N8nResponseError


def _required_string(payload: Mapping[str, Any], field: str, resource: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise N8nResponseError(f"n8n {resource} response has invalid {field}")
    return value


@dataclass(frozen=True, slots=True)
class Workflow:
    """Stable workflow fields returned by the n8n public API."""

    identifier: str
    name: str
    active: bool
    tags: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Workflow:
        identifier = _required_string(payload, "id", "workflow")
        name = _required_string(payload, "name", "workflow")
        active = payload.get("active")
        if not isinstance(active, bool):
            raise N8nResponseError("n8n workflow response has invalid active status")

        raw_tags = payload.get("tags", [])
        if not isinstance(raw_tags, list):
            raise N8nResponseError("n8n workflow response has invalid tags")
        tags: list[str] = []
        for raw_tag in raw_tags:
            if isinstance(raw_tag, str):
                tag = raw_tag
            elif isinstance(raw_tag, dict) and isinstance(raw_tag.get("name"), str):
                tag = raw_tag["name"]
            else:
                raise N8nResponseError("n8n workflow response contains an invalid tag")
            if tag:
                tags.append(tag)
        return cls(identifier=identifier, name=name, active=active, tags=tuple(tags))


@dataclass(frozen=True, slots=True)
class WorkflowPage:
    """One cursor-based page returned by the workflows endpoint."""

    workflows: tuple[Workflow, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class Execution:
    """Stable execution fields returned by the n8n public API."""

    identifier: str
    workflow_id: str
    status: str
    finished: bool

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Execution:
        identifier = _required_string(payload, "id", "execution")
        workflow_id = _required_string(payload, "workflowId", "execution")
        status = _required_string(payload, "status", "execution")
        finished = payload.get("finished")
        if not isinstance(finished, bool):
            raise N8nResponseError("n8n execution response has invalid finished status")
        return cls(identifier, workflow_id, status, finished)
