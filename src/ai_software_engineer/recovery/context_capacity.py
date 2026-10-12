"""Read-only recovery of exact legacy terminal Context overflow before invocation.

The observation is made now. It never manufactures the missing historical Run,
request, final provider input count, stop record or model outcome.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field, StrictInt, TypeAdapter
from pymysql.cursors import DictCursor

from ai_software_engineer.agents import FileModelRouteAttemptStore
from ai_software_engineer.agents.fallback import model_route_root
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.context.execution_baseline import (
    ExecutionBaselineContext,
    parse_execution_baseline_context,
)
from ai_software_engineer.context.models import ContextBundle
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    Task,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.execution_baseline import BaselineInputMode
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.read_record_scope import recovery_record_read_scope
from ai_software_engineer.recovery.baseline_source import (
    RecoveryBaselineEpoch,
    read_recovery_baseline_epochs,
)
from ai_software_engineer.recovery.models import (
    ContextCapacityRecoveryInput,
    RecoveryRejected,
    RecoveryScope,
    digest,
)
from ai_software_engineer.recovery.native import (
    NativeRecoverySource,
    NativeRecoverySourceReader,
    _parent,
    _require_native_active,
    read_approved_stages,
)
from ai_software_engineer.recovery.workspace_snapshot import _existing_task_scope
from ai_software_engineer.redaction import source_inspection_scope
from ai_software_engineer.repository_workspace import RepositoryWorkspaceManifest
from ai_software_engineer.store.mysql_repository import (
    _decode_task,
    _non_negative_int,
    _text,
    open_mysql_connection,
)
from ai_software_engineer.team_workspace import TeamWorkspace, _read_regular, _reject_symlinks
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    RoleQueueAdmission,
    _decode,
)
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.mysql import _RISK_RANK, MySqlPersistentWorkQueue
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard

LEGACY_CAPACITY_REASON = (
    "BUDGET_EXHAUSTED: Required context exceeds the configured input budget; no automatic retry."
)
LEGACY_CAPACITY_SUMMARY = LEGACY_CAPACITY_REASON.removeprefix("BUDGET_EXHAUSTED: ")


class CapacityContextClaim(DomainModel):
    task_id: NonEmptyStr
    work_item_id: NonEmptyStr
    lease_id: NonEmptyStr
    assignment_id: NonEmptyStr
    role: AgentRole
    attempt: StrictInt = Field(ge=1)
    dispatch_sequence: StrictInt = Field(ge=0)
    checkpoint_sequence: StrictInt = Field(ge=0)


@dataclass(frozen=True)
class ValidatedCapacityContext:
    claim: CapacityContextClaim
    complete: ExecutionBaselineContext
    available_input_tokens: int


def validate_capacity_context(
    *,
    task: Task,
    context: ContextBundle,
    epoch: RecoveryBaselineEpoch,
    terminal_at: datetime,
) -> ValidatedCapacityContext:
    """Pure validation of actual saved Context; no reconstructed AgentRequest."""
    binding = epoch.binding
    binding.require_task(task)
    if (
        binding.input_mode is not BaselineInputMode.CODER_REAPPLY
        or context.task_id != task.id
        or context.role is not AgentRole.CODER
        or context.attempt != task.attempts
        or context.attempt < epoch.minimum_attempt
        or context.source_revision != binding.execution_source_revision
        or not binding.completed_at <= context.built_at <= terminal_at
    ):
        raise ValueError("capacity Context differs from the latest execution epoch")
    for section in context.sections:
        if hashlib.sha256(section.content.encode()).hexdigest() != section.sha256:
            raise ValueError("capacity Context section changed")
    sections = tuple(s for s in context.sections if s.name == "execution.baseline")
    claims = tuple(s for s in context.sections if s.name == "source:execution.claim")
    if len(sections) != 1 or len(claims) != 1 or sections[0].truncated or claims[0].truncated:
        raise ValueError("capacity Context lacks exact complete baseline or claim")
    complete = parse_execution_baseline_context(sections[0].content)
    if not isinstance(complete, ExecutionBaselineContext) or complete.binding != binding:
        raise ValueError("capacity recovery requires its complete exact reapplication patch")
    claim = CapacityContextClaim.model_validate_json(claims[0].content)
    if (
        (claim.task_id, claim.role, claim.attempt) != (task.id, AgentRole.CODER, task.attempts)
        or claims[0].uri != "claim://" + claim.lease_id
        or sections[0].uri != "baseline://" + binding.binding_sha256
        or claim.checkpoint_sequence < binding.prior_task_revision
    ):
        raise ValueError("capacity Context claim or baseline identity differs")
    available = context.budget.max_input_tokens - context.budget.reserved_output_tokens
    if available < 1 or context.budget.used_input_tokens <= available:
        raise ValueError("saved Context does not establish input capacity overflow")
    return ValidatedCapacityContext(claim, complete, available)


class LegacyContextCapacitySourceReader:
    """Separate no-start reader; ordinary failed-route recovery stays strict."""

    def __init__(self, config: ProductionConfig, environment: Mapping[str, str]) -> None:
        self.config, self.environment = config, dict(environment)
        self.native = NativeRecoverySourceReader(config, environment)

    @source_inspection_scope()
    @recovery_record_read_scope()
    def discover(self, scope: RecoveryScope) -> NativeRecoverySource:
        try:
            return self._inspect(scope, None)
        except Exception as error:
            raise RecoveryRejected("上下文容量恢复的原执行、基线或保留进度记录尚不完整") from error

    @source_inspection_scope()
    @recovery_record_read_scope()
    def inspect(self, scope: RecoveryScope, receipt_sha256: str) -> NativeRecoverySource:
        try:
            team = self._team(scope)
            _, repository = team.project_registry().locate_repository(scope.repository_id)
            receipt = KnowledgeRecordStore(
                repository.root / "state/delivery-preflight", read_only=True
            ).get("context-capacity-receipts", receipt_sha256, ContextCapacityReceipt)
            receipt.validate_integrity()
            return self._inspect(scope, receipt)
        except Exception as error:
            raise RecoveryRejected(
                "上下文容量恢复的精确记录已变化或缺失; 原现场与历史仍保留"
            ) from error

    def _team(self, scope: RecoveryScope) -> TeamWorkspace:
        if scope.team_id != self.config.team_id:
            raise ValueError("capacity team mismatch")
        return TeamWorkspace.initialize(
            self.config.platform_root,
            team_id=scope.team_id,
            name=self.config.team_name,
            read_only=True,
        )

    def _inspect(
        self, scope: RecoveryScope, receipt: ContextCapacityReceipt | None
    ) -> NativeRecoverySource:
        team = self._team(scope)
        project, repository = team.project_registry().locate_repository(scope.repository_id)
        _require_native_active(project, scope.delivery_id)
        root = repository.root
        manifest = RepositoryWorkspaceManifest.model_validate_json(
            _read_regular(root / "workspace.json", 64_000)
        )
        manifest.validate_binding(root)
        if (
            manifest.repository_id != scope.repository_id
            or manifest.repository_root != scope.repository_root
        ):
            raise ValueError("capacity repository binding differs")
        journal = FileProjectDeliveryCheckpointStore(
            root / "state/project-deliveries", read_only=True
        )
        history = journal.list(scope.delivery_id)
        cp = history[-1]
        if (
            cp.stage is not DeliveryStage.BLOCKED
            or cp.task_status is not TaskStatus.BLOCKED
            or cp.candidate_revision
        ):
            raise ValueError(
                "capacity recovery requires original terminal pre-candidate checkpoint"
            )
        guard = WorkerExecutionGuard()
        with _existing_task_scope(root / "state/queue-worker-locks", cp.task_id or "", guard):
            facts = self.native._sql(
                cp, history, sidecar=root, project_id=project.manifest.project_id
            )
            task, revision, dispatch, planner, events = facts
            terminal = events[-1]
            if (
                terminal.reason != LEGACY_CAPACITY_REASON
                or terminal.from_status is not TaskStatus.IMPLEMENTING
            ):
                raise ValueError("not an exact legacy no-start Context capacity terminal")
            epochs = read_recovery_baseline_epochs(
                root, task, scope, project_id=project.manifest.project_id
            )
            if not epochs:
                raise ValueError("capacity recovery requires a verified latest retained baseline")
            stages = read_approved_stages(
                self.config, root, scope, cp, task, planner, current_dispatch=dispatch
            )
            context, value = self._context(root, task, epochs[-1], terminal.occurred_at, receipt)
            baseline_store = FileExecutionBaselineStore(
                root / "state/execution-baselines" / task.id, read_only=True
            )
            baseline_plan = baseline_store.plan(epochs[-1].binding.plan_sha256)
            if baseline_plan.complete_capture.patch != value.complete.complete_patch:
                raise ValueError(
                    "saved Context differs from complete store-verified retained patch"
                )
            claim = self._claim(
                scope, task, revision, dispatch.dispatch_sha256, value.claim, context, epochs
            )
            self._require_no_start(root, task, claim)
            policy_sections = tuple(s for s in context.sections if s.name == "policy")
            if len(policy_sections) != 1 or policy_sections[0].truncated:
                raise ValueError("capacity Context lacks original permissions")
            policy = json.loads(policy_sections[0].content)
            denied = TypeAdapter(tuple[str, ...]).validate_python(policy.pop("denied_paths"))
            permissions = AgentPermissions.model_validate(policy)
            if (
                permissions.can_merge
                or permissions.can_change_state
                or task.constraints is None
                or permissions.write_paths != task.constraints.allowed_paths
            ):
                raise ValueError("capacity permissions differ from frozen Task")
            manager = GitWorktreeManager(
                scope.repository_root,
                Path(self.config.platform_root) / "worktrees" / scope.repository_id,
                branch_names={task.id: task.branch_name},
            )
            old = manager.recover(
                WorktreeSpec(
                    task_id=task.id,
                    role=AgentRole.CODER,
                    attempt=1,
                    source_revision=context.source_revision,
                )
            )
            current_capture = manager.capture_changes(
                old,
                permissions,
                denied_paths=denied,
                base_revision=epochs[-1].binding.execution_base_ref,
            )
            if (
                current_capture.patch
                or current_capture.changed_paths
                or str(old.path) != epochs[-1].binding.worktree_path
            ):
                raise ValueError("capacity recovery must retain its exact clean execution worktree")
            parent_id, parent_sha = _parent(team, cp, stages.approval)
            observed = ContextCapacityReceipt(
                origin="legacy_terminal_context",
                task_id=task.id,
                task_sha256=digest(task.to_wire()),
                task_intent_sha256=task_intent_sha256(task),
                task_revision=revision,
                work_item_id=claim.work_item.id,
                lease_id=claim.lease.id,
                assignment_id=claim.assignment.id,
                claim_sha256=digest(claim.to_wire()),
                dispatch_sequence=claim.work_item.dispatch_sequence,
                checkpoint_sequence=claim.work_item.checkpoint_sequence,
                role=AgentRole.CODER,
                attempt=task.attempts,
                source_revision=context.source_revision,
                context_manifest_id=context.context_id,
                context_sha256=digest(context.to_wire()),
                max_input_tokens=value.available_input_tokens,
                context_input_tokens=context.budget.used_input_tokens,
                execution_baseline_sha256=epochs[-1].binding.binding_sha256,
                observed_at=receipt.observed_at if receipt else datetime.now(UTC),
                receipt_sha256="0" * 64,
            )
            observed = observed.model_copy(
                update={
                    "receipt_sha256": digest(
                        observed.model_dump(mode="json", exclude={"receipt_sha256"})
                    )
                }
            )
            observed.validate_integrity()
            if receipt is not None and observed != receipt:
                raise ValueError("capacity observation no longer matches exact current facts")
            from ai_software_engineer.recovery.models import RecoverySource

            source = RecoverySource(
                scope=scope,
                task_id=task.id,
                task_revision=revision,
                task_sha256=digest(task.to_wire()),
                checkpoint_sha256=cp.checkpoint_sha256,
                dispatch_sha256=dispatch.dispatch_sha256,
                preparation_sha256=stages.preparation.preparation_sha256,
                product_spec_sha256=stages.product.product_spec_sha256,
                approval_sha256=stages.approval.approval_sha256,
                technical_design_sha256=stages.design.technical_design_sha256,
                execution_plan_sha256=stages.plan.execution_plan_sha256,
                failed_context_id=context.context_id,
                base_revision=task.base_ref,
                execution_baseline_sha256=epochs[-1].binding.binding_sha256,
                execution_base_revision=epochs[-1].binding.execution_base_ref,
                context_capacity_receipt_sha256=observed.receipt_sha256,
                parent_delivery_id=parent_id,
                parent_checkpoint_sha256=parent_sha,
            )
            result = NativeRecoverySource(
                source,
                permissions,
                denied,
                stages.preparation,
                stages.product,
                stages.approval,
                stages.design,
                stages.plan,
                stages.request,
                task,
                context.source_revision,
                capacity_receipt=observed,
                capacity_input=ContextCapacityRecoveryInput(
                    execution_baseline_sha256=epochs[-1].binding.binding_sha256,
                    retained_patch=epochs[-1].binding.retained_patch,
                    patch=value.complete.complete_patch,
                ),
            )
            if (
                journal.list(scope.delivery_id) != history
                or self.native._sql(
                    cp, history, sidecar=root, project_id=project.manifest.project_id
                )
                != facts
                or read_recovery_baseline_epochs(
                    root, task, scope, project_id=project.manifest.project_id
                )
                != epochs
            ):
                raise ValueError("capacity native facts changed while observing")
            if read_approved_stages(
                self.config, root, scope, cp, task, planner, current_dispatch=dispatch
            ) != stages or _parent(team, cp, stages.approval) != (parent_id, parent_sha):
                raise ValueError("capacity approved Requirement changed while observing")
            if (
                self._claim(
                    scope, task, revision, dispatch.dispatch_sha256, value.claim, context, epochs
                )
                != claim
            ):
                raise ValueError("capacity queue changed while observing")
            self._require_no_start(root, task, claim)
            manager.verify_capture(current_capture, permissions, denied_paths=denied)
            return result

    def _context(
        self,
        root: Path,
        task: Task,
        epoch: RecoveryBaselineEpoch,
        terminal_at: datetime,
        receipt: ContextCapacityReceipt | None,
    ) -> tuple[ContextBundle, ValidatedCapacityContext]:
        contexts = root / "contexts"
        _reject_symlinks(contexts)
        store = FileContextStore(contexts, read_only=True)
        candidates = []
        for path in sorted(contexts.glob("*.json")):
            _read_regular(path, 8_000_000)
            context = store.get(path.stem)
            if (context.task_id, context.role, context.attempt) != (
                task.id,
                AgentRole.CODER,
                task.attempts,
            ):
                continue
            if receipt is not None and context.context_id != receipt.context_manifest_id:
                continue
            available = context.budget.max_input_tokens - context.budget.reserved_output_tokens
            if context.budget.used_input_tokens > available:
                candidates.append(
                    (
                        context,
                        validate_capacity_context(
                            task=task, context=context, epoch=epoch, terminal_at=terminal_at
                        ),
                    )
                )
        if len(candidates) != 1:
            raise ValueError("exact overflowing legacy Context is missing or ambiguous")
        return candidates[0]

    def _claim(
        self,
        scope: RecoveryScope,
        task: Task,
        revision: int,
        allocation_sha256: str,
        expected: CapacityContextClaim,
        context: ContextBundle,
        epochs: tuple[RecoveryBaselineEpoch, ...],
    ) -> QueueClaim:
        connection = open_mysql_connection(self.config.require_mysql_dsn(self.environment))
        try:
            with connection.cursor(DictCursor) as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                cursor.execute("SELECT * FROM tasks WHERE id=%s", (task.id,))
                task_row = cursor.fetchone()
                if (
                    task_row is None
                    or _decode_task(task.id, _text(task_row, "payload_json")) != task
                    or _non_negative_int(task_row, "revision") != revision
                ):
                    raise ValueError("capacity Task changed during queue observation")
                cursor.execute(
                    "SELECT lease_id FROM work_queue_claims WHERE task_id=%s AND state='ACTIVE'",
                    (task.id,),
                )
                if cursor.fetchone() is not None:
                    raise ValueError("capacity Task has an active claim")
                cursor.execute(
                    "SELECT * FROM work_queue_items WHERE task_id=%s ORDER BY id", (task.id,)
                )
                rows = cursor.fetchall()
                items = tuple(_closed_item(row) for row in rows)
                if not items or any(
                    item.task_id != task.id
                    or item.repository_id != scope.repository_id
                    or item.status is not WorkItemStatus.CLOSED
                    for item in items
                ):
                    raise ValueError("capacity queue is not fully closed")
                cursor.execute(
                    "SELECT * FROM work_queue_claims WHERE lease_id=%s", (expected.lease_id,)
                )
                row = cursor.fetchone()
                if (
                    row is None
                    or row["state"] not in {"RELEASED", "EXPIRED"}
                    or row["ended_at"] is None
                ):
                    raise ValueError("capacity original claim has no ended record")
                cursor.execute(
                    "SELECT * FROM work_queue_events "
                    "WHERE lease_id=%s AND event_type='CLAIMED' ORDER BY sequence",
                    (expected.lease_id,),
                )
                events = cursor.fetchall()
                if len(events) != 1:
                    raise ValueError("capacity original claim event missing or ambiguous")
                event = events[0]
                payload = json.loads(_text(event, "payload_json"))
                claim = QueueClaim.model_validate(
                    {
                        "work_item": payload["work_item"],
                        "assignment": json.loads(_text(row, "assignment_json")),
                        "lease": json.loads(_text(row, "lease_json")),
                        "model_selection": json.loads(_text(row, "model_selection_json")),
                        "worker_id": row["worker_id"],
                        "claimed_at": event["occurred_at"],
                    }
                )
                TypeAdapter(StageSha256).validate_python(row["owner_token_sha256"])
                if (
                    row["agent_id"] != claim.lease.agent_id
                    or _non_negative_int(row, "capacity_units") != claim.lease.capacity_units
                    or MySqlPersistentWorkQueue._parse_time(_text(row, "acquired_at"))
                    != claim.lease.acquired_at
                    or MySqlPersistentWorkQueue._parse_time(_text(row, "expires_at"))
                    != claim.lease.expires_at
                    or not claim.lease.acquired_at
                    <= MySqlPersistentWorkQueue._parse_time(_text(row, "last_heartbeat_at"))
                    <= MySqlPersistentWorkQueue._parse_time(_text(row, "ended_at"))
                    or MySqlPersistentWorkQueue._parse_time(_text(row, "ended_at"))
                    < context.built_at
                ):
                    raise ValueError("capacity ended claim record differs from original allocation")
                item = claim.work_item
                if (
                    (
                        item.task_id,
                        item.id,
                        claim.lease.id,
                        claim.assignment.id,
                        item.role,
                        item.attempt,
                        item.dispatch_sequence,
                        item.checkpoint_sequence,
                    )
                    != (
                        expected.task_id,
                        expected.work_item_id,
                        expected.lease_id,
                        expected.assignment_id,
                        expected.role,
                        expected.attempt,
                        expected.dispatch_sequence,
                        expected.checkpoint_sequence,
                    )
                    or item.repository_id != scope.repository_id
                    or not claim.claimed_at <= context.built_at
                    or item.checkpoint_sequence >= revision
                    or row["task_id"] != task.id
                    or row["work_item_id"] != item.id
                    or row["lease_id"] != claim.lease.id
                    or event["work_item_id"] != item.id
                    or event["lease_id"] != claim.lease.id
                    or event["from_status"] not in {"READY", "RETRY_SCHEDULED"}
                    or event["to_status"] != "LEASED"
                ):
                    raise ValueError("capacity original claim differs from saved Context")
                matched = tuple(current for current in items if current.id == item.id)
                if len(matched) != 1 or (
                    matched[0].attempt,
                    matched[0].role,
                    matched[0].checkpoint_sequence,
                    matched[0].dispatch_sequence,
                ) != (item.attempt, item.role, item.checkpoint_sequence, item.dispatch_sequence):
                    raise ValueError("capacity closed work item differs from original claim")
                cursor.execute(
                    "SELECT id,task_id,payload_json,sha256 FROM work_queue_admissions WHERE id=%s",
                    (task.id,),
                )
                admitted = cursor.fetchone()
                if admitted is None:
                    raise ValueError("capacity admission missing")
                admission = _decode(admitted, RoleQueueAdmission)
                if (
                    admission.repository_id != scope.repository_id
                    or admission.allocation_sha256 != allocation_sha256
                ):
                    raise ValueError("capacity original admission differs")
                cursor.execute(
                    "SELECT id,task_id,payload_json,sha256 FROM work_queue_execution_baselines "
                    "WHERE task_id=%s",
                    (task.id,),
                )
                consumed = tuple(
                    sorted(
                        (
                            _decode(record, BaselineQueueConsumption).binding
                            for record in cursor.fetchall()
                        ),
                        key=lambda binding: binding.sequence,
                    )
                )
                if consumed != tuple(epoch.binding for epoch in epochs):
                    raise ValueError("capacity queue baseline history differs from verified store")
                cursor.execute(
                    "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
                    "WHERE task_id=%s ORDER BY id",
                    (task.id,),
                )
                published = tuple(
                    _decode(record, AcceptedRoleArtifact) for record in cursor.fetchall()
                )
                if any(record.work_item_id == item.id for record in published):
                    raise ValueError("capacity work item already published an artifact")
                return claim
        finally:
            connection.rollback()
            connection.close()

    @staticmethod
    def _require_no_start(root: Path, task: Task, claim: QueueClaim) -> None:
        invocation_root = root / "state/invocations"
        _reject_symlinks(invocation_root)
        if invocation_root.exists():
            records = KnowledgeRecordStore(invocation_root, read_only=True)
            for start in records.list("invocation-starts", DeliveryInvocationStart):
                start.validate_integrity()
                if start.work_item_id == claim.work_item.id or (
                    start.request.task_id,
                    start.request.role,
                    start.request.attempt,
                ) == (task.id, AgentRole.CODER, task.attempts):
                    raise ValueError("capacity original invocation has a durable start")
            for outcome in records.list("invocation-outcomes", DeliveryInvocationOutcome):
                outcome.validate_integrity()
                if outcome.start.work_item_id == claim.work_item.id or (
                    outcome.result.task_id,
                    outcome.result.role,
                    outcome.result.attempt,
                ) == (task.id, AgentRole.CODER, task.attempts):
                    raise ValueError("capacity original invocation has a durable outcome")
        routes_root = model_route_root(root)
        _reject_symlinks(routes_root)
        if routes_root.exists():
            routes = FileModelRouteAttemptStore(routes_root, read_only=True)
            for directory in sorted(routes_root.iterdir()):
                _reject_symlinks(directory)
                if not directory.is_dir():
                    raise ValueError("capacity route ledger contains unsafe entry")
                for path in directory.glob("*.json"):
                    _read_regular(path, 8_000_000)
                run_id = TypeAdapter(RunId).validate_python(directory.name)
                for route in routes.list_for_run(run_id):
                    route.validate_integrity()
                    if (route.task_id, route.role, route.result.attempt) == (
                        task.id,
                        AgentRole.CODER,
                        task.attempts,
                    ):
                        raise ValueError("capacity original invocation has a provider route")
        capture_root = root / "state/continuations" / task.id
        _reject_symlinks(capture_root)
        if capture_root.exists():
            ledger = FileContinuationStore(capture_root, task_id=task.id)
            for path in sorted(capture_root.glob("capture-start-*.json")):
                capture = ledger.capture_start(path.stem.removeprefix("capture-start-"))
                capture.validate_integrity()
                if (
                    capture.claim.work_item.id == claim.work_item.id
                    or capture.request.attempt == task.attempts
                ):
                    raise ValueError("capacity original invocation has execution capture")
            for path in sorted(capture_root.glob("capture-stop-*.json")):
                run_id = path.stem.removeprefix("capture-stop-")
                captured_stop = ledger.capture_stop(run_id)
                captured_stop.validate_integrity()
                captured_start = ledger.capture_start(run_id)
                if captured_start.request.attempt == task.attempts:
                    raise ValueError("capacity original invocation has a stop record")


def _closed_item(row: Mapping[str, object]) -> QueuedWorkItem:
    """Validate searchable queue columns and typed payload before absence checks."""
    item = MySqlPersistentWorkQueue._decode_item(row)
    if (
        _text(row, "task_id") != item.task_id
        or _text(row, "repository_id") != item.repository_id
        or _text(row, "status") != item.status.value
        or _text(row, "role") != item.role.value
        or _non_negative_int(row, "attempt") != item.attempt
        or _non_negative_int(row, "checkpoint_sequence") != item.checkpoint_sequence
        or _non_negative_int(row, "priority") != item.priority
        or _non_negative_int(row, "risk_rank") != _RISK_RANK[item.risk.value]
        or MySqlPersistentWorkQueue._parse_time(_text(row, "created_at")) != item.created_at
        or MySqlPersistentWorkQueue._parse_time(_text(row, "updated_at")) != item.updated_at
        or (
            (row["available_at"] is None) != (item.available_at is None)
            or (
                row["available_at"] is not None
                and MySqlPersistentWorkQueue._parse_time(_text(row, "available_at"))
                != item.available_at
            )
        )
    ):
        raise ValueError("capacity queue columns differ from its durable payload")
    return item
