"""Read-only SQL evidence for terminal post-candidate verification.

Native checkpoint projections from old platform versions may lag actual runtime facts.
This reader checks immutable dispatch identity but derives status/revision from SQL. It
does not authorize execution or replace the required upstream/joint provenance checks.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from pymysql.cursors import DictCursor

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import AgentRole, Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.task import task_matches_dispatch
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryStage,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.dispatch import (
    ContinuationDispatchRecord,
    DeliveryAllocation,
    DispatchCommitRecord,
)
from ai_software_engineer.manager.mysql_dispatch_authority import _decode_allocation
from ai_software_engineer.recovery.allocation_lineage import (
    continuation_source_checkpoints,
    resolve_planner_dispatch,
)
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.store.mysql_repository import (
    _decode_event,
    _decode_task,
    _non_negative_int,
    _text,
    open_mysql_connection,
)
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    QueuedRoleStep,
    RoleQueueAdmission,
    _decode,
)
from ai_software_engineer.work_queue.models import QueueArtifactReceipt, QueuedWorkItem

_PRE_AGENT_CONTEXT_BUDGET_REASON = (
    "BUDGET_EXHAUSTED: Required context exceeds the configured input budget; no automatic retry."
)
_PRE_AGENT_WORKTREE_CONFLICT_MARKER = "WorktreeAlreadyExists"
_PRE_AGENT_STARTUP_FAILURE_MARKER = "not configured for live execution"
PRE_AGENT_KNOWLEDGE_TIMEOUT_SUMMARIES = frozenset(
    {
        "coder knowledge preparation failed: TIMEOUT",
        "coder knowledge preparation reached local time limit",
    }
)


def retained_candidate_checkpoint(
    history: tuple[ProjectDeliveryCheckpoint, ...],
    dispatch: ContinuationDispatchRecord,
) -> ProjectDeliveryCheckpoint:
    """Resolve the exact source candidate retained by a failed continuation allocation."""
    dispatch.validate_integrity()
    if not history:
        raise RecoveryRejected("continuation Delivery history is empty")
    current = history[-1]
    if (
        current.stage not in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}
        or current.failed_stage is not DeliveryStage.DELIVERING
        or current.task_status not in {TaskStatus.BLOCKED, TaskStatus.FAILED}
        or current.candidate_revision is not None
        or current.repository_id != dispatch.repository_id
        or current.repository_root != dispatch.task.repository
        or current.delivery_id != dispatch.source_delivery_id
        or current.task_id != dispatch.task_id
        or current.dispatch_commit_id != dispatch.id
        or current.dispatch_commit_sha256 != dispatch.dispatch_sha256
    ):
        raise RecoveryRejected("current Delivery is not the failed continuation")
    matches = continuation_source_checkpoints(history[:-1], dispatch)
    if not matches:
        raise RecoveryRejected("continuation source candidate is absent from Delivery history")
    return matches[-1]


@dataclass(frozen=True, slots=True)
class CandidateRuntimeSnapshot:
    task: Task
    revision: int
    dispatch: DeliveryAllocation
    planner_dispatch: DispatchCommitRecord
    events: tuple[StateEvent, ...]
    bootstrap_plan_receipt: QueueArtifactReceipt | None = None


def validate_candidate_snapshot(
    checkpoint: ProjectDeliveryCheckpoint, snapshot: CandidateRuntimeSnapshot
) -> None:
    """Validate actual runtime progress without trusting stale cached status/candidate."""
    task, dispatch, events = snapshot.task, snapshot.dispatch, snapshot.events
    if (
        checkpoint.task_id != task.id
        or checkpoint.dispatch_commit_id != dispatch.id
        or checkpoint.dispatch_commit_sha256 != dispatch.dispatch_sha256
        or checkpoint.repository_id != dispatch.repository_id
        or checkpoint.repository_root != task.repository
        or not task_matches_dispatch(task, dispatch.task)
        or task.status not in (TaskStatus.FAILED, TaskStatus.BLOCKED)
        or snapshot.revision != len(events)
        or len(events) < 2
        or (checkpoint.task_revision is not None and checkpoint.task_revision > snapshot.revision)
    ):
        raise RecoveryRejected("candidate runtime does not match its original dispatch")
    previous = TaskStatus.NEW
    previous_time = task.created_at
    for event in events:
        if (
            event.task_id != task.id
            or event.from_status is not previous
            or event.attempt > task.attempts
            or event.occurred_at < previous_time
        ):
            raise RecoveryRejected("candidate runtime event chain is inconsistent")
        previous, previous_time = event.to_status, event.occurred_at
    terminal_candidate_event(task, events)
    if previous is not task.status or previous_time != task.updated_at:
        raise RecoveryRejected("runtime is not a terminal post-candidate QA failure")


def candidate_event(events: tuple[StateEvent, ...]) -> tuple[int, StateEvent]:
    """Return the latest candidate checkpoint retained before a terminal retry failure."""
    matches = tuple(
        (index, event)
        for index, event in enumerate(events)
        if event.to_status is TaskStatus.QA
        and event.reason in {"candidate_ready", "candidate_recovered"}
    )
    if not matches:
        raise RecoveryRejected("terminal runtime has no candidate checkpoint")
    index, event = matches[-1]
    if (
        len(event.artifact_ids) != 1
        or len(event.source_revision) not in (40, 64)
        or any(character not in "0123456789abcdef" for character in event.source_revision)
    ):
        raise RecoveryRejected("candidate checkpoint identity is invalid")
    return index, event


def terminal_candidate_event(task: Task, events: tuple[StateEvent, ...]) -> StateEvent:
    """Return a candidate only when the remaining events form a valid terminal tail."""
    index, candidate = candidate_event(events)
    if not _valid_terminal_tail(task, events[index + 1 :], candidate):
        raise RecoveryRejected("runtime is not a terminal post-candidate QA failure")
    return candidate


def terminal_accepted_qa_event(task: Task, events: tuple[StateEvent, ...]) -> StateEvent | None:
    """Return the exact QA PASS transition retained by a failed Reviewer run."""
    index, candidate = candidate_event(events)
    tail = events[index + 1 :]
    if not _valid_terminal_tail(task, tail, candidate):
        raise RecoveryRejected("runtime is not a terminal post-candidate QA failure")
    if not tail or not (
        tail[0].from_status is TaskStatus.QA
        and tail[0].to_status is TaskStatus.REVIEW
        and tail[0].reason == "qa_passed"
    ):
        return None
    if tail[0].source_revision != candidate.source_revision or len(tail[0].artifact_ids) != 1:
        raise RecoveryRejected("terminal QA PASS evidence is invalid")
    return tail[0]


def terminal_candidate_requires_coder_recovery(task: Task, events: tuple[StateEvent, ...]) -> bool:
    """Return whether a verified candidate was followed by interrupted Coder work.

    The retained candidate remains useful as the worktree baseline, but it is no
    longer the latest solution once QA/Review routed feedback back to Coder.  A
    terminal Coder failure after that feedback must therefore recover the Coder
    workspace instead of re-verifying the older candidate.
    """
    index, candidate = candidate_event(events)
    tail = events[index + 1 :]
    if not _valid_terminal_tail(task, tail, candidate):
        raise RecoveryRejected("runtime is not a terminal post-candidate QA failure")
    offset = (
        1
        if (
            tail[0].from_status is TaskStatus.QA
            and tail[0].to_status is TaskStatus.REVIEW
            and tail[0].reason == "qa_passed"
        )
        else 0
    )
    remaining = tail[offset:]
    return (
        len(remaining) == 2
        and remaining[0].to_status is TaskStatus.IMPLEMENTING
        and remaining[1].from_status is TaskStatus.IMPLEMENTING
        and remaining[1].to_status is task.status
    )


def _valid_terminal_tail(
    task: Task,
    tail: tuple[StateEvent, ...],
    candidate: StateEvent,
) -> bool:
    if not tail:
        return False
    current = TaskStatus.QA
    offset = 0
    if (
        tail[0].from_status is TaskStatus.QA
        and tail[0].to_status is TaskStatus.REVIEW
        and tail[0].reason == "qa_passed"
    ):
        if tail[0].source_revision != candidate.source_revision:
            return False
        current, offset = TaskStatus.REVIEW, 1
    remaining = tail[offset:]
    if len(remaining) == 1:
        terminal = remaining[0]
        return (
            terminal.from_status is current
            and terminal.to_status is task.status
            and terminal.source_revision in (task.base_ref, candidate.source_revision)
        )
    feedback_reason = {
        TaskStatus.QA: "qa_failed_route_to_coder",
        TaskStatus.REVIEW: "review_rejected_route_to_coder",
    }[current]
    if len(remaining) != 2:
        return False
    feedback, terminal = remaining
    return (
        feedback.from_status is current
        and feedback.to_status is TaskStatus.IMPLEMENTING
        and feedback.reason == feedback_reason
        and feedback.source_revision == candidate.source_revision
        and terminal.from_status is TaskStatus.IMPLEMENTING
        and terminal.to_status is task.status
        and terminal.source_revision in (task.base_ref, candidate.source_revision)
    )


def read_candidate_snapshot(
    config: ProductionConfig,
    environment: Mapping[str, str],
    checkpoint: ProjectDeliveryCheckpoint,
    history: tuple[ProjectDeliveryCheckpoint, ...],
) -> CandidateRuntimeSnapshot:
    """One consistent read-only transaction; no repository construction or DDL."""
    if checkpoint.task_id is None or checkpoint.dispatch_commit_id is None:
        raise RecoveryRejected("missing original Task or dispatch reference")
    if not history or history[-1] != checkpoint:
        raise RecoveryRejected("candidate checkpoint history is incomplete")
    connection = open_mysql_connection(config.require_mysql_dsn(environment))
    try:
        with connection.cursor(DictCursor) as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            allocations = _read_allocations(cursor, history)
            return _read_candidate_runtime(cursor, checkpoint, history, allocations)
    finally:
        connection.rollback()
        connection.close()


def read_pre_execution_snapshot(
    config: ProductionConfig,
    environment: Mapping[str, str],
    history: tuple[ProjectDeliveryCheckpoint, ...],
    *,
    allow_unstarted: bool = False,
) -> CandidateRuntimeSnapshot | None:
    """Read a never-invoked Task for restart or preparation rebinding.

    The default remains the narrowly recognized historical context-budget failure.
    ``allow_unstarted`` is a separate, stricter shape used only when the Delivery
    cursor is already materialized at DELIVERING and the preparation digest drifted.
    """
    if not history:
        return None
    cp = history[-1]
    if cp.task_id is None or cp.dispatch_commit_id is None or cp.candidate_revision is not None:
        return None
    connection = open_mysql_connection(config.require_mysql_dsn(environment))
    try:
        with connection.cursor(DictCursor) as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            task, revision, events = _read_task_facts(cursor, cp)
            original_failure = (
                revision == 2
                and task.attempts == 1
                and not task.retry_failures
                and task.status is TaskStatus.BLOCKED
                and len(events) == 2
                and events[0].from_status is TaskStatus.NEW
                and events[0].to_status is TaskStatus.PLANNING
                and events[0].reason == "task_validated"
                and events[1].from_status is TaskStatus.PLANNING
                and events[1].to_status is TaskStatus.BLOCKED
                and events[1].reason == _PRE_AGENT_CONTEXT_BUDGET_REASON
            )
            pre_agent_worktree_conflict = (
                cp.stage in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}
                and cp.failed_stage is DeliveryStage.DELIVERING
                and cp.failure_code is DeliveryFailureCode.INVARIANT_VIOLATION
                and cp.failure_summary is not None
                and _PRE_AGENT_WORKTREE_CONFLICT_MARKER in cp.failure_summary
                and revision == 2
                and task.attempts == 1
                and not task.retry_failures
                and task.status is TaskStatus.IMPLEMENTING
                and len(events) == 2
                and events[0].from_status is TaskStatus.NEW
                and events[0].to_status is TaskStatus.PLANNING
                and events[0].reason == "task_validated"
                and events[1].from_status is TaskStatus.PLANNING
                and events[1].to_status is TaskStatus.IMPLEMENTING
                and events[1].reason == "plan_validated"
            )
            pre_agent_startup_failure = (
                cp.stage in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}
                and cp.failed_stage is DeliveryStage.DELIVERING
                and cp.failure_code is DeliveryFailureCode.PERMISSION_DENIED
                and cp.failure_summary is not None
                and _PRE_AGENT_STARTUP_FAILURE_MARKER in cp.failure_summary
                and revision == 2
                and task.attempts == 1
                and not task.retry_failures
                and task.status is TaskStatus.IMPLEMENTING
                and len(events) == 2
                and events[0].from_status is TaskStatus.NEW
                and events[0].to_status is TaskStatus.PLANNING
                and events[0].reason == "task_validated"
                and events[1].from_status is TaskStatus.PLANNING
                and events[1].to_status is TaskStatus.IMPLEMENTING
                and events[1].reason == "plan_validated"
            )
            pre_agent_knowledge_timeout = (
                cp.stage in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}
                and cp.failed_stage is DeliveryStage.DELIVERING
                and cp.failure_summary in PRE_AGENT_KNOWLEDGE_TIMEOUT_SUMMARIES
                and cp.failure_code
                in {
                    DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED,  # legacy projection
                    DeliveryFailureCode.TRANSIENT_PROVIDER_FAILURE,
                    DeliveryFailureCode.RESOURCE_UNAVAILABLE,
                }
                and revision == 3
                and task.attempts == 1
                and not task.retry_failures
                and task.status is TaskStatus.BLOCKED
                and len(events) == 3
                and events[0].from_status is TaskStatus.NEW
                and events[0].to_status is TaskStatus.PLANNING
                and events[0].reason == "task_validated"
                and events[1].from_status is TaskStatus.PLANNING
                and events[1].to_status is TaskStatus.IMPLEMENTING
                and events[1].reason == "plan_validated"
                and events[2].from_status is TaskStatus.IMPLEMENTING
                and events[2].to_status is TaskStatus.BLOCKED
                and events[2].reason == f"TRANSIENT_INFRA: {cp.failure_summary}"
                and len(events[1].artifact_ids) == 1
                and events[2].artifact_ids == events[1].artifact_ids
                and events[1].occurred_at <= events[2].occurred_at
                and all(e.actor is AgentRole.ORCHESTRATOR for e in events)
            )
            bootstrap_failure = (
                pre_agent_worktree_conflict
                or pre_agent_startup_failure
                or pre_agent_knowledge_timeout
            )
            unstarted_rebind = (
                allow_unstarted
                and cp.stage is DeliveryStage.DELIVERING
                and cp.task_status is TaskStatus.NEW
                and cp.task_revision == 0
                and cp.failed_stage is None
                and cp.failure_code is None
                and task.status is TaskStatus.NEW
                and task.attempts == 0
                and not task.retry_failures
                and not events
            )
            if not (
                original_failure
                or unstarted_rebind
                or pre_agent_worktree_conflict
                or pre_agent_startup_failure
                or pre_agent_knowledge_timeout
            ):
                return None
            allocations = _read_allocations(cursor, history)
            dispatch = allocations[cp.dispatch_commit_id]
            invalid_dispatch = not isinstance(dispatch, DispatchCommitRecord) and not (
                (unstarted_rebind or pre_agent_worktree_conflict or pre_agent_startup_failure)
                and isinstance(dispatch, ContinuationDispatchRecord)
            )
            if invalid_dispatch and (original_failure or bootstrap_failure):
                raise RecoveryRejected(
                    "pre-execution restart already attempted; inspect the new context failure"
                )
            if invalid_dispatch:
                return None
            if (
                cp.task_revision != revision
                or cp.task_status is not task.status
                or cp.repository_root != task.repository
                or not task_matches_dispatch(task, dispatch.task)
                or (
                    (original_failure or bootstrap_failure)
                    and (
                        cp.stage not in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}
                        or cp.failed_stage is not DeliveryStage.DELIVERING
                        or task.updated_at != events[-1].occurred_at
                        or not task.created_at <= events[0].occurred_at <= events[1].occurred_at
                        or any(
                            e.task_id != task.id
                            or e.attempt != 1
                            or e.source_revision != task.base_ref
                            or (
                                e.artifact_ids
                                if original_failure
                                else e is events[0] and e.artifact_ids
                            )
                            for e in events
                        )
                        or (
                            bootstrap_failure
                            and (
                                len(events[1].artifact_ids) != 1
                                or not events[1].artifact_ids[0].startswith("art_plan_")
                            )
                        )
                    )
                )
            ):
                raise RecoveryRejected("pre-execution failure facts are inconsistent")
            # An ACTIVE claim is execution evidence until the normal queue
            # reaper changes it to EXPIRED.  Do not compare clocks here and
            # silently ignore an un-reaped claim: the resume supervisor reaps
            # it first, preserving the LEASE_EXPIRED audit event.  A direct
            # read therefore fails closed on every remaining ACTIVE row.
            startup = bootstrap_failure
            claim_query = "SELECT lease_id FROM work_queue_claims WHERE task_id=%s"
            if startup:
                claim_query += " AND state='ACTIVE'"
            cursor.execute(claim_query, (task.id,))
            if cursor.fetchone() is not None:
                raise RecoveryRejected("pre-execution source already has a role claim")
            cursor.execute(
                "SELECT id,task_id,payload_json,sha256 FROM work_queue_admissions WHERE task_id=%s",
                (task.id,),
            )
            admission_row = cursor.fetchone()
            plan_receipt = None
            if admission_row is not None:
                if not bootstrap_failure:
                    raise RecoveryRejected("pre-execution source already has a queue admission")
                # T046 creates the immutable RoleQueueAdmission after the
                # deterministic plan boundary and before the first Worker
                # claim.  A worktree collision can therefore leave this
                # bootstrap record even though no Agent ever started.  It is
                # safe to retain only when its complete, integrity-checked
                # identity matches the source dispatch and its sole legacy
                # artifact is the accepted planning artifact.
                if not {"id", "task_id", "payload_json", "sha256"}.issubset(admission_row):
                    raise RecoveryRejected("pre-agent queue admission is incomplete")
                admission = _decode(admission_row, RoleQueueAdmission)
                if (
                    admission.task_id != task.id
                    or admission.repository_id != dispatch.repository_id
                    or admission.allocation_sha256 != dispatch.dispatch_sha256
                    or tuple(receipt.artifact_id for receipt in admission.legacy_artifacts)
                    != events[-1].artifact_ids
                ):
                    raise RecoveryRejected("pre-agent queue admission does not match source")
                if (
                    len(admission.legacy_artifacts) != 1
                    or len(events[-1].artifact_ids) != 1
                    or admission.legacy_artifacts[0].artifact_id != events[-1].artifact_ids[0]
                ):
                    raise RecoveryRejected("pre-agent admission must contain the sole plan receipt")
                cursor.execute(
                    "SELECT id,task_id,payload_json,sha256 FROM work_queue_steps "
                    "WHERE task_id=%s ORDER BY id",
                    (task.id,),
                )
                step_rows = tuple(cursor.fetchall())
                if len(step_rows) != 1:
                    raise RecoveryRejected("pre-agent queue step is missing or ambiguous")
                step = _decode(step_rows[0], QueuedRoleStep)
                if (
                    step.allocation_sha256 != admission.allocation_sha256
                    or step.boundary.task_id != task.id
                    or step.boundary.role is not AgentRole.CODER
                    or step.boundary.attempt != 1
                    or step.boundary.checkpoint_sequence
                    != (revision - 1 if pre_agent_knowledge_timeout else revision)
                    or step.boundary.source_revision != task.base_ref
                ):
                    raise RecoveryRejected("pre-agent queue step does not match source")
                cursor.execute(
                    "SELECT id,task_id,status,payload_json FROM work_queue_items WHERE task_id=%s "
                    "ORDER BY checkpoint_sequence,attempt,id",
                    (task.id,),
                )
                item_rows = tuple(cursor.fetchall())
                if len(item_rows) != 1:
                    raise RecoveryRejected("pre-agent queue item is missing or ambiguous")
                item = QueuedWorkItem.model_validate_json(item_rows[0]["payload_json"])
                if (
                    item_rows[0]["id"] != item.id
                    or item_rows[0]["task_id"] != item.task_id
                    or item_rows[0]["status"] != item.status.value
                    or item.id != step.work_item.id
                    or item.task_id != task.id
                    or item.role is not AgentRole.CODER
                    or item.attempt != 1
                    or item.checkpoint_sequence != step.boundary.checkpoint_sequence
                    or item.repository_id != dispatch.repository_id
                    or item.status
                    not in (
                        {WorkItemStatus.CLOSED}
                        if pre_agent_knowledge_timeout
                        else {WorkItemStatus.READY, WorkItemStatus.RETRY_SCHEDULED}
                    )
                    or item.model_dump(
                        exclude={
                            "status",
                            "dispatch_sequence",
                            "wait_reason",
                            "available_at",
                            "updated_at",
                        }
                    )
                    != step.work_item.model_dump(
                        exclude={
                            "status",
                            "dispatch_sequence",
                            "wait_reason",
                            "available_at",
                            "updated_at",
                        }
                    )
                ):
                    raise RecoveryRejected("pre-agent queue item is not an unclaimed Coder")
                cursor.execute(
                    "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
                    "WHERE task_id=%s ORDER BY id",
                    (task.id,),
                )
                accepted_rows = tuple(cursor.fetchall())
                if accepted_rows:
                    _decode(accepted_rows[0], AcceptedRoleArtifact)
                    raise RecoveryRejected("pre-agent source already has an accepted role artifact")
                plan_receipt = admission.legacy_artifacts[0]
            elif pre_agent_knowledge_timeout:
                raise RecoveryRejected(
                    "pre-Coder knowledge timeout has no verified queue admission"
                )
            elif pre_agent_worktree_conflict or pre_agent_startup_failure:
                # Queue tables are append-only and may outlive a failed
                # admission transaction in an older deployment.  An orphaned
                # step/item or accepted receipt is evidence, not absence.
                for table, query in (
                    (
                        "work_queue_steps",
                        "SELECT id FROM work_queue_steps WHERE task_id=%s",
                    ),
                    (
                        "work_queue_items",
                        "SELECT id FROM work_queue_items WHERE task_id=%s",
                    ),
                    (
                        "work_queue_accepted_artifacts",
                        "SELECT id FROM work_queue_accepted_artifacts WHERE task_id=%s",
                    ),
                ):
                    cursor.execute(query, (task.id,))
                    if tuple(cursor.fetchall()):
                        raise RecoveryRejected(f"pre-agent source has an orphaned {table} record")
            planner_dispatch = (
                dispatch
                if isinstance(dispatch, DispatchCommitRecord)
                else resolve_planner_dispatch(dispatch, allocations, history)
            )
            return CandidateRuntimeSnapshot(
                task, revision, dispatch, planner_dispatch, events, plan_receipt
            )
    finally:
        connection.rollback()
        connection.close()


def read_candidate_source_snapshot(
    config: ProductionConfig,
    environment: Mapping[str, str],
    history: tuple[ProjectDeliveryCheckpoint, ...],
) -> tuple[
    ProjectDeliveryCheckpoint,
    ProjectDeliveryCheckpoint,
    CandidateRuntimeSnapshot,
    ContinuationDispatchRecord | None,
]:
    """Read the current terminal cursor and its exact retained candidate in one SQL snapshot."""
    if not history:
        raise RecoveryRejected("candidate checkpoint history is incomplete")
    current = history[-1]
    if current.task_id is None or current.dispatch_commit_id is None:
        raise RecoveryRejected("missing current Task or dispatch reference")
    connection = open_mysql_connection(config.require_mysql_dsn(environment))
    try:
        with connection.cursor(DictCursor) as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            allocations = _read_allocations(cursor, history)
            source = current
            continuation: ContinuationDispatchRecord | None = None
            if current.candidate_revision is None:
                _, _, current_events = _read_task_facts(cursor, current)
                if any(
                    event.to_status is TaskStatus.QA
                    and event.reason in {"candidate_ready", "candidate_recovered"}
                    for event in current_events
                ):
                    snapshot = _read_candidate_runtime(cursor, current, history, allocations)
                    return current, current, snapshot, None
                current_dispatch = allocations[current.dispatch_commit_id]
                if not isinstance(current_dispatch, ContinuationDispatchRecord):
                    raise RecoveryRejected("terminal Delivery has no retained candidate")
                _validate_failed_continuation_runtime(cursor, current, current_dispatch)
                source = retained_candidate_checkpoint(history, current_dispatch)
                continuation = current_dispatch
            snapshot = _read_candidate_runtime(cursor, source, history, allocations)
            return source, current, snapshot, continuation
    finally:
        connection.rollback()
        connection.close()


def _read_allocations(
    cursor: DictCursor,
    history: tuple[ProjectDeliveryCheckpoint, ...],
) -> dict[str, DeliveryAllocation]:
    allocations: dict[str, DeliveryAllocation] = {}
    for historic in history:
        commit_id = historic.dispatch_commit_id
        if commit_id is None or commit_id in allocations:
            continue
        cursor.execute("SELECT * FROM dispatch_commits WHERE id = %s", (commit_id,))
        row = cursor.fetchone()
        if row is None:
            raise RecoveryRejected("candidate dispatch history is missing")
        allocation = _decode_allocation(row)
        if (
            allocation.id != commit_id
            or allocation.dispatch_sha256 != historic.dispatch_commit_sha256
            or allocation.repository_id != historic.repository_id
            or allocation.task_id != historic.task_id
        ):
            raise RecoveryRejected("candidate dispatch history is inconsistent")
        allocations[commit_id] = allocation
    return allocations


def _read_task_facts(
    cursor: DictCursor,
    checkpoint: ProjectDeliveryCheckpoint,
) -> tuple[Task, int, tuple[StateEvent, ...]]:
    assert checkpoint.task_id is not None
    cursor.execute("SELECT * FROM tasks WHERE id = %s", (checkpoint.task_id,))
    row = cursor.fetchone()
    if row is None:
        raise RecoveryRejected("original Task is missing")
    task = _decode_task(checkpoint.task_id, _text(row, "payload_json"))
    revision = _non_negative_int(row, "revision")
    if _text(row, "status") != task.status.value:
        raise RecoveryRejected("Task status columns disagree")
    cursor.execute("SELECT * FROM state_events WHERE task_id = %s ORDER BY revision", (task.id,))
    rows = cursor.fetchall()
    if [item["revision"] for item in rows] != list(range(1, revision + 1)):
        raise RecoveryRejected("candidate runtime event revisions have gaps")
    events = tuple(_decode_event(_text(item, "payload_json")) for item in rows)
    if any(event.event_id != item["event_id"] for event, item in zip(events, rows, strict=True)):
        raise RecoveryRejected("candidate event identities disagree")
    return task, revision, events


def _read_candidate_runtime(
    cursor: DictCursor,
    checkpoint: ProjectDeliveryCheckpoint,
    history: tuple[ProjectDeliveryCheckpoint, ...],
    allocations: Mapping[str, DeliveryAllocation],
) -> CandidateRuntimeSnapshot:
    if checkpoint.task_id is None or checkpoint.dispatch_commit_id is None:
        raise RecoveryRejected("missing original Task or dispatch reference")
    dispatch = allocations[checkpoint.dispatch_commit_id]
    planner_dispatch = resolve_planner_dispatch(dispatch, allocations, history)
    task, revision, events = _read_task_facts(cursor, checkpoint)
    snapshot = CandidateRuntimeSnapshot(task, revision, dispatch, planner_dispatch, events)
    validate_candidate_snapshot(checkpoint, snapshot)
    return snapshot


def _validate_failed_continuation_runtime(
    cursor: DictCursor,
    checkpoint: ProjectDeliveryCheckpoint,
    dispatch: ContinuationDispatchRecord,
) -> None:
    task, revision, events = _read_task_facts(cursor, checkpoint)
    if (
        not task_matches_dispatch(task, dispatch.task)
        or checkpoint.task_status is not task.status
        or checkpoint.task_revision != revision
        or task.status not in {TaskStatus.BLOCKED, TaskStatus.FAILED}
        or not events
        or any(
            event.to_status is TaskStatus.QA
            and event.reason in {"candidate_ready", "candidate_recovered"}
            for event in events
        )
    ):
        raise RecoveryRejected("failed continuation runtime is inconsistent")
    previous = TaskStatus.NEW
    previous_time = task.created_at
    for event in events:
        if (
            event.task_id != task.id
            or event.from_status is not previous
            or event.attempt > task.attempts
            or event.occurred_at < previous_time
        ):
            raise RecoveryRejected("failed continuation event chain is inconsistent")
        previous, previous_time = event.to_status, event.occurred_at
    if previous is not task.status or previous_time != task.updated_at:
        raise RecoveryRejected("failed continuation is not terminal")
    # A continuation may reuse the retained source candidate only when execution
    # stopped before any Agent was admitted.  Every other terminal continuation
    # can contain valuable Coder work and must go through native worktree
    # recovery instead of silently starting again from the old candidate.
    if events[-1].reason != _PRE_AGENT_CONTEXT_BUDGET_REASON:
        raise RecoveryRejected("failed continuation contains a recoverable Agent workspace")
