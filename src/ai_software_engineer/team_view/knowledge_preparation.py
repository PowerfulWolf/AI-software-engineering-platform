"""Fresh read-only role phases from the current claim's immutable invocation facts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, StrictInt
from pymysql.cursors import DictCursor

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.enums import TeamRole, WorkItemStatus
from ai_software_engineer.domain.model import DomainModel, JsonValue
from ai_software_engineer.domain.workforce import RoleAssignment, TaskLease
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord,
    KnowledgeInvocationIntent,
    KnowledgeInvocationOutcome,
    invocation_scope_lane_sha256,
)
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import BaselineExecutionReservation
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption, resolve_step_overlays
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep, _decode
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem

ExecutionPhase = Literal["KNOWLEDGE_PREPARATION", "ROLE_EXECUTION", "FINALIZING"]


class _QueueReadEvent(DomainModel):
    sequence: StrictInt = Field(gt=0)
    work_item_id: str
    event_type: Literal["CLAIMED", "EXECUTION_BASELINE_REBOUND"]
    from_status: WorkItemStatus | None
    to_status: WorkItemStatus
    lease_id: str | None
    payload_json: str
    occurred_at: AwareDatetime


class _ClaimedPayload(DomainModel):
    work_item: QueuedWorkItem
    detail: dict[str, JsonValue] = Field(max_length=0)


class _ReboundDetail(DomainModel):
    binding_sha256: Sha256
    next_work_item_id: str
    plan_sha256: Sha256
    budget_refund: Literal[False]
    reservation: BaselineExecutionReservation | None


class _ReboundPayload(DomainModel):
    work_item: QueuedWorkItem
    detail: _ReboundDetail


@dataclass(frozen=True)
class RoleExecutionScope:
    sidecar: Path
    team_id: str
    project_id: str
    requirement_id: str
    source_revision: str = ""


def _optional_records(root: Path) -> KnowledgeRecordStore | None:
    # A missing legacy directory is neutral; dangling links are unsafe, not absent.
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise KnowledgeError("STORE_PATH")
    if not root.exists():
        return None
    return KnowledgeRecordStore(root, read_only=True)


def _main_phase(
    scope: RoleExecutionScope, item: QueuedWorkItem, lease: TaskLease
) -> ExecutionPhase | None:
    records = _optional_records(scope.sidecar / "state" / "invocations")
    if records is None:
        return None
    start = records.find("invocation-starts", item.id, DeliveryInvocationStart)
    outcome = records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome)
    if start is not None:
        start.validate_integrity()
    if outcome is not None:
        outcome.validate_integrity()
        if outcome.start != start:
            raise ValueError("role phase outcome changed its exact invocation start")
    if start is None:
        return None
    request = start.request
    if (
        start.work_item_id,
        start.checkpoint_sequence,
        start.lease_id,
        request.task_id,
        request.role,
        request.attempt,
        request.source_revision,
    ) != (
        item.id,
        item.checkpoint_sequence,
        lease.id,
        item.task_id,
        item.role,
        item.attempt,
        scope.source_revision,
    ) or start.started_at < lease.acquired_at:
        return None
    return "FINALIZING" if outcome is not None else "ROLE_EXECUTION"


def _item_identity(item: QueuedWorkItem, *, include_dispatch: bool = True) -> tuple[object, ...]:
    return (
        item.id,
        item.task_id,
        item.repository_id,
        item.role,
        item.attempt,
        item.checkpoint_sequence,
        item.dispatch_sequence if include_dispatch else None,
        item.repository_scopes,
        item.parent_work_item_id,
    )


def read_claim_source(
    cursor: DictCursor,
    *,
    scope: RoleExecutionScope,
    item: QueuedWorkItem,
    lease: TaskLease,
    allocation_sha256: str,
) -> str | None:
    """Resolve the source before this exact claim, using the caller's SQL snapshot.

    Coder source can differ from both Task.base_ref and historical candidates.
    The immutable step and a validated local baseline overlay establish it. An
    unsupported inherited epoch stays neutral; this reader grants no authority.
    """
    cursor.execute(
        "SELECT id,task_id,payload_json,sha256 FROM work_queue_steps WHERE id=%s", (item.id,)
    )
    row = cursor.fetchone()
    if row is None:
        return None
    original = _decode(row, QueuedRoleStep)
    if original.allocation_sha256 != allocation_sha256 or _item_identity(
        original.work_item, include_dispatch=False
    ) != _item_identity(item, include_dispatch=False):
        raise ValueError("role phase source changed its exact immutable queue step")
    cursor.execute(
        "SELECT sequence,work_item_id,event_type,from_status,to_status,lease_id,"
        "payload_json,occurred_at FROM work_queue_events "
        "WHERE lease_id=%s AND event_type='CLAIMED' LIMIT 2",
        (lease.id,),
    )
    claimed = cursor.fetchall()
    if len(claimed) != 1:
        raise ValueError("role phase source requires one exact claim event")
    claim = _QueueReadEvent.model_validate(claimed[0])
    claim_payload = _ClaimedPayload.model_validate_json(claim.payload_json)
    if (
        claim.event_type != "CLAIMED"
        or claim.work_item_id != item.id
        or claim.lease_id != lease.id
        or claim.occurred_at != lease.acquired_at
        or claim.to_status is not WorkItemStatus.LEASED
        or claim.from_status not in {WorkItemStatus.READY, WorkItemStatus.RETRY_SCHEDULED}
        or claim_payload.work_item.status is not WorkItemStatus.LEASED
        or _item_identity(claim_payload.work_item) != _item_identity(item)
    ):
        raise ValueError("role phase source claim identity mismatch")
    cursor.execute(
        "SELECT sequence,work_item_id,event_type,from_status,to_status,lease_id,"
        "payload_json,occurred_at "
        "FROM work_queue_events WHERE work_item_id=%s "
        "AND event_type='EXECUTION_BASELINE_REBOUND' AND sequence<%s "
        "ORDER BY sequence DESC LIMIT 1",
        (item.id, claim.sequence),
    )
    rebound_row = cursor.fetchone()
    rebound_payload = None
    baseline_sha = None
    if rebound_row is not None:
        rebound = _QueueReadEvent.model_validate(rebound_row)
        rebound_payload = _ReboundPayload.model_validate_json(rebound.payload_json)
        if (
            rebound.event_type != "EXECUTION_BASELINE_REBOUND"
            or rebound.work_item_id != item.id
            or rebound.lease_id is not None
            or rebound.sequence >= claim.sequence
            or rebound.occurred_at > claim.occurred_at
            or rebound.to_status is not rebound_payload.work_item.status
            or _item_identity(rebound_payload.work_item, include_dispatch=False)
            != _item_identity(item, include_dispatch=False)
            or rebound_payload.work_item.dispatch_sequence > item.dispatch_sequence
        ):
            raise ValueError("role phase source rebound event identity mismatch")
        baseline_sha = rebound_payload.detail.binding_sha256
    cursor.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='work_queue_execution_baselines'"
    )
    if cursor.fetchone() is None:
        return original.boundary.source_revision if baseline_sha is None else None
    cursor.execute(
        "SELECT id,task_id,payload_json,sha256 FROM work_queue_execution_baselines "
        "WHERE task_id=%s LIMIT 101",
        (item.task_id,),
    )
    rows = cursor.fetchall()
    if len(rows) > 100:
        raise ValueError("role phase source exceeds bounded execution baseline history")
    consumed = tuple(
        sorted(
            (_decode(row, BaselineQueueConsumption) for row in rows),
            key=lambda record: record.binding.sequence,
        )
    )
    if len({record.binding.sequence for record in consumed}) != len(consumed):
        raise ValueError("role phase source has duplicate baseline versions")
    for record in consumed:
        bound = record.binding
        if (
            bound.scope.team_id,
            bound.scope.project_id,
            bound.scope.repository_id,
            bound.scope.repository_root,
            bound.task_id,
        ) != (
            scope.team_id,
            scope.project_id,
            item.repository_id,
            item.repository_scopes[0],
            item.task_id,
        ):
            raise ValueError("role phase source baseline belongs to another scope")
    if rebound_payload is not None:
        matched = tuple(
            record for record in consumed if record.binding.binding_sha256 == baseline_sha
        )
        if len(matched) != 1:
            return None
        record = matched[0]
        detail = rebound_payload.detail
        if (
            record.work_item_id != item.id
            or detail.next_work_item_id != record.next_work_item_id
            or detail.plan_sha256 != record.plan.plan_sha256
            or detail.reservation != record.plan.facts.continuation
        ):
            raise ValueError("role phase source rebound changed its sealed baseline consumption")
    selected, found = resolve_step_overlays(
        original, consumed, baseline_sha256=baseline_sha, latest=False
    )
    return selected.boundary.source_revision if found else None


def _current_intent(
    intent: KnowledgeInvocationIntent,
    scope: RoleExecutionScope,
    requirement_id: str,
    item: QueuedWorkItem,
    assignment: RoleAssignment,
    lease: TaskLease,
) -> bool:
    bound, claim = intent.binding, intent.claim
    return (
        claim is not None
        and (
            bound.team_id,
            bound.project_id,
            bound.requirement_id,
            bound.repository_ids,
            bound.task_id,
            bound.role.value,
            bound.source_revision,
        )
        == (
            scope.team_id,
            scope.project_id,
            requirement_id,
            (item.repository_id,),
            item.task_id,
            item.role.value,
            scope.source_revision,
        )
        and _item_identity(claim.work_item) == _item_identity(item)
        and claim.assignment == assignment
        and claim.lease.model_dump(exclude={"expires_at"})
        == lease.model_dump(exclude={"expires_at"})
        and intent.created_at >= lease.acquired_at
    )


def read_execution_phase(
    *,
    scope: RoleExecutionScope,
    item: QueuedWorkItem,
    assignment: RoleAssignment,
    lease: TaskLease,
) -> ExecutionPhase | None:
    """Caller must first verify RUNNING and current SQL lease liveness.

    Missing records preserve legacy neutral rendering. Unsafe or corrupt facts
    raise into the read projection's existing fail-closed boundary; no writes,
    reconciliation, verdict interpretation or cross-snapshot caching occur here.
    """
    if not scope.source_revision:
        return None
    main = _main_phase(scope, item, lease)
    if main is not None:
        return main
    found = False
    # Native joint Requirement, plus only the known Task-id legacy scope.
    for requirement_id in dict.fromkeys((scope.requirement_id, item.task_id)):
        lane = invocation_scope_lane_sha256(
            team_id=scope.team_id,
            project_id=scope.project_id,
            requirement_id=requirement_id,
            repository_ids=(item.repository_id,),
            task_id=item.task_id,
            role=TeamRole(item.role.value),
        )
        records = _optional_records(scope.sidecar / "knowledge" / "runs" / "invocations" / lane)
        if records is None:
            continue
        for intent in records.list(
            "knowledge-invocation-intents", KnowledgeInvocationIntent, limit=512
        ):
            intent.validate_integrity()
            bound = intent.binding
            actual_lane = invocation_scope_lane_sha256(
                team_id=bound.team_id,
                project_id=bound.project_id,
                requirement_id=bound.requirement_id,
                repository_ids=bound.repository_ids,
                task_id=bound.task_id,
                role=bound.role,
            )
            if actual_lane != lane:
                raise ValueError("knowledge phase record belongs to another scope lane")
            if not _current_intent(intent, scope, requirement_id, item, assignment, lease):
                continue
            if (
                records.find(
                    "knowledge-invocation-intents",
                    bound.run_id + ":" + intent.phase,
                    KnowledgeInvocationIntent,
                )
                != intent
            ):
                raise ValueError("knowledge phase intent changed its content-addressed key")
            outcome = records.find(
                "knowledge-invocation-outcomes",
                bound.run_id + ":" + intent.phase,
                KnowledgeInvocationOutcome,
            )
            if outcome is not None:
                outcome.validate_integrity()
                if outcome.intent != intent:
                    raise ValueError("knowledge phase outcome changed its exact intent")
                for execution in outcome.executions:
                    if (
                        records.get(
                            "knowledge-execution-records",
                            execution.record_sha256,
                            KnowledgeExecutionRecord,
                        )
                        != execution
                    ):
                        raise ValueError("knowledge phase outcome lost its exact execution receipt")
            found = True
    return "KNOWLEDGE_PREPARATION" if found else None
