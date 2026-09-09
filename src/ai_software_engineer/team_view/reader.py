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
from ai_software_engineer.company_workspace import CompanyWorkspace, _read_regular, _reject_symlinks
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.evaluation import FileEvaluationEventStore
from ai_software_engineer.multi_directory.models import JointCheckpoint, digest
from ai_software_engineer.multi_directory.production import DerivedStageInputs
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.project_manager.delivery import _delivery_id
from ai_software_engineer.project_manager.delivery_checkpoint import (
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
    ProjectDeliveryIntake,
    checkpoint_is_ancestor,
)
from ai_software_engineer.project_manager.dispatch import (
    ContinuationDispatchRecord,
    VerificationReservation,
)
from ai_software_engineer.project_manager.mysql_dispatch_authority import _decode_allocation
from ai_software_engineer.project_workspace import ProjectWorkspaceManifest
from ai_software_engineer.projection.models import ProjectionFacts
from ai_software_engineer.projection.projector import RunProjectionBuilder
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.runtime_workspace import (
    FileOrganizationWorkforceStore,
    OrganizationWorkspace,
)
from ai_software_engineer.store.mysql_repository import (
    _decode_event,
    _decode_task,
    _text,
    open_mysql_connection,
)

from .models import (
    AgentView,
    AssignmentView,
    DocumentView,
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

    def snapshot(self) -> TeamSnapshot:
        try:
            return self._snapshot()
        except Exception as error:
            # Read failure must not become a successful empty team or expose a DSN/path secret.
            raise TeamReadError(
                "Team data unavailable; check configuration, MySQL and workspace integrity."
            ) from error

    def _snapshot(self) -> TeamSnapshot:
        company = CompanyWorkspace.initialize(
            self.config.platform_root,
            company_id=self.config.company_id,
            name=self.config.company_name,
            read_only=True,
        )
        organization = OrganizationWorkspace.open(Path(self.config.platform_root) / "organization")
        workforce = FileOrganizationWorkforceStore(organization)
        profiles = tuple(
            workforce.get_agent(path.stem)
            for path in _files(organization.directory("agents"), "*.json")
        )
        journal = JointJournal(company.requests_root, read_only=True)
        joints: list[JointCheckpoint] = []
        for path in _directories(company.requests_root, "delivery_multi_*"):
            checkpoint = journal.current(path.name)
            if checkpoint is None:
                continue  # an operation lock can precede the first committed checkpoint
            if (
                checkpoint.company_id != company.manifest.company_id
                or checkpoint.company_manifest_sha256 != company.manifest.manifest_sha256
            ):
                raise ValueError("request company mismatch")
            joints.append(checkpoint)
        natives = _read_native(company)
        by_id = {n.checkpoint.delivery_id: n for n in natives}
        ownership: dict[str, tuple[str, ScopeView]] = {}
        requests: list[RequestView] = []
        for joint in joints:
            scopes: list[ScopeView] = []
            for unit in joint.scope.units:
                native_id: str | None = None
                reference = joint.design is not None and unit.id in joint.design.reference_only
                if joint.plan is not None and not reference:
                    derived = DerivedStageInputs(joint, unit.id)
                    native_id = _delivery_id(
                        derived.root, derived.requirement, namespace=joint.company_id
                    )
                scope = ScopeView(
                    root=unit.root,
                    selected_paths=unit.selected_paths,
                    reference_only=reference,
                    delivery_id=native_id,
                )
                if native_id is not None:
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
                )
                if document is not None
            )
            requests.append(
                RequestView(
                    id=joint.delivery_id,
                    title=_safe(joint.title),
                    stage=joint.stage,
                    scopes=tuple(scopes),
                    next_action=_safe(joint.next_action),
                    blocker=_safe(joint.next_action) if _waiting(joint.stage) else None,
                    documents=documents,
                    checkpoint_sha256=joint.checkpoint_sha256,
                )
            )
        tasks: list[TaskView] = []
        # Filesystem prefixes first, SQL snapshot second: SQL cannot lag the captured checkpoints.
        if natives:
            connection = open_mysql_connection(self.config.require_mysql_dsn(self._environment))
            try:
                with connection.cursor(DictCursor) as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                    cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                    native_by_task: dict[str, tuple[_Native, str, ScopeView]] = {}
                    for native in natives:
                        cp = native.checkpoint
                        request_id, scope = ownership.get(
                            cp.delivery_id,
                            (
                                cp.delivery_id,
                                ScopeView(
                                    root=cp.project_root,
                                    selected_paths=(".",),
                                    delivery_id=cp.delivery_id,
                                ),
                            ),
                        )
                        if scope.root != cp.project_root:
                            raise ValueError("child code scope mismatch")
                        view = _read_task(native, request_id, scope, cursor)
                        tasks.append(view)
                        if view.task_id is not None:
                            native_by_task[view.task_id] = (native, request_id, scope)
                        if cp.delivery_id not in ownership:
                            requests.append(
                                RequestView(
                                    id=cp.delivery_id,
                                    title=_safe(native.intake.title),
                                    stage=cp.stage,
                                    scopes=(scope,),
                                    next_action=view.next_action,
                                    blocker=view.blocker,
                                    documents=_stage_refs(cp),
                                    checkpoint_sha256=cp.checkpoint_sha256,
                                )
                            )
                    tasks.extend(
                        _read_verifications(
                            cursor,
                            native_by_task,
                            company_id=company.manifest.company_id,
                        )
                    )
            finally:
                connection.rollback()
                connection.close()
        known_agents = {p.id for p in profiles}
        if any(a.agent_id not in known_agents for t in tasks for a in t.assignments):
            raise ValueError("assignment references an unknown organization member")
        agents = tuple(
            AgentView(
                id=p.id,
                name=_safe(p.display_name),
                roles=p.eligible_roles,
                capabilities=tuple(_safe(c) for c in p.capabilities),
                enabled=p.active,
                max_parallel_assignments=p.max_parallel_assignments,
                assigned_delivery_ids=tuple(
                    t.id
                    for t in tasks
                    if not t.terminal and any(a.agent_id == p.id for a in t.assignments)
                ),
                current_stage_delivery_ids=tuple(
                    t.id
                    for t in tasks
                    if not t.terminal
                    and any(a.agent_id == p.id and a.current_stage for a in t.assignments)
                ),
                history_delivery_ids=tuple(
                    t.id
                    for t in tasks
                    if t.terminal and any(a.agent_id == p.id for a in t.assignments)
                ),
            )
            for p in profiles
        )
        return TeamSnapshot(
            as_of=datetime.now(UTC),
            company_id=company.manifest.company_id,
            company_name=_safe(company.manifest.name),
            agents=agents,
            requests=tuple(sorted(requests, key=lambda r: r.id)),
            tasks=tuple(sorted(tasks, key=lambda t: (t.last_activity, t.id), reverse=True)),
        )


