"""Read production facts without constructing a mutation-capable application Host."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pymysql.cursors import DictCursor

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, model_route_root
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, TeamRole, WorkItemStatus
from ai_software_engineer.domain.workforce import AgentProfile
from ai_software_engineer.evaluation import FileEvaluationEventStore
from ai_software_engineer.knowledge.administration import find_gap_records
from ai_software_engineer.knowledge.gaps import KnowledgeGap
from ai_software_engineer.knowledge.views import read_gap_view
from ai_software_engineer.manager.delivery import _delivery_id
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
    ProjectDeliveryIntake,
    checkpoint_is_ancestor,
)
from ai_software_engineer.manager.dispatch import (
    ContinuationDispatchRecord,
    DeliveryAllocation,
    RecoveryDispatchRecord,
    VerificationReservation,
)
from ai_software_engineer.manager.mysql_dispatch_authority import _decode_allocation
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage, digest
from ai_software_engineer.multi_directory.production import DerivedStageInputs
from ai_software_engineer.multi_directory.retirement import RequirementRetirementStore
from ai_software_engineer.multi_directory.scope import git_read
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.projection.models import ProjectionFacts
from ai_software_engineer.projection.projector import RunProjectionBuilder
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.repository_workspace import RepositoryWorkspaceManifest
from ai_software_engineer.runtime_workspace import (
    FileTeamWorkforceStore,
    TeamWorkforceWorkspace,
)
from ai_software_engineer.store.mysql_repository import (
    _decode_event,
    _decode_task,
    _text,
    open_mysql_connection,
)
from ai_software_engineer.team_workspace import (
    _read_regular,
    _reject_symlinks,
    discover_team_workspaces,
)

from .models import (
    AgentView,
    AssignmentView,
    DialogueAttachmentView,
    DialogueTurnView,
    DocumentView,
    ProjectView,
    RequestView,
    RunView,
    ScopeView,
    TaskView,
    TeamReadError,
    TeamSnapshot,
)

_TERMINAL = {"DONE", "BLOCKED", "FAILED"}
_CURRENT_ROLE = {
    TaskStatus.IMPLEMENTING: AgentRole.CODER,
    TaskStatus.CONTINUE_REQUIRED: AgentRole.CODER,
    TaskStatus.QA: AgentRole.QA,
    TaskStatus.REVIEW: AgentRole.REVIEWER,
}


@dataclass(frozen=True)
class _Native:
    checkpoint: ProjectDeliveryCheckpoint
    intake: ProjectDeliveryIntake
    sidecar: Path
    history: tuple[ProjectDeliveryCheckpoint, ...]


class ProductionTeamReader:
    def __init__(self, config: ProductionConfig, environment: Mapping[str, str]) -> None:
        self.config = config
        self._environment = dict(environment)

    @classmethod
    def from_environment(cls) -> ProductionTeamReader:
        return cls(ProductionConfig.from_environment(), os.environ)

    def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
        try:
            return self._snapshot(project_id)
        except Exception as error:
            # Read failure must not become a successful empty team or expose a DSN/path secret.
            raise TeamReadError(
                "Team data unavailable; check configuration, MySQL and workspace integrity."
            ) from error

    def _snapshot(self, project_id: str | None) -> TeamSnapshot:
        teams = discover_team_workspaces(self.config.platform_root)
        if len(teams) != 1:
            raise ValueError("team workspace has not been prepared")
        team = teams[0]
        if team.manifest.team_id != self.config.team_id:
            raise ValueError("configured Team identity does not match the prepared Team")
        projects = team.project_registry().discover()
        selected_id = project_id or self.config.default_project_id
        if selected_id is None and projects:
            selected_id = projects[0].manifest.project_id
        selected = next(
            (item for item in projects if item.manifest.project_id == selected_id), None
        )
        if selected_id is not None and selected is None:
            raise ValueError("Project workspace has not been prepared")
        workforce_workspace = TeamWorkforceWorkspace.from_team(team)
        workforce = FileTeamWorkforceStore(workforce_workspace)
        profiles = tuple(
            workforce.get_agent(path.stem)
            for path in _files(workforce_workspace.directory("agents"), "*.json")
        )
        journal = (
            JointJournal(selected.requirements_root, read_only=True)
            if selected is not None
            else None
        )
        retired = (
            _retired_requirement_ids(selected, journal)
            if selected is not None and journal is not None
            else frozenset()
        )
        all_joints: list[JointCheckpoint] = []
        for path in _directories(
            selected.requirements_root if selected is not None else Path("/nonexistent"),
            "delivery_multi_*",
        ):
            assert journal is not None
            assert selected is not None
            checkpoint = journal.current(path.name)
            if checkpoint is None:
                continue  # an operation lock can precede the first committed checkpoint
            if (
                checkpoint.team_id != team.manifest.team_id
                or checkpoint.team_manifest_sha256 != team.manifest.manifest_sha256
                or checkpoint.project_id != selected.manifest.project_id
                or checkpoint.project_manifest_sha256 != selected.manifest.manifest_sha256
            ):
                raise ValueError("Requirement Team or Project mismatch")
            all_joints.append(checkpoint)
        retired_native_ids = frozenset(
            native_id
            for joint in all_joints
            if joint.delivery_id in retired
            for native_id in _owned_native_delivery_ids(joint)
        )
        joints = [joint for joint in all_joints if joint.delivery_id not in retired]
        natives = (
            tuple(
                native
                for native in _read_native(selected)
                if native.checkpoint.delivery_id not in retired_native_ids
            )
            if selected is not None
            else ()
        )
        by_id = {n.checkpoint.delivery_id: n for n in natives}
        ownership: dict[str, tuple[str, ScopeView]] = {}
        requests: list[RequestView] = []
        for joint in joints:
            children = {child.unit_id: child.checkpoint for child in joint.children}
            if not children.keys() <= {unit.id for unit in joint.scope.units}:
                raise ValueError("committed child unit is outside the Requirement scope")
            scopes: list[ScopeView] = []
            for unit in joint.scope.units:
                native_id: str | None = None
                reference = joint.design is not None and unit.id in joint.design.reference_only
                child_checkpoint = children.get(unit.id)
                if child_checkpoint is not None:
                    if reference or child_checkpoint.repository_root != unit.root:
                        raise ValueError("committed child code scope mismatch")
                    # A sealed child keeps its identity when integration recovery clears or
                    # replaces the parent plan. Derivation is only for the initial window
                    # before that child has been attached to the parent journal.
                    native_id = child_checkpoint.delivery_id
                elif joint.plan is not None and not reference:
                    derived = DerivedStageInputs(joint, unit.id)
                    native_id = _delivery_id(
                        derived.root,
                        derived.requirement,
                        namespace=joint.project_id,
                    )
                scope = ScopeView(
                    root=unit.root,
                    selected_paths=unit.selected_paths,
                    reference_only=reference,
                    delivery_id=native_id,
                )
                if native_id is not None:
                    if native_id in ownership:
                        raise ValueError("ambiguous native Requirement ownership")
                    ownership[native_id] = (joint.delivery_id, scope)
                scopes.append(scope)
            for child in joint.children:
                stored = by_id.get(child.checkpoint.delivery_id)
                if (
                    stored is None
                    or child.checkpoint.delivery_id not in ownership
                    or not checkpoint_is_ancestor(stored.history, child.checkpoint)
                ):
                    raise ValueError("committed child checkpoint mismatch")
            documents = tuple(
                DocumentView(
                    name=name,
                    source_uri=f"request://{joint.delivery_id}/{name}",
                    sha256=digest(document),
                    content=_safe(document.model_dump_json(indent=2)),
                )
                for name, document in (
                    ("ProductSpec", joint.product_spec),
                    ("TechnicalDesign", joint.design),
                    ("ExecutionPlan", joint.plan),
                    ("IntegrationEvidence", joint.integration),
                    ("SingleRepositoryAcceptance", joint.single_repository_acceptance),
                )
                if document is not None
            )
            waiting_single_acceptance = (
                len(joint.scope.units) == 1
                and len(joint.children) == 1
                and joint.children[0].checkpoint.stage is DeliveryStage.DONE
                and joint.single_repository_acceptance is None
                and joint.stage not in {JointStage.DONE, JointStage.CLOSED}
            )
            presented_stage = (
                "WAITING_DELIVERY_FINALIZATION" if waiting_single_acceptance else joint.stage
            )
            presented_next_action = (
                "原生 QA 与 Review 已通过，继续交付将复核现有证据并完成单仓需求。"  # noqa: RUF001
                if waiting_single_acceptance
                else _safe(joint.next_action)
            )
            knowledge_gap = None
            if joint.stage is JointStage.WAITING_HUMAN and joint.knowledge_gap_id is not None:
                assert selected is not None
                records = find_gap_records(
                    selected, joint.delivery_id, joint.knowledge_gap_id, read_only=True
                )
                knowledge_gap = read_gap_view(
                    records,
                    records.get("gaps", joint.knowledge_gap_id, KnowledgeGap),
                    current_gap_id=joint.knowledge_gap_id,
                )
                presented_next_action = (
                    "知识解答已批准，点击“继续交付”恢复原需求，无需重复解答。"  # noqa: RUF001
                    if knowledge_gap.resolution is not None
                    else "请在“知识缺口”中补充并批准解答，然后继续交付。"  # noqa: RUF001
                )
            requests.append(
                RequestView(
                    id=joint.delivery_id,
                    project_id=joint.project_id,
                    title=_safe(joint.title),
                    stage=presented_stage,
                    scopes=tuple(scopes),
                    next_action=presented_next_action,
                    blocker=(presented_next_action if _waiting(presented_stage) else None),
                    dialogue=tuple(
                        DialogueTurnView(
                            sequence=sequence,
                            speaker=message.speaker,
                            text=_safe(message.text),
                            attachments=tuple(
                                DialogueAttachmentView(
                                    id=screenshot.id,
                                    name=_safe(screenshot.source_name),
                                    media_type=screenshot.media_type,
                                    source_bytes=screenshot.source_bytes,
                                    sha256=screenshot.source_sha256,
                                )
                                for screenshot in message.screenshots
                            ),
                        )
                        for sequence, message in enumerate(joint.dialogue, 1)
                    ),
                    documents=documents,
                    checkpoint_sha256=joint.checkpoint_sha256,
                    knowledge_gap=knowledge_gap,
                )
            )
        tasks: list[TaskView] = []
        native_views: list[tuple[_Native, TaskView]] = []
        native_by_task: dict[str, tuple[_Native, str, ScopeView]] = {}
        if natives:
            assert selected is not None
            for native in natives:
                cp = native.checkpoint
                request_id, scope = ownership.get(
                    cp.delivery_id,
                    (
                        cp.delivery_id,
                        ScopeView(
                            root=cp.repository_root,
                            selected_paths=(".",),
                            delivery_id=cp.delivery_id,
                        ),
                    ),
                )
                if scope.root != cp.repository_root:
                    raise ValueError("child code scope mismatch")
                native_views.append(
                    (
                        native,
                        _task_base(
                            native,
                            selected.manifest.project_id,
                            request_id,
                            scope,
                        ),
                    )
                )
                for task_id, source_native in _native_task_sources(native).items():
                    existing = native_by_task.get(task_id)
                    if (
                        existing is not None
                        and existing[0].checkpoint.delivery_id
                        != source_native.checkpoint.delivery_id
                    ):
                        raise ValueError("ambiguous native Task ownership")
                    native_by_task[task_id] = (source_native, request_id, scope)

        # Filesystem prefixes first, SQL snapshot second: SQL cannot lag the captured checkpoints.
        # A pre-dispatch failure has no SQL Task, Assignment or verification source to enrich.
        # Its durable filesystem checkpoint is sufficient for an honest blocked work card.
        requires_sql = bool(native_by_task) or any(
            native.checkpoint.dispatch_commit_id is not None for native in natives
        )
        projected_native_views: list[tuple[_Native, TaskView]] = []
        if requires_sql:
            assert selected is not None
            connection = open_mysql_connection(self.config.require_mysql_dsn(self._environment))
            try:
                with connection.cursor(DictCursor) as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                    cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                    for native, base in native_views:
                        view = _read_task_details(native, cursor, base)
                        successor = _active_successor_dispatch(native, cursor)
                        if successor is not None:
                            view = _read_task_details(
                                native,
                                cursor,
                                base,
                                dispatch_override=successor,
                            )
                        tasks.append(view)
                        projected_native_views.append((native, view))
                    tasks.extend(
                        _read_verifications(
                            cursor,
                            native_by_task,
                            team_id=team.manifest.team_id,
                            project_id=selected.manifest.project_id,
                        )
                    )
            finally:
                connection.rollback()
                connection.close()
        else:
            for native, base in native_views:
                tasks.append(base)
                projected_native_views.append((native, base))

        if projected_native_views:
            assert selected is not None
            for native, view in projected_native_views:
                cp = native.checkpoint
                if cp.delivery_id not in ownership:
                    requests.append(
                        RequestView(
                            id=cp.delivery_id,
                            project_id=selected.manifest.project_id,
                            title=_safe(native.intake.title),
                            stage=cp.stage,
                            scopes=(view.scope,),
                            next_action=view.next_action,
                            blocker=view.blocker,
                            documents=_stage_refs(cp),
                            checkpoint_sha256=cp.checkpoint_sha256,
                        )
                    )
        requests = [_request_with_current_work(request, tasks) for request in requests]
        known_agents = {p.id for p in profiles}
        if any(a.agent_id not in known_agents for t in tasks for a in t.assignments):
            raise ValueError("assignment references an unknown Team member")
        agents = _agent_views(profiles, requests, tasks)
        return TeamSnapshot(
            as_of=datetime.now(UTC),
            team_id=team.manifest.team_id,
            team_name=_safe(team.manifest.name),
            selected_project_id=selected.manifest.project_id if selected is not None else None,
            projects=tuple(
                ProjectView(
                    id=item.manifest.project_id,
                    name=_safe(item.manifest.name),
                    repository_count=len(item.repository_registry().discover()),
                    requirement_count=len(
                        set(
                            path.name
                            for path in _directories(item.requirements_root, "delivery_multi_*")
                        )
                        - _retired_requirement_ids(
                            item,
                            JointJournal(item.requirements_root, read_only=True),
                        )
                    ),
                )
                for item in projects
            ),
            agents=agents,
            requests=tuple(sorted(requests, key=lambda r: r.id)),
            tasks=tuple(sorted(tasks, key=lambda t: (t.last_activity, t.id), reverse=True)),
        )


_UPSTREAM_ROLE_INDEX = {
    TeamRole.MANAGER: 0,
    TeamRole.PRODUCT: 1,
    TeamRole.DESIGNER: 2,
    TeamRole.PLANNER: 3,
}
_REQUEST_STAGE_INDEX = {
    "PREPARING": 0,
    "READY_FOR_DISCUSSION": 1,
    "PRODUCT_DISCOVERY": 1,
    "WAITING_PRODUCT_REPLY": 1,
    "WAITING_PRODUCT_APPROVAL": 1,
    "DESIGNING": 2,
    "PLANNING": 3,
    "DELIVERING": 4,
    "INTEGRATING": 4,
    "DONE": 5,
    "CLOSED": 5,
}
_CURRENT_REQUEST_STAGE = {
    TeamRole.MANAGER: "PREPARING",
    TeamRole.PRODUCT: "PRODUCT_DISCOVERY",
    TeamRole.DESIGNER: "DESIGNING",
    TeamRole.PLANNER: "PLANNING",
}


def _upstream_request_state(request: RequestView, role: TeamRole) -> str | None:
    role_index = _UPSTREAM_ROLE_INDEX.get(role)
    if role_index is None:
        return None
    if request.stage in {"BLOCKED", "WAITING_HUMAN"}:
        return "assigned" if role is TeamRole.MANAGER else None
    stage_index = _REQUEST_STAGE_INDEX.get(request.stage)
    if stage_index is None or stage_index < role_index:
        return None
    if stage_index > role_index:
        return "history"
    return "current" if request.stage == _CURRENT_REQUEST_STAGE[role] else "assigned"


def _agent_views(
    profiles: tuple[AgentProfile, ...],
    requests: list[RequestView],
    tasks: list[TaskView],
) -> tuple[AgentView, ...]:
    """Project Requirement stages and native Task assignments share one Agent queue."""

    def unique(values: list[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(values))

    views: list[AgentView] = []
    for profile in profiles:
        assigned = [
            task.id
            for task in tasks
            if not task.terminal
            and any(assignment.agent_id == profile.id for assignment in task.assignments)
        ]
        current = [
            task.id
            for task in tasks
            if not task.terminal
            and any(
                assignment.agent_id == profile.id and assignment.current_stage
                for assignment in task.assignments
            )
        ]
        history = [
            task.id
            for task in tasks
            if task.terminal
            and any(assignment.agent_id == profile.id for assignment in task.assignments)
        ]
        for request in requests:
            states = {
                state
                for role in profile.eligible_roles
                if (state := _upstream_request_state(request, role)) is not None
            }
            if "current" in states:
                assigned.append(request.id)
                current.append(request.id)
            elif "assigned" in states:
                assigned.append(request.id)
            elif "history" in states:
                history.append(request.id)
        views.append(
            AgentView(
                id=profile.id,
                name=_safe(profile.display_name),
                roles=profile.eligible_roles,
                capabilities=tuple(_safe(capability) for capability in profile.capabilities),
                enabled=profile.active,
                max_parallel_assignments=profile.max_parallel_assignments,
                assigned_delivery_ids=unique(assigned),
                current_stage_delivery_ids=unique(current),
                history_delivery_ids=unique(history),
            )
        )
    return tuple(views)


def _retired_requirement_ids(project: ProjectWorkspace, journal: JointJournal) -> frozenset[str]:
    return RequirementRetirementStore(
        project.requirements_root,
        team_id=project.team.manifest.team_id,
        team_manifest_sha256=project.team.manifest.manifest_sha256,
        project_id=project.manifest.project_id,
        project_manifest_sha256=project.manifest.manifest_sha256,
        read_only=True,
    ).retired_delivery_ids(journal)


def _owned_native_delivery_ids(joint: JointCheckpoint) -> frozenset[str]:
    """Return every native delivery identity derived from one joint Requirement."""
    result = {child.checkpoint.delivery_id for child in joint.children}
    for unit in joint.scope.units:
        reference = joint.design is not None and unit.id in joint.design.reference_only
        if joint.plan is None or reference:
            continue
        derived = DerivedStageInputs(joint, unit.id)
        result.add(
            _delivery_id(
                derived.root,
                derived.requirement,
                namespace=joint.project_id,
            )
        )
    return frozenset(result)


def _read_native(project: ProjectWorkspace) -> tuple[_Native, ...]:
    result: list[_Native] = []
    for sidecar in _directories(project.root / "repositories", "repository_*"):
        manifest = RepositoryWorkspaceManifest.model_validate_json(
            _read_regular(sidecar / "workspace.json", 64_000)
        )
        manifest.validate_binding(sidecar)
        if (
            manifest.repository_id != sidecar.name
            or manifest.project_id != project.manifest.project_id
            or manifest.project_manifest_sha256 != project.manifest.manifest_sha256
        ):
            raise ValueError("Repository workspace Project binding mismatch")
        root = sidecar / "state" / "project-deliveries"
        _reject_symlinks(root)
        if not root.exists():
            continue  # project prepared but never received a native delivery
        store = FileProjectDeliveryCheckpointStore(root, read_only=True)
        for directory in _directories(root, "delivery_*"):
            records = store.list(directory.name)
            if not records:
                continue
            cp = records[-1]
            intake = store.get_intake(cp.delivery_id)
            if (
                cp.repository_id != manifest.repository_id
                or cp.repository_root != manifest.repository_root
                or intake.repository_id != cp.repository_id
                or intake.repository_root != cp.repository_root
            ):
                raise ValueError("native checkpoint project mismatch")
            result.append(_Native(cp, intake, sidecar, records))
    if len({n.checkpoint.delivery_id for n in result}) != len(result):
        raise ValueError("ambiguous native delivery")
    return tuple(result)


def _native_task_sources(native: _Native) -> dict[str, _Native]:
    """Resolve the latest committed checkpoint for every Task used by one delivery."""
    result: dict[str, _Native] = {}
    for index, checkpoint in enumerate(native.history):
        if (
            checkpoint.delivery_id != native.checkpoint.delivery_id
            or checkpoint.repository_id != native.checkpoint.repository_id
            or checkpoint.repository_root != native.checkpoint.repository_root
        ):
            raise ValueError("native checkpoint history binding mismatch")
        if checkpoint.task_id is None:
            continue
        result[checkpoint.task_id] = _Native(
            checkpoint=checkpoint,
            intake=native.intake,
            sidecar=native.sidecar,
            history=native.history[: index + 1],
        )
    return result


def _safe(text: str) -> str:
    return redact_text(text).text


def _waiting(stage: str) -> bool:
    return stage.startswith("WAITING_") or stage in {"BLOCKED", "FAILED"}


def _request_with_current_work(request: RequestView, tasks: list[TaskView]) -> RequestView:
    """Prefer a newer active child Task over a stale terminal joint observation."""
    # Knowledge waits preserve the child's delivery checkpoint; it is not active work.
    if request.knowledge_gap is not None and request.knowledge_gap.is_current:
        return request
    if not (_waiting(request.stage) or request.stage in {"DELIVERING", "INTEGRATING"}):
        return request
    active = tuple(
        task
        for task in tasks
        if task.request_id == request.id
        and not task.terminal
        and task.blocker is None
        and not _waiting(task.status)
    )
    if not active:
        return request
    current = max(active, key=lambda task: (task.last_activity, task.id))
    stage = "INTEGRATING" if current.work_kind == "candidate_verification" else "DELIVERING"
    return request.model_copy(
        update={
            "stage": stage,
            "next_action": current.next_action,
            "blocker": None,
        }
    )


def _directories(root: Path, pattern: str) -> tuple[Path, ...]:
    _reject_symlinks(root)
    paths = tuple(sorted(root.glob(pattern)))
    for path in paths:
        _reject_symlinks(path)
        if not path.is_dir():
            raise ValueError("expected workspace directory")
    return paths


def _files(root: Path, pattern: str) -> tuple[Path, ...]:
    _reject_symlinks(root)
    paths = tuple(sorted(root.glob(pattern)))
    for path in paths:
        _reject_symlinks(path)
        if not path.is_file():
            raise ValueError("expected regular record")
    return paths


def _stage_refs(cp: ProjectDeliveryCheckpoint) -> tuple[DocumentView, ...]:
    return tuple(
        DocumentView(name=name, source_uri=f"{name}://{identity}", sha256=sha)
        for name, identity, sha in (
            ("ProductSpec", cp.product_spec_id, cp.product_spec_sha256),
            ("TechnicalDesign", cp.technical_design_id, cp.technical_design_sha256),
            ("ExecutionPlan", cp.execution_plan_id, cp.execution_plan_sha256),
        )
        if identity is not None and sha is not None
    )


def _read_task(
    native: _Native,
    project_id: str,
    request_id: str,
    scope: ScopeView,
    cursor: DictCursor,
) -> TaskView:
    return _read_task_details(
        native,
        cursor,
        _task_base(native, project_id, request_id, scope),
    )


def _task_base(
    native: _Native,
    project_id: str,
    request_id: str,
    scope: ScopeView,
) -> TaskView:
    cp = native.checkpoint
    return TaskView(
        id=cp.delivery_id,
        project_id=project_id,
        request_id=request_id,
        task_id=cp.task_id,
        title=_safe(native.intake.title),
        scope=scope,
        status=cp.stage,
        checkpoint_stage=cp.stage,
        terminal=cp.stage in _TERMINAL,
        last_activity=cp.checkpointed_at,
        blocker=_safe(cp.failure_summary or cp.next_action) if _waiting(cp.stage) else None,
        next_action=cp.next_action,
        candidate_revision=cp.candidate_revision,
        candidate_branch=_candidate_branch(cp.repository_root, cp.task_id, cp.candidate_revision),
        documents=_stage_refs(cp),
    )


def _read_verifications(
    cursor: DictCursor,
    native_by_task: Mapping[str, tuple[_Native, str, ScopeView]],
    *,
    team_id: str,
    project_id: str,
) -> tuple[TaskView, ...]:
    """Project verification reservations as first-class read-side work items."""
    cursor.execute(
        "SELECT plan_sha256,payload_json,completion_sha256,abandonment_sha256 "
        "FROM verification_reservations ORDER BY plan_sha256"
    )
    reservations: list[tuple[VerificationReservation, str | None, str | None]] = []
    latest_by_source: dict[tuple[str, str], VerificationReservation] = {}
    for row in cursor.fetchall():
        reservation = VerificationReservation.model_validate_json(_text(row, "payload_json"))
        if reservation.plan_sha256 != row["plan_sha256"]:
            raise ValueError("verification reservation row identity mismatch")
        completion_sha256 = (
            str(row["completion_sha256"]) if row["completion_sha256"] is not None else None
        )
        abandonment_sha256 = (
            str(row["abandonment_sha256"]) if row["abandonment_sha256"] is not None else None
        )
        if completion_sha256 is not None and abandonment_sha256 is not None:
            raise ValueError("verification reservation has conflicting releases")
        reservations.append((reservation, completion_sha256, abandonment_sha256))
        key = (str(reservation.repository_id), str(reservation.source_task_id))
        latest = latest_by_source.get(key)
        if latest is None or reservation.committed_at > latest.committed_at:
            latest_by_source[key] = reservation
        elif reservation.committed_at == latest.committed_at:
            raise ValueError("ambiguous verification reservation order")
    result: list[TaskView] = []
    validated_sources: set[str] = set()
    repository_ids = {native.checkpoint.repository_id for native, _, _ in native_by_task.values()}
    for reservation, completion_sha256, abandonment_sha256 in reservations:
        source = native_by_task.get(str(reservation.source_task_id))
        if source is None:
            if reservation.repository_id in repository_ids:
                raise ValueError("verification reservation source Task is missing")
            continue
        native, request_id, source_scope = source
        if reservation.repository_id != native.checkpoint.repository_id:
            raise ValueError("verification reservation project mismatch")
        if reservation.source_task_id not in validated_sources:
            source_view = _read_task(native, project_id, request_id, source_scope, cursor)
            if source_view.task_id != reservation.source_task_id:
                raise ValueError("verification reservation source Task is missing")
            validated_sources.add(reservation.source_task_id)
        result.append(
            _verification_view(
                native,
                request_id,
                source_scope,
                reservation,
                completion_sha256,
                abandonment_sha256,
                superseded=(
                    completion_sha256 is None
                    and abandonment_sha256 is None
                    and latest_by_source[
                        (str(reservation.repository_id), str(reservation.source_task_id))
                    ].plan_sha256
                    != reservation.plan_sha256
                ),
                team_id=team_id,
                project_id=project_id,
            )
        )
    return tuple(result)


def _verification_view(
    native: _Native,
    request_id: str,
    source_scope: ScopeView,
    reservation: VerificationReservation,
    completion_sha256: str | None,
    abandonment_sha256: str | None,
    *,
    superseded: bool,
    team_id: str,
    project_id: str,
) -> TaskView:
    verification_id = f"verification_{reservation.plan_sha256[:32]}"
    current_role = AgentRole.QA
    status, terminal = "VERIFY_QA", False
    next_action = "QA candidate verification is active or awaiting resume."
    blocker: str | None = None
    last_activity = reservation.committed_at
    documents: list[DocumentView] = []
    run_ids: set[str] = set()
    store_root = (
        native.sidecar / "state" / f"candidate-verification-{native.checkpoint.delivery_id}"
    )
    completion = None
    if store_root.exists():
        scope = RecoveryScope(
            team_id=team_id,
            repository_id=native.checkpoint.repository_id,
            delivery_id=native.checkpoint.delivery_id,
            repository_root=native.checkpoint.repository_root,
        )
        store = FileRecoveryStore(store_root, scope=scope)
        plan = store.get_verification_plan(reservation.plan_sha256)
        authorization = store.get_verification_authorization(reservation.plan_sha256)
        if (
            plan.execution_task_id != reservation.task_id
            or plan.inputs.task_id != reservation.source_task_id
            or not authorization.decision.approved
        ):
            raise ValueError("verification reservation lineage mismatch")
        documents.extend(
            (
                DocumentView(
                    name="CandidateVerificationPlan",
                    source_uri=f"candidate-verification://{reservation.plan_sha256}/plan",
                    sha256=plan.plan_sha256,
                    content=_safe(plan.model_dump_json(indent=2)),
                ),
                DocumentView(
                    name="CandidateVerificationApproval",
                    source_uri=f"candidate-verification://{reservation.plan_sha256}/approval",
                    sha256=authorization.authorization_sha256,
                    content=_safe(authorization.model_dump_json(indent=2)),
                ),
            )
        )
        for role in (AgentRole.QA, AgentRole.REVIEWER):
            try:
                invocation = store.get_verification_invocation(reservation.plan_sha256, role)
            except RecoveryRecordMissing:
                continue
            run_ids.add(str(invocation.request.run_id))
            last_activity = max(last_activity, invocation.admitted_at)
            if role is AgentRole.REVIEWER:
                current_role, status = AgentRole.REVIEWER, "VERIFY_REVIEW"
                next_action = "Reviewer candidate verification is active or awaiting resume."
        try:
            completion = store.get_verification_completion(reservation.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            last_activity = max(last_activity, completion.completed_at)
            documents.append(
                DocumentView(
                    name="CandidateVerificationCompletion",
                    source_uri=f"candidate-verification://{reservation.plan_sha256}/completion",
                    sha256=completion.completion_sha256,
                    content=_safe(completion.model_dump_json(indent=2)),
                )
            )
    if completion_sha256 is not None:
        if completion is None or completion.completion_sha256 != completion_sha256:
            raise ValueError("verification completion lineage mismatch")
        terminal = True
        current_role = AgentRole.QA
        if completion.verified:
            status = "VERIFIED"
            next_action = "Candidate verification passed; continue the delivery acceptance policy."
        else:
            status = "REMEDIATION_REQUIRED"
            blocker = (
                "QA failed; resume the delivery to create a linked Coder remediation."
                if completion.qa.content.status.value == "FAIL"
                else "Review rejected; resume the delivery to create a linked Coder remediation."
            )
            next_action = blocker
    elif abandonment_sha256 is not None:
        terminal = True
        status = "VERIFICATION_INTERRUPTED"
        blocker = "Candidate verification stopped before a sealed result was produced."
        next_action = "Continue the delivery to create and approve a fresh verification plan."
    elif superseded:
        terminal = True
        status = "VERIFICATION_SUPERSEDED"
        next_action = "A successor verification plan replaced this consumed plan."
    assignments = tuple(
        AssignmentView(
            agent_id=phase.agent_id,
            role=phase.role,
            planned_provider=phase.model_selection.provider,
            planned_model=phase.model_selection.model,
            current_stage=not terminal and phase.role is current_role,
        )
        for phase in reservation.phases
    )
    return TaskView(
        id=verification_id,
        project_id=project_id,
        request_id=request_id,
        work_kind="candidate_verification",
        task_id=reservation.task_id,
        source_delivery_id=native.checkpoint.delivery_id,
        source_task_id=reservation.source_task_id,
        plan_sha256=reservation.plan_sha256,
        title=f"Candidate verification · {_safe(native.intake.title)}",
        scope=source_scope.model_copy(update={"delivery_id": verification_id}),
        status=status,
        checkpoint_stage="CANDIDATE_VERIFICATION",
        terminal=terminal,
        last_activity=last_activity,
        blocker=blocker,
        next_action=next_action,
        candidate_revision=native.checkpoint.candidate_revision,
        candidate_branch=_candidate_branch(
            native.checkpoint.repository_root,
            reservation.source_task_id,
            native.checkpoint.candidate_revision,
        ),
        assignments=assignments,
        # Verifier requests judge the immutable source Task/candidate.  The
        # distinct reservation Task scopes leases and worktrees, while the
        # invocation digest identifies the exact source-Task Run shown here.
        runs=_read_runs(native, reservation.source_task_id, run_ids=run_ids),
        documents=tuple(documents),
    )


def _read_task_details(
    native: _Native,
    cursor: DictCursor,
    base: TaskView,
    *,
    dispatch_override: DeliveryAllocation | None = None,
) -> TaskView:
    cp = native.checkpoint
    if cp.dispatch_commit_id is None and dispatch_override is None:
        return base
    checkpoint_bound = dispatch_override is None
    if checkpoint_bound:
        cursor.execute("SELECT * FROM dispatch_commits WHERE id = %s", (cp.dispatch_commit_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("missing committed dispatch")
        dispatch = _decode_allocation(row)
        if (
            dispatch.dispatch_sha256 != cp.dispatch_commit_sha256
            or dispatch.repository_id != cp.repository_id
            or dispatch.task.repository != cp.repository_root
            or (cp.task_id is not None and dispatch.task_id != cp.task_id)
        ):
            raise ValueError("dispatch checkpoint mismatch")
    else:
        if dispatch_override is None:
            raise ValueError("active successor dispatch is missing")
        dispatch = dispatch_override
        if (
            dispatch.repository_id != cp.repository_id
            or dispatch.task.repository != cp.repository_root
        ):
            raise ValueError("active successor dispatch scope mismatch")
    cursor.execute("SELECT * FROM tasks WHERE id = %s", (dispatch.task_id,))
    row = cursor.fetchone()
    if row is None:
        if cp.task_id is not None:
            raise ValueError("materialized Task is missing")
        return base
    task = _decode_task(dispatch.task_id, _text(row, "payload_json"))
    if row["status"] != task.status.value:
        raise ValueError("Task indexed status mismatch")
    if checkpoint_bound and cp.task_revision is not None and row["revision"] < cp.task_revision:
        raise ValueError("Task snapshot predates the captured checkpoint")
    if (
        checkpoint_bound
        and cp.task_status is not None
        and cp.task_status.value in _TERMINAL
        and task.status != cp.task_status
    ):
        raise ValueError("terminal checkpoint Task status mismatch")
    normalized = task.model_copy(
        update={
            "status": TaskStatus.NEW,
            "attempts": 0,
            "updated_at": dispatch.task.updated_at,
        }
    )
    if normalized != dispatch.task:
        raise ValueError("Task differs from dispatch intent")
    cursor.execute("SELECT * FROM state_events WHERE task_id = %s ORDER BY revision", (task.id,))
    event_rows = cursor.fetchall()
    if [r["revision"] for r in event_rows] != list(range(1, len(event_rows) + 1)):
        raise ValueError("non-contiguous SQL event revisions")
    if row["revision"] != len(event_rows):
        raise ValueError("SQL Task revision mismatch")
    events = tuple(_decode_event(_text(r, "payload_json")) for r in event_rows)
    if any(
        e.event_id != r["event_id"] or e.task_id != r["task_id"]
        for e, r in zip(events, event_rows, strict=True)
    ):
        raise ValueError("state event row identity mismatch")
    artifact_store = FileArtifactStore(native.sidecar / "artifacts", read_only=True)
    artifact_ids = sorted({identity for e in events for identity in e.artifact_ids})
    for identity in artifact_ids:
        _reject_symlinks(native.sidecar / "artifacts" / f"{identity}.json")
    artifacts = tuple(artifact_store.get(identity) for identity in artifact_ids)
    evaluation_store = FileEvaluationEventStore(native.sidecar / "evaluations", read_only=True)
    # Read a finite published prefix; later events cannot silently change this SQL snapshot.
    evaluation = tuple(
        e
        for path in _files(native.sidecar / "evaluations", "evalevt_*.json")
        if (e := evaluation_store.get(path.stem)).task_id == task.id
        and e.occurred_at <= task.updated_at
    )
    projection = RunProjectionBuilder().build(
        ProjectionFacts(
            tasks=(task,),
            state_events=events,
            artifacts=artifacts,
            evaluation_events=evaluation,
            assignments=tuple(p.assignment for p in dispatch.phases),
        )
    )
    timeline = tuple(
        entry.model_copy(update={"summary": _safe(entry.summary), "details": {}})
        for entry in projection.tasks[0].timeline
    )
    docs = tuple(
        DocumentView(
            name=a.kind.value,
            source_uri=f"artifact://{a.artifact_id}",
            sha256=a.integrity.sha256,
            content=_safe(a.model_dump_json(indent=2)),
        )
        for a in artifacts
    )
    blocker = base.blocker if checkpoint_bound else None
    if blocker is None and task.status.value in {"BLOCKED", "FAILED"} and events:
        blocker = _safe(events[-1].reason)
    continuation = dispatch if isinstance(dispatch, ContinuationDispatchRecord) else None
    recovery = dispatch if isinstance(dispatch, RecoveryDispatchRecord) else None
    source_task_id = (
        continuation.source_task_id
        if continuation is not None
        else (
            str(recovery.task.metadata.get("recovery_of_task_id")) if recovery is not None else None
        )
    )
    source_delivery_id = (
        continuation.source_delivery_id
        if continuation is not None
        else (
            str(recovery.task.metadata.get("recovery_of_delivery_id"))
            if recovery is not None
            else None
        )
    )
    plan_sha256 = (
        continuation.continuation_sha256
        if continuation is not None
        else (recovery.recovery_plan_sha256 if recovery is not None else None)
    )
    terminal = task.status.value in _TERMINAL or (base.terminal if checkpoint_bound else False)
    candidate_revision = projection.tasks[0].candidate_revision
    if checkpoint_bound:
        candidate_revision = cp.candidate_revision or candidate_revision
    from ai_software_engineer.team_view.queue_reader import read_role_queue

    role_queue = read_role_queue(
        cursor,
        task_id=task.id,
        repository_id=dispatch.repository_id,
        allocation_sha256=dispatch.dispatch_sha256,
        now=datetime.now(UTC),
    )
    return base.model_copy(
        update={
            "role_queue": role_queue,
            "work_kind": (
                "remediation"
                if continuation is not None or recovery is not None
                else base.work_kind
            ),
            "source_delivery_id": source_delivery_id,
            "source_task_id": source_task_id,
            "plan_sha256": plan_sha256,
            "task_id": task.id,
            "status": task.status.value,
            "checkpoint_stage": (base.checkpoint_stage if checkpoint_bound else task.status.value),
            "terminal": terminal,
            "last_activity": max(cp.checkpointed_at, task.updated_at),
            "blocker": blocker,
            "next_action": (
                base.next_action if checkpoint_bound else f"Continue {task.status.value}."
            ),
            "assignments": tuple(
                AssignmentView(
                    agent_id=p.agent_id,
                    role=p.role,
                    planned_provider=p.model_selection.provider,
                    planned_model=p.model_selection.model,
                    current_stage=(
                        _CURRENT_ROLE.get(task.status) is p.role
                        and not terminal
                        and (
                            not role_queue
                            or any(
                                step.role is p.role
                                and step.status is WorkItemStatus.RUNNING
                                and step.lease_liveness == "LEASE_VALID"
                                for step in role_queue
                            )
                        )
                    ),
                )
                for p in dispatch.phases
            ),
            "timeline": timeline,
            "runs": _read_runs(native, task.id),
            "documents": base.documents + docs,
            "candidate_revision": candidate_revision,
            "candidate_branch": _candidate_branch(cp.repository_root, task.id, candidate_revision),
        }
    )


def _active_successor_dispatch(
    native: _Native,
    cursor: DictCursor,
) -> DeliveryAllocation | None:
    """Return the one live recovery/remediation Task newer than the checkpoint.

    A Coder run begins only after its dispatch and SQL Task are durable.  The native
    delivery checkpoint is published after that run returns, so it legitimately lags
    while Coder, QA, or Reviewer is executing.  Project the live successor instead of
    leaving the parent Requirement and Team queues on the previous BLOCKED checkpoint.
    """
    cp = native.checkpoint
    known_tasks = _native_task_sources(native)
    cursor.execute(
        "SELECT * FROM dispatch_commits WHERE repository_id = %s",
        (cp.repository_id,),
    )
    candidates: list[DeliveryAllocation] = []
    for row in cursor.fetchall():
        dispatch = _decode_allocation(row)
        if dispatch.task_id == cp.task_id or dispatch.committed_at <= cp.checkpointed_at:
            continue
        source_task_id: str | None = None
        source_delivery_id: str | None = None
        if isinstance(dispatch, RecoveryDispatchRecord):
            source_task_id = str(dispatch.task.metadata.get("recovery_of_task_id", ""))
            source_delivery_id = str(dispatch.task.metadata.get("recovery_of_delivery_id", ""))
            if source_delivery_id == cp.delivery_id and (
                source_task_id != cp.task_id
                or dispatch.task.metadata.get("recovery_source_checkpoint_sha256")
                != cp.checkpoint_sha256
            ):
                raise ValueError("active recovery source checkpoint mismatch")
        elif isinstance(dispatch, ContinuationDispatchRecord):
            source_task_id = str(dispatch.source_task_id)
            source_delivery_id = str(dispatch.source_delivery_id)
        if source_task_id not in known_tasks or source_delivery_id != cp.delivery_id:
            continue
        cursor.execute("SELECT status FROM tasks WHERE id = %s", (dispatch.task_id,))
        task_row = cursor.fetchone()
        if task_row is None:
            continue
        if str(task_row["status"]) not in _TERMINAL:
            candidates.append(dispatch)
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("ambiguous active successor dispatch")
    return candidates[0]


def _read_runs(
    native: _Native, task_id: str, *, run_ids: set[str] | None = None
) -> tuple[RunView, ...]:
    root = model_route_root(native.sidecar)
    _reject_symlinks(root)
    if not root.exists():
        return ()
    store = FileModelRouteAttemptStore(root, read_only=True)
    runs: list[RunView] = []
    for directory in _directories(root, "run_*"):
        _files(directory, "*.json")  # reject symlinks before asking the typed store to decode
        for attempt in store.list_for_run(directory.name):
            if attempt.task_id == task_id and (run_ids is None or attempt.run_id in run_ids):
                runs.append(
                    RunView(
                        run_id=attempt.run_id,
                        role=attempt.role,
                        provider=_safe(attempt.provider),
                        model=_safe(attempt.model),
                        route_index=attempt.route_index,
                        outcome=attempt.outcome.value,
                        error_code=attempt.error_code.value if attempt.error_code else None,
                        duration_ms=attempt.result.duration_ms,
                        completed_at=attempt.completed_at,
                        source_uri=f"model-route://{attempt.run_id}/{attempt.route_index}",
                        sha256=attempt.attempt_sha256,
                    )
                )
    return tuple(sorted(runs, key=lambda r: (r.completed_at, r.run_id, r.route_index)))


def _candidate_branch(
    repository_root: str, task_id: str | None, candidate_revision: str | None
) -> str | None:
    if task_id is None or candidate_revision is None:
        return None
    value = git_read(
        Path(repository_root),
        "for-each-ref",
        f"--points-at={candidate_revision}",
        "--format=%(refname:short)",
        f"refs/heads/ai/{task_id}",
    )
    if not value:
        return None
    branches = tuple(
        branch for branch in value.splitlines() if branch.startswith(f"ai/{task_id}/attempt-")
    )
    return branches[0] if len(branches) == 1 else None
