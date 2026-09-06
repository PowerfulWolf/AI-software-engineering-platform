"""Versioned read model, never a scheduling or verdict authority."""

from typing import Literal

from pydantic import AwareDatetime

from ai_software_engineer.domain.enums import AgentRole, OrganizationRole
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.projection.models import TimelineEntry


class DocumentView(DomainModel):
    name: str
    source_uri: str
    sha256: str
    content: str = ""


class ScopeView(DomainModel):
    root: str
    selected_paths: tuple[str, ...]
    reference_only: bool = False
    delivery_id: str | None = None


class AssignmentView(DomainModel):
    agent_id: str
    role: AgentRole
    planned_provider: str
    planned_model: str
    current_stage: bool


class RunView(DomainModel):
    run_id: str
    role: AgentRole
    provider: str
    model: str
    route_index: int
    outcome: str
    error_code: str | None = None
    duration_ms: int
    completed_at: AwareDatetime
    source_uri: str
    sha256: str


class TaskView(DomainModel):
    id: str
    request_id: str
    task_id: str | None = None
    title: str
    scope: ScopeView
    status: str
    checkpoint_stage: str
    terminal: bool
    last_activity: AwareDatetime
    execution_liveness: Literal["UNKNOWN"] = "UNKNOWN"
    blocker: str | None = None
    next_action: str
    candidate_revision: str | None = None
    assignments: tuple[AssignmentView, ...] = ()
    timeline: tuple[TimelineEntry, ...] = ()
    runs: tuple[RunView, ...] = ()
    documents: tuple[DocumentView, ...] = ()


class RequestView(DomainModel):
    id: str
    title: str
    stage: str
    scopes: tuple[ScopeView, ...]
    next_action: str
    blocker: str | None = None
    documents: tuple[DocumentView, ...] = ()
    checkpoint_sha256: str


class AgentView(DomainModel):
    id: str
    name: str
    roles: tuple[OrganizationRole, ...]
    capabilities: tuple[str, ...]
    enabled: bool
    max_parallel_assignments: int
    execution_liveness: Literal["UNKNOWN"] = "UNKNOWN"
    assigned_delivery_ids: tuple[str, ...] = ()
    current_stage_delivery_ids: tuple[str, ...] = ()
    history_delivery_ids: tuple[str, ...] = ()


class TeamSnapshot(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    as_of: AwareDatetime
    company_id: str
    company_name: str
    agents: tuple[AgentView, ...] = ()
    requests: tuple[RequestView, ...] = ()
    tasks: tuple[TaskView, ...] = ()


class TeamReadError(RuntimeError):
    """Safe boundary error: never carry raw SQL, provider text or credentials."""
