"""Small, dependency-free read API over the immutable projection snapshot.

The object is deliberately transport-neutral.  A local HTTP adapter can call
``handle`` from ``BaseHTTPRequestHandler`` or a future ASGI adapter; this module
never opens a socket and never exposes a mutation endpoint.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.identity import ProjectId, RunId
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.projection.models import ProjectionSnapshot


class ReadApiError(RuntimeError):
    """Base class for stable local read API errors."""


class _WireModel(Protocol):
    def to_wire(self) -> WirePayload: ...


@dataclass(frozen=True, slots=True)
class ReadApiResponse:
    """Transport-neutral response suitable for JSON or HTTP adapters."""

    status_code: int
    payload: dict[str, object]

    def to_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ReadOnlyProjectionApi:
    """GET-only API for Task, Run, Agent and Lease projections.

    The constructor receives a snapshot rather than a mutable store.  Rebuild a
    new snapshot when durable facts change; an existing API object therefore stays
    safe to share with dashboard readers and cannot accidentally write a verdict.
    """

    _PAGE_SIZE_DEFAULT: Final = 50
    _PAGE_SIZE_MAX: Final = 100

    def __init__(self, snapshot: ProjectionSnapshot) -> None:
        self._snapshot = snapshot

    @property
    def snapshot(self) -> ProjectionSnapshot:
        """Return the immutable snapshot used by this API instance."""
        return self._snapshot

    def list_tasks(
        self,
        *,
        project_id: ProjectId | str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = _PAGE_SIZE_DEFAULT,
    ) -> ReadApiResponse:
        items = tuple(
            item
            for item in self._snapshot.tasks
            if (project_id is None or item.project_id == project_id)
            and (status is None or item.status.value == status)
        )
        return _page_response("tasks", items, page=page, page_size=page_size)

    def get_task(self, task_id: TaskId | str) -> ReadApiResponse:
        return self._get_one(
            "task", (item for item in self._snapshot.tasks if item.task_id == task_id)
        )

    def list_runs(
        self,
        *,
        project_id: ProjectId | str | None = None,
        task_id: TaskId | str | None = None,
        role: AgentRole | str | None = None,
        candidate_revision: str | None = None,
        page: int = 1,
        page_size: int = _PAGE_SIZE_DEFAULT,
    ) -> ReadApiResponse:
        role_value = role.value if isinstance(role, AgentRole) else role
        items = tuple(
            item
            for item in self._snapshot.runs
            if (project_id is None or item.project_id == project_id)
            and (task_id is None or item.task_id == task_id)
            and (role_value is None or (item.role is not None and item.role.value == role_value))
            and (candidate_revision is None or item.source_revision == candidate_revision)
        )
        return _page_response("runs", items, page=page, page_size=page_size)

    def get_run(self, run_id: RunId | str) -> ReadApiResponse:
        return self._get_one("run", (item for item in self._snapshot.runs if item.run_id == run_id))

    def list_agents(self, *, page: int = 1, page_size: int = _PAGE_SIZE_DEFAULT) -> ReadApiResponse:
        return _page_response("agents", self._snapshot.agents, page=page, page_size=page_size)

    def list_leases(
        self,
        *,
        task_id: TaskId | str | None = None,
        agent_id: str | None = None,
        page: int = 1,
        page_size: int = _PAGE_SIZE_DEFAULT,
    ) -> ReadApiResponse:
        items = tuple(
            item
            for item in self._snapshot.leases
            if (task_id is None or item.task_id == task_id)
            and (agent_id is None or item.agent_id == agent_id)
        )
        return _page_response("leases", items, page=page, page_size=page_size)

    def handle(
        self,
        method: str,
        path: str,
        query: Mapping[str, str | Sequence[str]] | None = None,
    ) -> ReadApiResponse:
        """Route one local request; only ``GET`` is accepted."""
        if method.upper() != "GET":
            return ReadApiResponse(405, {"error": "METHOD_NOT_ALLOWED", "read_only": True})
        params = _first_values(query or {})
        clean_path = path.split("?", 1)[0].rstrip("/") or "/"
        parts = tuple(part for part in clean_path.split("/") if part)
        try:
            if parts in {("api", "v1", "tasks"), ("tasks",)}:
                return self.list_tasks(
                    project_id=params.get("project_id"),
                    status=params.get("status"),
                    page=_int_param(params, "page", 1),
                    page_size=_int_param(params, "page_size", self._PAGE_SIZE_DEFAULT),
                )
            if len(parts) == 4 and parts[:3] == ("api", "v1", "tasks"):
                return self.get_task(parts[3])
            if parts in {("api", "v1", "runs"), ("runs",)}:
                return self.list_runs(
                    project_id=params.get("project_id"),
                    task_id=params.get("task_id"),
                    role=params.get("role"),
                    candidate_revision=params.get("candidate_revision"),
                    page=_int_param(params, "page", 1),
                    page_size=_int_param(params, "page_size", self._PAGE_SIZE_DEFAULT),
                )
            if len(parts) == 4 and parts[:3] == ("api", "v1", "runs"):
                return self.get_run(parts[3])
            if parts in {("api", "v1", "agents"), ("agents",)}:
                return self.list_agents(
                    page=_int_param(params, "page", 1),
                    page_size=_int_param(params, "page_size", self._PAGE_SIZE_DEFAULT),
                )
            if parts in {("api", "v1", "leases"), ("leases",)}:
                return self.list_leases(
                    task_id=params.get("task_id"),
                    agent_id=params.get("agent_id"),
                    page=_int_param(params, "page", 1),
                    page_size=_int_param(params, "page_size", self._PAGE_SIZE_DEFAULT),
                )
        except ValueError as error:
            return ReadApiResponse(400, {"error": "INVALID_QUERY", "message": str(error)})
        return ReadApiResponse(404, {"error": "NOT_FOUND", "path": clean_path})

    @staticmethod
    def _get_one(kind: str, values: Iterable[_WireModel]) -> ReadApiResponse:
        item = next(iter(values), None)
        if item is None:
            return ReadApiResponse(404, {"error": "NOT_FOUND", "resource": kind})
        return ReadApiResponse(
            200, {"schema_version": "v0.1", "resource": kind, "item": item.to_wire()}
        )


# Short name retained for callers that do not need to distinguish transport.
ReadApi = ReadOnlyProjectionApi


def _page_response(
    resource: str,
    values: Sequence[_WireModel],
    *,
    page: int,
    page_size: int,
) -> ReadApiResponse:
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1 or page_size > ReadOnlyProjectionApi._PAGE_SIZE_MAX:
        raise ValueError(f"page_size must be between 1 and {ReadOnlyProjectionApi._PAGE_SIZE_MAX}")
    start = (page - 1) * page_size
    items = [value.to_wire() for value in values[start : start + page_size]]
    return ReadApiResponse(
        200,
        {
            "schema_version": "v0.1",
            "resource": resource,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": len(values),
        },
    )


def _first_values(query: Mapping[str, str | Sequence[str]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in query.items():
        if isinstance(value, str):
            values[key] = value
        elif value:
            values[key] = str(value[0])
    return values


def _int_param(values: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(values.get(key, str(default)))
    except ValueError as error:
        raise ValueError(f"{key} must be an integer") from error


__all__ = ["ReadApi", "ReadApiError", "ReadApiResponse", "ReadOnlyProjectionApi"]