def _read_native(company: CompanyWorkspace) -> tuple[_Native, ...]:
    result: list[_Native] = []
    for sidecar in _directories(company.root / "projects", "project_*"):
        manifest = ProjectWorkspaceManifest.model_validate_json(
            _read_regular(sidecar / "workspace.json", 64_000)
        )
        manifest.validate_binding(sidecar)
        if manifest.project_id != sidecar.name:
            raise ValueError("project directory identity mismatch")
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
                cp.project_id != manifest.project_id
                or cp.project_root != manifest.project_root
                or intake.project_id != cp.project_id
                or intake.project_root != cp.project_root
            ):
                raise ValueError("native checkpoint project mismatch")
            result.append(_Native(cp, intake, sidecar, records))
    if len({n.checkpoint.delivery_id for n in result}) != len(result):
        raise ValueError("ambiguous native delivery")
    return tuple(result)


def _safe(text: str) -> str:
    return redact_text(text).text


def _waiting(stage: str) -> bool:
    return stage.startswith("WAITING_") or stage in {"BLOCKED", "FAILED"}


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


def _read_task(native: _Native, request_id: str, scope: ScopeView, cursor: DictCursor) -> TaskView:
    cp = native.checkpoint
    base = TaskView(
        id=cp.delivery_id,
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
        documents=_stage_refs(cp),
    )
    return _read_task_details(native, cursor, base)


