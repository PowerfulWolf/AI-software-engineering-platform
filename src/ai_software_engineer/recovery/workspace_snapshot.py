"""Read-only audit of a terminal Coder workspace, without reviving its old Task.

An excluded local environment is retained as no-follow metadata in the original
workspace. It is never a recovery input, an execution cache, or retry authority.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter
from pymysql.cursors import DictCursor

from ai_software_engineer.agents import FileModelRouteAttemptStore, ModelRouteAttempt
from ai_software_engineer.agents.fallback import RouteAttemptOutcome, model_route_root
from ai_software_engineer.agents.models import AgentRunStatus
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    CoderProgressArtifact,
    Task,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.git.mutation import (
    WorkspaceMutationInventory,
    capture_mutation_inventory,
    changed_mutation_paths,
    is_execution_cache_path,
)
from ai_software_engineer.git.policy import is_protected_rule_path
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_models import (
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import (
    FileContinuationStore,
    _open_directory,
)
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.models import (
    CapturedChanges,
    RecoveryRejected,
    RecoveryScopeSupplement,
    RecoverySource,
    digest,
)
from ai_software_engineer.recovery.workspace_records import (
    RecoveryExcludedPath,
    RecoveryWorkspaceScope,
    RecoveryWorkspaceSnapshot,
)
from ai_software_engineer.store.mysql_repository import (
    _decode_event,
    _decode_task,
    _non_negative_int,
    _text,
    open_mysql_connection,
)
from ai_software_engineer.team_workspace import TeamWorkspace, _reject_symlinks
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
    _decode,
    record_digest,
)
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.mysql import _RISK_RANK
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard

if TYPE_CHECKING:
    from ai_software_engineer.recovery.native import NativeRecoverySource


@dataclass(frozen=True)
class TerminalWorkspaceFacts:
    scope: RecoveryWorkspaceScope
    task: Task
    task_revision: int
    events: tuple[StateEvent, ...]
    start: ExecutionCaptureStart
    stop: ExecutionCaptureStop
    invocation_start: DeliveryInvocationStart
    invocation_outcome: DeliveryInvocationOutcome
    historical_claim: QueueClaim
    step: QueuedRoleStep
    current_item: QueuedWorkItem
    routes: tuple[ModelRouteAttempt, ...]
    accepted: tuple[AcceptedRoleArtifact, ...] = ()
    claim_record_sha256: str | None = None


@dataclass(frozen=True)
class TerminalWorkspaceObservation:
    inventory_after: WorkspaceMutationInventory
    ignored_paths: tuple[str, ...]
    tracked_environment_paths: tuple[str, ...]
    task_lock_held: bool
    process_group_stopped: bool
    observed_at: datetime


def _require(condition: bool) -> None:
    if not condition:
        raise RecoveryRejected("终态开发现场的完整记录不一致; 原任务、文件和审计历史均已保留")


def _permitted(path: str, patterns: tuple[str, ...], denied: tuple[str, ...]) -> bool:
    return (
        not is_protected_rule_path(path)
        and not any(part.casefold() == ".git" for part in path.split("/"))
        and not any(fnmatchcase(path, pattern) for pattern in denied)
        and any(fnmatchcase(path, pattern) for pattern in patterns)
    )


def _capture_authority(
    source: RecoverySource,
    original: AgentPermissions,
    approved: AgentPermissions,
    denied: tuple[str, ...],
    supplement: RecoveryScopeSupplement | None,
) -> None:
    """Keep the historical request intact; audit only an exact approved expansion."""
    from ai_software_engineer.recovery.scope import expanded_recovery_permissions

    if supplement is not None:
        supplement = RecoveryScopeSupplement.model_validate(supplement.to_wire())
        supplement.validate_integrity()
        _require(
            supplement.scope == source.scope
            and supplement.task_id == source.task_id
            and supplement.task_revision == source.task_revision
            and supplement.checkpoint_sha256 == source.checkpoint_sha256
            and supplement.base_revision == source.effective_base_revision
            and supplement.permissions_sha256 == digest(original.to_wire())
            and supplement.denied_paths_sha256 == digest(denied)
            and all(
                _permitted(path, ("**",), denied) and not path.startswith(".venv/")
                for path in supplement.paths
            )
        )
    _require(approved == expanded_recovery_permissions(original, supplement))


def validate_terminal_workspace_snapshot(
    *,
    source: RecoverySource,
    permissions: AgentPermissions,
    denied_paths: tuple[str, ...],
    capture: CapturedChanges,
    facts: TerminalWorkspaceFacts,
    observation: TerminalWorkspaceObservation,
    scope_supplement: RecoveryScopeSupplement | None = None,
) -> RecoveryWorkspaceSnapshot:
    """Pure validation: no process, SQL, filesystem, Task or approval mutation."""
    source = RecoverySource.model_validate(source.to_wire())
    permissions = AgentPermissions.model_validate(permissions.to_wire())
    capture = CapturedChanges.model_validate(capture.to_wire())
    task = Task.model_validate(facts.task.to_wire())
    start = ExecutionCaptureStart.model_validate(facts.start.to_wire())
    stop = ExecutionCaptureStop.model_validate(facts.stop.to_wire())
    start.validate_integrity()
    stop.validate_integrity()
    invocation = DeliveryInvocationStart.model_validate(facts.invocation_start.to_wire())
    outcome = DeliveryInvocationOutcome.model_validate(facts.invocation_outcome.to_wire())
    invocation.validate_integrity()
    outcome.validate_integrity()
    claim = QueueClaim.model_validate(facts.historical_claim.to_wire())
    step = QueuedRoleStep.model_validate(facts.step.to_wire())
    item = QueuedWorkItem.model_validate(facts.current_item.to_wire())
    request, policy = start.request, task.interruption_continuation_policy
    _capture_authority(source, request.permissions, permissions, denied_paths, scope_supplement)
    scope = RecoveryWorkspaceScope.model_validate(facts.scope.to_wire())
    _require(
        observation.task_lock_held
        and observation.process_group_stopped
        and task.status is TaskStatus.BLOCKED
        and task.id == source.task_id == request.task_id
        and task.repository == source.scope.repository_root
        and digest(task.to_wire()) == source.task_sha256
        and task.base_ref == source.base_revision
        and facts.task_revision == source.task_revision == start.task_revision + 1
        and task.attempts == request.attempt
        and policy is not None
        and policy.policy_sha256 == start.policy_sha256
        and task_intent_sha256(task) == start.task_intent_sha256
        and denied_paths == (task.constraints.denied_paths if task.constraints else ())
        and request.role is AgentRole.CODER
        and request.run_id == source.failed_run_id
        and request.context_manifest_id == source.failed_context_id
        and (
            (
                source.execution_baseline_sha256 is None
                and request.source_revision == source.base_revision
            )
            or (
                source.execution_baseline_sha256 is not None
                and request.execution_base_ref == source.effective_base_revision
            )
        )
        and request.execution_baseline_sha256 == source.execution_baseline_sha256
        and scope.team_id == source.scope.team_id
        and scope.repository_id == source.scope.repository_id
        and scope.requirement_id == source.scope.delivery_id
        and scope.dispatch_sha256 == source.dispatch_sha256
        and start.scope.to_wire() == scope.to_wire()
        and stop.task_id == task.id
        and stop.run_id == request.run_id
        and stop.capture_start_sha256 == start.start_sha256
        and not stop.output_present
        and outcome.start == invocation
        and invocation.request == request
        and outcome.result.status is not AgentRunStatus.SUCCEEDED
        and outcome.result.artifact is None
        and outcome.result.error is not None
        # The original executor stop and the later admission failure are separate
        # facts. A real timeout can become POLICY_VIOLATION when sealing mutations.
        # Never rewrite either; the exact final route below authenticates outcome.
        and stop.original_error_code is not None
    )
    recorded = start.claim
    if facts.claim_record_sha256 is not None:
        TypeAdapter(Sha256).validate_python(facts.claim_record_sha256)
    _require(
        claim.assignment == recorded.assignment
        and claim.model_selection == recorded.model_selection
        and claim.lease.model_dump(exclude={"expires_at"})
        == recorded.lease.model_dump(exclude={"expires_at"})
        and claim.work_item == recorded.work_item
        and claim.worker_id == recorded.worker_id
        and claim.claimed_at == recorded.claimed_at
        and invocation.lease_id == claim.lease.id
        and invocation.work_item_id == claim.work_item.id == item.id == step.work_item.id
        and invocation.checkpoint_sequence
        == claim.work_item.checkpoint_sequence
        == item.checkpoint_sequence
        == step.boundary.checkpoint_sequence
        and step.allocation_sha256 == source.dispatch_sha256
        and step.boundary.task_id == task.id
        and step.boundary.role is AgentRole.CODER
        and step.boundary.attempt == request.attempt
        and step.boundary.source_revision == request.source_revision
        and step.work_item.repository_id == claim.work_item.repository_id == scope.repository_id
        and step.work_item.repository_scopes
        == claim.work_item.repository_scopes
        == (task.repository,)
        and step.work_item.parent_work_item_id == claim.work_item.parent_work_item_id
        and item.status is WorkItemStatus.CLOSED
        and item.model_dump(
            exclude={"status", "updated_at", "wait_reason", "wait_disposition", "available_at"}
        )
        == claim.work_item.model_dump(
            exclude={"status", "updated_at", "wait_reason", "wait_disposition", "available_at"}
        )
        and not any(accepted.run_id == request.run_id for accepted in facts.accepted)
    )
    events = tuple(StateEvent.model_validate(event.to_wire()) for event in facts.events)
    _require(len(events) == facts.task_revision and bool(events))
    previous = TaskStatus.NEW
    previous_time = task.created_at
    for event in events:
        _require(
            event.task_id == task.id
            and event.from_status is previous
            and event.occurred_at >= previous_time
            and event.attempt <= task.attempts
        )
        previous, previous_time = event.to_status, event.occurred_at
    terminal = events[-1]
    _require(
        terminal.from_status is TaskStatus.IMPLEMENTING
        and terminal.to_status is TaskStatus.BLOCKED
        and terminal.attempt == request.attempt
        and terminal.source_revision == request.source_revision
        and terminal.occurred_at == task.updated_at
        and claim.claimed_at <= invocation.started_at <= start.started_at
        and start.started_at <= stop.process_stop.stopped_at <= terminal.occurred_at
        and terminal.occurred_at <= observation.observed_at
        and bool(facts.routes)
    )
    previous_route_time = invocation.started_at
    for index, route in enumerate(facts.routes, 1):
        route = ModelRouteAttempt.model_validate(route.to_wire())
        route.validate_integrity()
        result = route.result
        _require(
            route.route_index == index
            and route.request_sha256 == digest(request.to_wire())
            and (
                result.run_id,
                result.task_id,
                result.role,
                result.attempt,
                result.source_revision,
                result.context_manifest_id,
            )
            == (
                request.run_id,
                request.task_id,
                request.role,
                request.attempt,
                request.source_revision,
                request.context_manifest_id,
            )
            and previous_route_time
            <= route.started_at
            <= route.completed_at
            <= terminal.occurred_at
            and route.outcome
            is (
                RouteAttemptOutcome.FAILED
                if index == len(facts.routes)
                else RouteAttemptOutcome.FALLBACK
            )
        )
        previous_route_time = route.completed_at
    _require(
        facts.routes[-1].result == outcome.result
        and facts.routes[-1].completed_at >= stop.process_stop.stopped_at
        and capture.task_id == task.id
        and capture.attempt == 1
        and capture.worktree_path == start.worktree_path
        and capture.source_revision == request.source_revision
        and capture.to_capture().effective_base_revision == source.effective_base_revision
    )
    before, after = start.inventory_before, observation.inventory_after
    observed = {file.path: file for file in after.files}
    captured = {file.path: file.sha256 for file in capture.files}
    for path, sha256 in captured.items():
        actual = observed.get(path)
        _require(
            actual is not None
            and actual.kind == "file"
            and actual.sha256 == sha256
            and _permitted(path, permissions.write_paths, denied_paths)
            and not path.startswith(".venv/")
        )
    environment = tuple(file for file in after.files if file.path.startswith(".venv/"))
    if environment:
        _require(
            not any(file.path == ".venv" or file.path.startswith(".venv/") for file in before.files)
            and not observation.tracked_environment_paths
            and tuple(file.path for file in environment) == observation.ignored_paths
            and all(file.kind in {"file", "symlink"} for file in environment)
        )
    environment_paths = {file.path for file in environment}
    for path in changed_mutation_paths(before, after):
        _require(_permitted(path, ("**",), denied_paths))
        actual = observed.get(path)
        if path in environment_paths:
            continue
        if is_execution_cache_path(path):
            _require(actual is None or actual.kind == "file")
            continue
        _require(path in captured and _permitted(path, permissions.write_paths, denied_paths))
    snapshot = RecoveryWorkspaceSnapshot.create(
        scope=scope,
        task_id=task.id,
        task_revision=facts.task_revision,
        task_sha256=source.task_sha256,
        task_intent_sha256=start.task_intent_sha256,
        run_id=request.run_id,
        context_manifest_id=request.context_manifest_id,
        worktree_path=start.worktree_path,
        source_revision=request.source_revision,
        effective_capture_base=capture.to_capture().effective_base_revision,
        execution_baseline_sha256=source.execution_baseline_sha256,
        capture_sha256=capture.capture_sha256,
        capture_start_sha256=start.start_sha256,
        capture_stop_sha256=stop.observation_sha256,
        invocation_start_sha256=invocation.start_sha256,
        invocation_outcome_sha256=outcome.outcome_sha256,
        claim_sha256=digest(claim.to_wire())
        if facts.claim_record_sha256 is None
        else digest({"claim": claim.to_wire(), "record_sha256": facts.claim_record_sha256}),
        step_sha256=record_digest(step),
        routes_sha256=digest([route.to_wire() for route in facts.routes]),
        inventory_before_sha256=before.sha256,
        inventory_after=after,
        inventory_after_sha256=after.sha256,
        excluded_paths=tuple(
            RecoveryExcludedPath.model_validate(
                {
                    "path": file.path,
                    "kind": file.kind,
                    "sha256": file.sha256,
                    "mode": file.mode,
                    "size": file.size,
                }
            )
            for file in environment
        ),
        stopped_at=stop.process_stop.stopped_at,
        blocked_at=terminal.occurred_at,
        # Stable durable anchor: a fresh observation must validate the same plan,
        # rather than changing its digest merely because the clock advanced.
        created_at=terminal.occurred_at,
    )
    snapshot.validate_integrity()
    return snapshot


def _terminal_sql_facts(
    cursor: DictCursor,
    source: RecoverySource,
    start: ExecutionCaptureStart,
) -> tuple[
    Task,
    int,
    tuple[StateEvent, ...],
    QueueClaim,
    QueuedRoleStep,
    QueuedWorkItem,
    tuple[AcceptedRoleArtifact, ...],
    str,
]:
    """One consistent SELECT-only snapshot; no queue constructor or authority lock."""
    cursor.execute("SELECT * FROM tasks WHERE id=%s", (source.task_id,))
    row = cursor.fetchone()
    _require(row is not None)
    assert row is not None
    task = _decode_task(source.task_id, _text(row, "payload_json"))
    revision = _non_negative_int(row, "revision")
    _require(
        _text(row, "id") == task.id
        and _text(row, "status") == task.status.value
        and MySqlRoleQueue._parse_time(_text(row, "created_at")) == task.created_at
        and MySqlRoleQueue._parse_time(_text(row, "updated_at")) == task.updated_at
    )
    cursor.execute("SELECT * FROM state_events WHERE task_id=%s ORDER BY revision", (task.id,))
    rows = tuple(cursor.fetchall())
    _require(tuple(row["revision"] for row in rows) == tuple(range(1, revision + 1)))
    events = tuple(_decode_event(_text(row, "payload_json")) for row in rows)
    _require(
        all(
            event.event_id == row["event_id"] and event.task_id == row["task_id"]
            for event, row in zip(events, rows, strict=True)
        )
    )
    cursor.execute(
        "SELECT lease_id FROM work_queue_claims WHERE task_id=%s AND state='ACTIVE'", (task.id,)
    )
    _require(cursor.fetchone() is None)
    cursor.execute(
        "SELECT id,task_id,payload_json,sha256 FROM work_queue_admissions WHERE id=%s", (task.id,)
    )
    row = cursor.fetchone()
    _require(row is not None)
    assert row is not None
    admission = _decode(row, RoleQueueAdmission)
    _require(
        admission.repository_id == source.scope.repository_id
        and admission.allocation_sha256 == source.dispatch_sha256
    )
    cursor.execute("SELECT * FROM work_queue_claims WHERE lease_id=%s", (start.claim.lease.id,))
    row = cursor.fetchone()
    _require(row is not None)
    assert row is not None
    cursor.execute(
        "SELECT * FROM work_queue_events "
        "WHERE lease_id=%s AND event_type='CLAIMED' ORDER BY sequence",
        (start.claim.lease.id,),
    )
    claims = tuple(cursor.fetchall())
    _require(len(claims) == 1)
    event = claims[0]
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
    _require(
        row["task_id"] == task.id
        and row["work_item_id"] == claim.work_item.id
        and row["lease_id"] == claim.lease.id
        and row["agent_id"] == claim.lease.agent_id
        and _non_negative_int(row, "capacity_units") == claim.lease.capacity_units
        and row["state"] in {"RELEASED", "EXPIRED"}
        and row["ended_at"] is not None
        and MySqlRoleQueue._parse_time(_text(row, "acquired_at")) == claim.lease.acquired_at
        and MySqlRoleQueue._parse_time(_text(row, "expires_at")) == claim.lease.expires_at
        and event["work_item_id"] == claim.work_item.id
        and event["lease_id"] == claim.lease.id
        and event["event_type"] == "CLAIMED"
        and event["to_status"] == claim.work_item.status.value
        and event["from_status"] in {"READY", "RETRY_SCHEDULED"}
    )
    TypeAdapter(Sha256).validate_python(row["owner_token_sha256"])
    _require(
        claim.lease.acquired_at
        <= MySqlRoleQueue._parse_time(_text(row, "last_heartbeat_at"))
        <= MySqlRoleQueue._parse_time(_text(row, "ended_at"))
    )
    claim_record_sha256 = digest({"claim_record": row, "claim_event": event})
    cursor.execute("SELECT * FROM work_queue_items WHERE task_id=%s ORDER BY id", (task.id,))
    items = []
    for item_row in cursor.fetchall():
        decoded = MySqlRoleQueue._decode_item(item_row)
        _require(
            item_row["task_id"] == decoded.task_id == task.id
            and item_row["repository_id"] == decoded.repository_id == source.scope.repository_id
            and item_row["status"] == decoded.status.value
            and item_row["role"] == decoded.role.value
            and _non_negative_int(item_row, "attempt") == decoded.attempt
            and _non_negative_int(item_row, "checkpoint_sequence") == decoded.checkpoint_sequence
            and _non_negative_int(item_row, "priority") == decoded.priority
            and _non_negative_int(item_row, "risk_rank") == _RISK_RANK[decoded.risk.value]
            and MySqlRoleQueue._parse_time(_text(item_row, "created_at")) == decoded.created_at
            and MySqlRoleQueue._parse_time(_text(item_row, "updated_at")) == decoded.updated_at
            and (
                (item_row["available_at"] is None and decoded.available_at is None)
                or (
                    item_row["available_at"] is not None
                    and MySqlRoleQueue._parse_time(_text(item_row, "available_at"))
                    == decoded.available_at
                )
            )
        )
        items.append(decoded)
    _require(
        bool(items)
        and all(item.task_id == task.id and item.status is WorkItemStatus.CLOSED for item in items)
    )
    matches = tuple(item for item in items if item.id == claim.work_item.id)
    _require(len(matches) == 1)
    item = matches[0]
    cursor.execute(
        "SELECT id,task_id,payload_json,sha256 FROM work_queue_steps WHERE id=%s", (item.id,)
    )
    row = cursor.fetchone()
    _require(row is not None)
    assert row is not None
    step = _decode(row, QueuedRoleStep)
    cursor.execute(
        "SELECT id,task_id,payload_json,sha256 FROM work_queue_execution_baselines "
        "WHERE task_id=%s",
        (task.id,),
    )
    baselines = tuple(
        sorted(
            (_decode(row, BaselineQueueConsumption) for row in cursor.fetchall()),
            key=lambda record: record.binding.sequence,
        )
    )
    previous_binding = None
    for baseline in baselines:
        binding = baseline.binding
        binding.require_task(task)
        binding.require_predecessor(previous_binding)
        _require(
            binding.scope.team_id == source.scope.team_id
            and binding.scope.project_id == start.scope.project_id
            and binding.scope.repository_id == source.scope.repository_id
            and binding.scope.repository_root == source.scope.repository_root
        )
        previous_binding = binding
    _require(
        (baselines[-1].binding.binding_sha256 if baselines else None)
        == source.execution_baseline_sha256
    )
    for baseline in baselines:
        if baseline.work_item_id != item.id or baseline.next_work_item_id != item.id:
            continue
        _require(record_digest(step) == baseline.prior_step_sha256)
        boundary = step.boundary
        step = step.model_copy(
            update={
                "boundary": RoleRunBoundary(
                    boundary.task_id,
                    boundary.role,
                    boundary.attempt,
                    boundary.checkpoint_sequence,
                    baseline.binding.execution_source_revision,
                )
            }
        )
        if baseline.binding.binding_sha256 == source.execution_baseline_sha256:
            break
    cursor.execute(
        "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
        "AND event_type='EXECUTION_BASELINE_REBOUND' AND sequence<%s "
        "ORDER BY sequence DESC LIMIT 1",
        (item.id, event["sequence"]),
    )
    rebound = cursor.fetchone()
    if rebound is not None:
        _require(
            json.loads(_text(rebound, "payload_json"))["detail"]["binding_sha256"]
            == source.execution_baseline_sha256
        )
    cursor.execute(
        "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
        "WHERE task_id=%s ORDER BY id",
        (task.id,),
    )
    accepted = tuple(_decode(row, AcceptedRoleArtifact) for row in cursor.fetchall())
    return task, revision, events, claim, step, item, accepted, claim_record_sha256


def _read_facts(
    config: ProductionConfig,
    environment: Mapping[str, str],
    original: NativeRecoverySource,
    sidecar: Path,
    scope: RecoveryWorkspaceScope,
) -> TerminalWorkspaceFacts:
    source = original.source
    continuation = FileContinuationStore(
        sidecar / "state/continuations" / source.task_id, task_id=source.task_id
    )
    start = continuation.capture_start(source.failed_run_id)
    stop = continuation.capture_stop(source.failed_run_id)
    invocation_root = sidecar / "state/invocations"
    _reject_symlinks(invocation_root)
    records = KnowledgeRecordStore(invocation_root, read_only=True)
    invocation = records.get("invocation-starts", start.claim.work_item.id, DeliveryInvocationStart)
    outcome = records.get(
        "invocation-outcomes", start.claim.work_item.id, DeliveryInvocationOutcome
    )
    routes = _read_routes(sidecar, source)
    with (
        closing(open_mysql_connection(config.require_mysql_dsn(environment))) as connection,
        connection.cursor(DictCursor) as cursor,
    ):
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
        task, revision, events, claim, step, item, accepted, claim_record_sha256 = (
            _terminal_sql_facts(cursor, source, start)
        )
    return TerminalWorkspaceFacts(
        scope,
        task,
        revision,
        events,
        start,
        stop,
        invocation,
        outcome,
        claim,
        step,
        item,
        routes,
        accepted,
        claim_record_sha256,
    )


def _read_routes(sidecar: Path, source: RecoverySource) -> tuple[ModelRouteAttempt, ...]:
    routes_root = model_route_root(sidecar)
    _reject_symlinks(routes_root)
    routes = FileModelRouteAttemptStore(routes_root, read_only=True).list_for_run(
        source.failed_run_id
    )
    _require(bool(routes))
    for index, route in enumerate(routes, 1):
        route.validate_integrity()
        _require(
            route.route_index == index
            and route.task_id == source.task_id
            and route.run_id == source.failed_run_id
            and route.role is AgentRole.CODER
            and route.result.context_manifest_id == source.failed_context_id
            and (index == len(routes) or route.outcome is RouteAttemptOutcome.FALLBACK)
        )
    return routes


def _observe(
    git: GitWorktreeManager, facts: TerminalWorkspaceFacts, guard: WorkerExecutionGuard
) -> TerminalWorkspaceObservation:
    NativeCoderContinuation._require_stopped(facts.stop.process_stop, facts.start.request)
    root = Path(facts.start.worktree_path)
    inventory = capture_mutation_inventory(root)
    environment = tuple(file.path for file in inventory.files if file.path.startswith(".venv/"))
    ignored: tuple[str, ...] = ()
    if environment:
        raw = git._run_git_bytes(
            ("check-ignore", "-z", "--stdin"),
            cwd=root,
            input=("\0".join(environment) + "\0").encode(),
        )
        ignored = tuple(sorted(path.decode("utf-8") for path in raw.split(b"\0") if path))
    tracked = git._run_git_bytes(("ls-files", "-z", "--", ".venv"), cwd=root)
    return TerminalWorkspaceObservation(
        inventory,
        ignored,
        tuple(path.decode("utf-8") for path in tracked.split(b"\0") if path),
        bool(guard.inherited_fds),
        True,
        datetime.now(UTC),
    )


@contextmanager
def _existing_task_scope(root: Path, task_id: str, guard: WorkerExecutionGuard) -> Iterator[None]:
    """Acquire the existing old Worker lock; never mkdir, create or replace it."""
    directory = _open_directory(root)
    root_metadata = os.fstat(directory)
    descriptor = -1
    try:
        name = hashlib.sha256(task_id.encode()).hexdigest() + ".lock"
        descriptor = os.open(name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory)
        metadata = os.fstat(descriptor)
        _require(stat.S_ISREG(metadata.st_mode) and not metadata.st_mode & 0o077)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RecoveryRejected("原任务仍有本机执行占用, 暂不能核验终态开发现场") from error
        guard.inherited_fds = (descriptor,)
        yield
        current = os.stat(name, dir_fd=directory, follow_symlinks=False)
        _require((metadata.st_dev, metadata.st_ino) == (current.st_dev, current.st_ino))
        current_root = _open_directory(root)
        try:
            current_metadata = os.fstat(current_root)
            _require(
                (root_metadata.st_dev, root_metadata.st_ino)
                == (current_metadata.st_dev, current_metadata.st_ino)
            )
        finally:
            os.close(current_root)
    finally:
        guard.inherited_fds = ()
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory)


def read_terminal_workspace_snapshot(
    config: ProductionConfig,
    environment: Mapping[str, str],
    original: NativeRecoverySource,
    capture: CapturedChanges,
    *,
    approved_permissions: AgentPermissions | None = None,
    scope_supplement: RecoveryScopeSupplement | None = None,
) -> RecoveryWorkspaceSnapshot | None:
    """Audit known stopped terminal work; legacy Tasks retain their old contract.

    Recovery commit already owns the global MySQL authority fence. Acquiring a
    second authority lock here would deadlock. A terminal Task cannot be claimed;
    the old Task process lock and two read-only SQL snapshots reject any drift.
    """
    if original.task.interruption_continuation_policy is None:
        return None
    from ai_software_engineer.recovery.native import NativeRecoverySourceReader

    try:
        source = original.source
        team = TeamWorkspace.initialize(
            config.platform_root,
            team_id=source.scope.team_id,
            name=config.team_name,
            read_only=True,
        )
        project, repository = team.project_registry().locate_repository(source.scope.repository_id)
        sidecar = repository.root
        scope = RecoveryWorkspaceScope(
            team_id=source.scope.team_id,
            project_id=project.manifest.project_id,
            repository_id=source.scope.repository_id,
            requirement_id=source.scope.delivery_id,
            dispatch_sha256=source.dispatch_sha256,
        )
        locks = sidecar / "state/queue-worker-locks"
        _reject_symlinks(locks)
        guard = WorkerExecutionGuard()
        with _existing_task_scope(locks, source.task_id, guard):
            reader = NativeRecoverySourceReader(config, environment)
            _require(
                reader.inspect(
                    source.scope,
                    failed_run_id=source.failed_run_id,
                    failed_context_id=source.failed_context_id,
                )
                == original
            )
            routes = _read_routes(sidecar, source)
            final = routes[-1]
            if final.outcome is RouteAttemptOutcome.SUCCEEDED:
                progress = final.result.artifact
                _require(
                    isinstance(progress, CoderProgressArtifact)
                    and progress == original.accepted_progress
                    and progress.producer.run_id == source.failed_run_id
                    and progress.source_revision == original.worktree_revision
                )
                # Native source inspection already authenticated the accepted
                # progress/event/checkpoint chain. This is the existing progress
                # recovery contract, not a failed mutation sealing audit.
                from ai_software_engineer.recovery.progress_source import require_stopped_progress

                require_stopped_progress(config, environment, sidecar, original.task, final)
                _require(
                    reader.inspect(
                        source.scope,
                        failed_run_id=source.failed_run_id,
                        failed_context_id=source.failed_context_id,
                    )
                    == original
                    and _read_routes(sidecar, source) == routes
                )
                return None
            _require(final.outcome is RouteAttemptOutcome.FAILED)
            facts = _read_facts(config, environment, original, sidecar, scope)
            _require(facts.scope == scope)
            _require(facts.start.request.permissions == original.permissions)
            _require(facts.start.request.source_revision == original.worktree_revision)
            permissions = approved_permissions or original.permissions
            git = GitWorktreeManager(
                source.scope.repository_root,
                Path(config.platform_root) / "worktrees" / source.scope.repository_id,
                branch_names={source.task_id: original.task.branch_name},
            )
            if scope_supplement is not None:
                from ai_software_engineer.recovery.scope import inspect_recovery_scope_supplement

                _require(
                    inspect_recovery_scope_supplement(
                        git,
                        capture.to_capture().worktree,
                        original,
                        request=scope_supplement.request,
                    )
                    == scope_supplement
                )
            git.verify_capture(
                capture.to_capture(), permissions, denied_paths=original.denied_paths
            )
            observation = _observe(git, facts, guard)
            snapshot = validate_terminal_workspace_snapshot(
                source=source,
                permissions=permissions,
                denied_paths=original.denied_paths,
                capture=capture,
                facts=facts,
                observation=observation,
                scope_supplement=scope_supplement,
            )
            _require(_read_facts(config, environment, original, sidecar, scope) == facts)
            _require(
                reader.inspect(
                    source.scope,
                    failed_run_id=source.failed_run_id,
                    failed_context_id=source.failed_context_id,
                )
                == original
            )
            NativeCoderContinuation._require_stopped(facts.stop.process_stop, facts.start.request)
            git.verify_capture(
                capture.to_capture(), permissions, denied_paths=original.denied_paths
            )
            second = _observe(git, facts, guard)
            _require(
                second.inventory_after == observation.inventory_after
                and second.ignored_paths == observation.ignored_paths
                and second.tracked_environment_paths == observation.tracked_environment_paths
            )
            return snapshot
    except RecoveryRejected:
        raise
    except Exception as error:
        raise RecoveryRejected(
            "终态开发现场的完整审计未通过; 原任务和文件保留, 请核对平台保存的原执行记录"
        ) from error
