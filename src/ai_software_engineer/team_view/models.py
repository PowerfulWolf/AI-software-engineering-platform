"""Versioned read model, never a scheduling or verdict authority."""

from typing import Literal

from pydantic import AwareDatetime

from ai_software_engineer.domain.enums import AgentRole, TeamRole, WorkItemStatus
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.views import KnowledgeGapView
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


class DialogueAttachmentView(DomainModel):
    id: str
    name: str
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    source_bytes: int
    sha256: str


class DialogueTurnView(DomainModel):
    sequence: int
    speaker: Literal["user", "product"]
    text: str = ""
    attachments: tuple[DialogueAttachmentView, ...] = ()


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


class RoleQueueView(DomainModel):
    work_item_id: str
    role: AgentRole
    attempt: int
    status: WorkItemStatus
    agent_id: str | None = None
    heartbeat_at: AwareDatetime | None = None
    lease_expires_at: AwareDatetime | None = None
    lease_liveness: Literal["UNKNOWN", "LEASE_VALID", "LEASE_EXPIRED"] = "UNKNOWN"
    wait_reason: str | None = None


class TaskView(DomainModel):
    id: str
    project_id: str
    request_id: str
    work_kind: Literal["delivery", "candidate_verification", "remediation"] = "delivery"
    task_id: str | None = None
    source_delivery_id: str | None = None
    source_task_id: str | None = None
    plan_sha256: str | None = None
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
    candidate_branch: str | None = None
    role_queue: tuple[RoleQueueView, ...] = ()
    assignments: tuple[AssignmentView, ...] = ()
    timeline: tuple[TimelineEntry, ...] = ()
    runs: tuple[RunView, ...] = ()
    documents: tuple[DocumentView, ...] = ()


class RequestView(DomainModel):
    id: str
    project_id: str
    title: str
    stage: str
    scopes: tuple[ScopeView, ...]
    next_action: str
    blocker: str | None = None
    dialogue: tuple[DialogueTurnView, ...] = ()
    documents: tuple[DocumentView, ...] = ()
    checkpoint_sha256: str
    knowledge_gap: KnowledgeGapView | None = None
    design_recovery_available: bool = False


class AgentView(DomainModel):
    id: str
    name: str
    roles: tuple[TeamRole, ...]
    capabilities: tuple[str, ...]
    enabled: bool
    max_parallel_assignments: int
    execution_liveness: Literal["UNKNOWN"] = "UNKNOWN"
    assigned_delivery_ids: tuple[str, ...] = ()
    current_stage_delivery_ids: tuple[str, ...] = ()
    history_delivery_ids: tuple[str, ...] = ()


class ProjectView(DomainModel):
    id: str
    name: str
    repository_count: int = 0
    requirement_count: int = 0


class TeamSnapshot(DomainModel):
    schema_version: Literal["v0.2"] = "v0.2"
    as_of: AwareDatetime
    team_id: str
    team_name: str
    selected_project_id: str | None = None
    projects: tuple[ProjectView, ...] = ()
    agents: tuple[AgentView, ...] = ()
    requests: tuple[RequestView, ...] = ()
    tasks: tuple[TaskView, ...] = ()


class TeamReadError(RuntimeError):
    """Safe boundary error: never carry raw SQL, provider text or credentials."""