def _read_verifications(
    cursor: DictCursor,
    native_by_task: Mapping[str, tuple[_Native, str, ScopeView]],
    *,
    company_id: str,
) -> tuple[TaskView, ...]:
    """Project verification reservations as first-class read-side work items."""
    cursor.execute(
        "SELECT plan_sha256,payload_json,completion_sha256 "
        "FROM verification_reservations ORDER BY plan_sha256"
    )
    result: list[TaskView] = []
    project_ids = {native.checkpoint.project_id for native, _, _ in native_by_task.values()}
    for row in cursor.fetchall():
        reservation = VerificationReservation.model_validate_json(_text(row, "payload_json"))
        if reservation.plan_sha256 != row["plan_sha256"]:
            raise ValueError("verification reservation row identity mismatch")
        source = native_by_task.get(str(reservation.source_task_id))
        if source is None:
            if reservation.project_id in project_ids:
                raise ValueError("verification reservation source Task is missing")
            continue
        native, request_id, source_scope = source
        if reservation.project_id != native.checkpoint.project_id:
            raise ValueError("verification reservation project mismatch")
        result.append(
            _verification_view(
                native,
                request_id,
                source_scope,
                reservation,
                str(row["completion_sha256"]) if row["completion_sha256"] is not None else None,
                company_id=company_id,
            )
        )
    return tuple(result)


def _verification_view(
    native: _Native,
    request_id: str,
    source_scope: ScopeView,
    reservation: VerificationReservation,
    completion_sha256: str | None,
    *,
    company_id: str,
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
            company_id=company_id,
            project_id=native.checkpoint.project_id,
            delivery_id=native.checkpoint.delivery_id,
            project_root=native.checkpoint.project_root,
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
        assignments=assignments,
        # Verifier requests judge the immutable source Task/candidate.  The
        # distinct reservation Task scopes leases and worktrees, while the
        # invocation digest identifies the exact source-Task Run shown here.
        runs=_read_runs(native, reservation.source_task_id, run_ids=run_ids),
        documents=tuple(documents),
    )


def _read_task_details(native: _Native, cursor: DictCursor, base: TaskView) -> TaskView:
    cp = native.checkpoint
    if cp.dispatch_commit_id is None:
        return base
    cursor.execute("SELECT * FROM dispatch_commits WHERE id = %s", (cp.dispatch_commit_id,))
    row = cursor.fetchone()
    if row is None:
        raise ValueError("missing committed dispatch")
    dispatch = _decode_allocation(row)
    if (
        dispatch.dispatch_sha256 != cp.dispatch_commit_sha256
        or dispatch.project_id != cp.project_id
        or dispatch.task.repository != cp.project_root
        or (cp.task_id is not None and dispatch.task_id != cp.task_id)
    ):
        raise ValueError("dispatch checkpoint mismatch")
    cursor.execute("SELECT * FROM tasks WHERE id = %s", (dispatch.task_id,))
    row = cursor.fetchone()
    if row is None:
        if cp.task_id is not None:
            raise ValueError("materialized Task is missing")
        return base
    task = _decode_task(dispatch.task_id, _text(row, "payload_json"))
    if row["status"] != task.status.value:
        raise ValueError("Task indexed status mismatch")
    if cp.task_revision is not None and row["revision"] < cp.task_revision:
        raise ValueError("Task snapshot predates the captured checkpoint")
    if (
        cp.task_status is not None
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
    blocker = base.blocker or (
        _safe(events[-1].reason) if task.status.value in {"BLOCKED", "FAILED"} and events else None
    )
    continuation = dispatch if isinstance(dispatch, ContinuationDispatchRecord) else None
    return base.model_copy(
        update={
            "work_kind": "remediation" if continuation is not None else base.work_kind,
            "source_delivery_id": (
                continuation.source_delivery_id if continuation is not None else None
            ),
            "source_task_id": (continuation.source_task_id if continuation is not None else None),
            "plan_sha256": (continuation.continuation_sha256 if continuation is not None else None),
            "task_id": task.id,
            "status": task.status.value,
            "terminal": task.status.value in _TERMINAL or base.terminal,
            "last_activity": max(cp.checkpointed_at, task.updated_at),
            "blocker": blocker,
            "assignments": tuple(
                AssignmentView(
                    agent_id=p.agent_id,
                    role=p.role,
                    planned_provider=p.model_selection.provider,
                    planned_model=p.model_selection.model,
                    current_stage=_CURRENT_ROLE.get(task.status) is p.role and not base.terminal,
                )
                for p in dispatch.phases
            ),
            "timeline": timeline,
            "runs": _read_runs(native, task.id),
            "documents": base.documents + docs,
            "candidate_revision": cp.candidate_revision or projection.tasks[0].candidate_revision,
        }
    )


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
