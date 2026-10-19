"""SELECT-only proof that inherited inputs reached a genuinely claimed Coder."""

import json
from collections.abc import Callable, Mapping
from functools import wraps

from pydantic import JsonValue, TypeAdapter
from pymysql import MySQLError
from pymysql.cursors import DictCursor

from ai_software_engineer.domain import AgentRole, Task, WorkItemStatus
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.recovery.models import RecoveryRejected, RecoveryScope
from ai_software_engineer.store import StoreError
from ai_software_engineer.store.mysql_repository import (
    _non_negative_int,
    _text,
    open_mysql_connection,
)
from ai_software_engineer.work_queue.baseline import (
    BaselineQueueConsumption,
    resolve_step_overlays,
)
from ai_software_engineer.work_queue.claim_snapshot import require_claim_snapshot
from ai_software_engineer.work_queue.execution_store import (
    QueuedRoleStep,
    RoleQueueAdmission,
    _decode,
    record_digest,
)
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from ai_software_engineer.work_queue.models import QueueClaim
from ai_software_engineer.work_queue.mysql import MySqlPersistentWorkQueue

_MAX_QUEUE_HISTORY = 512


def _inherited_read_boundary[**P, R](method: Callable[P, R]) -> Callable[P, R]:
    """Known read availability failures cannot strand an already sealed main start."""

    @wraps(method)
    def checked(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return method(*args, **kwargs)
        except (StoreError, MySQLError):
            # Vendor connection/SQL text may contain credentials or host details.
            raise RecoveryRejected("inherited recovery durable input is unavailable") from None

    return checked


@_inherited_read_boundary
def read_inherited_invocation_queue(
    dsn: str,
    start: DeliveryInvocationStart,
    dispatch: RecoveryDispatchRecord,
    task: Task,
    scope: RecoveryScope,
    project_id: ProjectId,
) -> None:
    """Never construct a queue: its constructor owns DDL and mutation authority."""
    connection = open_mysql_connection(dsn)
    try:
        with connection.cursor(DictCursor) as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            cursor.execute(
                "SELECT id,task_id,payload_json,sha256 FROM work_queue_admissions WHERE id=%s",
                (task.id,),
            )
            admission = _decode(_required(cursor.fetchone()), RoleQueueAdmission)
            cursor.execute(
                "SELECT id,task_id,payload_json,sha256 FROM work_queue_steps "
                "WHERE task_id=%s ORDER BY id LIMIT 513",
                (task.id,),
            )
            rows = tuple(cursor.fetchall())
            if len(rows) > _MAX_QUEUE_HISTORY:
                raise RecoveryRejected("inherited invocation queue history exceeds its bound")
            steps = tuple(_decode(row, QueuedRoleStep) for row in rows)
            cursor.execute(
                "SELECT id,task_id,payload_json,sha256 FROM work_queue_execution_baselines "
                "WHERE task_id=%s LIMIT 101",
                (task.id,),
            )
            baseline_rows = tuple(cursor.fetchall())
            if len(baseline_rows) > 100:
                raise RecoveryRejected("inherited invocation baseline history exceeds its bound")
            baselines = tuple(
                sorted(
                    (_decode(row, BaselineQueueConsumption) for row in baseline_rows),
                    key=lambda record: record.binding.sequence,
                )
            )
            cursor.execute("SELECT * FROM work_queue_claims WHERE lease_id=%s", (start.lease_id,))
            claim_row = _required(cursor.fetchone())
            cursor.execute(
                "SELECT * FROM work_queue_events "
                "WHERE lease_id=%s AND event_type='CLAIMED' ORDER BY sequence LIMIT 2",
                (start.lease_id,),
            )
            events = tuple(cursor.fetchall())
            if len(events) != 1:
                raise RecoveryRejected("inherited invocation has no unique original claim event")
            claim = _original_claim(claim_row, events[0])
            require_inherited_invocation_queue(
                start, dispatch, task, scope, project_id, admission, steps, baselines, claim
            )
    finally:
        connection.rollback()
        connection.close()


def _required(row: dict[str, object] | None) -> dict[str, object]:
    if row is None:
        raise RecoveryRejected("inherited invocation is missing a required durable queue record")
    return row


def _original_claim(row: dict[str, object], event: dict[str, object]) -> QueueClaim:
    """Honor a complete immutable snapshot when present, including its original expiry."""
    try:
        return _decode_original_claim(row, event)
    except (KeyError, TypeError) as error:
        raise RecoveryRejected("inherited invocation original claim record is malformed") from error


def _decode_original_claim(row: dict[str, object], event: dict[str, object]) -> QueueClaim:
    payload = TypeAdapter(dict[str, JsonValue]).validate_json(_text(event, "payload_json"))
    current = QueueClaim.model_validate(
        {
            "work_item": payload["work_item"],
            "assignment": json.loads(_text(row, "assignment_json")),
            "lease": json.loads(_text(row, "lease_json")),
            "model_selection": json.loads(_text(row, "model_selection_json")),
            "worker_id": row["worker_id"],
            "claimed_at": event["occurred_at"],
        }
    )
    item, lease = current.work_item, current.lease
    if (
        (row["lease_id"], event["lease_id"]) != (lease.id, lease.id)
        or (row["work_item_id"], event["work_item_id"]) != (item.id, item.id)
        or row["task_id"] != item.task_id
        or row["agent_id"] != lease.agent_id
        or _non_negative_int(row, "capacity_units") != lease.capacity_units
        or MySqlPersistentWorkQueue._parse_time(_text(row, "acquired_at")) != lease.acquired_at
        or MySqlPersistentWorkQueue._parse_time(_text(row, "expires_at")) != lease.expires_at
        or current.claimed_at != lease.acquired_at
        or current.claimed_at != item.updated_at
        or event["event_type"] != "CLAIMED"
        or event["from_status"]
        not in {WorkItemStatus.READY.value, WorkItemStatus.RETRY_SCHEDULED.value}
        or event["to_status"] != WorkItemStatus.LEASED.value
    ):
        raise RecoveryRejected("inherited invocation original claim indices changed")
    TypeAdapter(StageSha256).validate_python(row["owner_token_sha256"])
    detail = payload.get("detail", {})
    if not isinstance(detail, dict):
        raise RecoveryRejected("inherited invocation original claim detail changed")
    if "queue_claim" in detail:
        return require_claim_snapshot(QueueClaim.model_validate(detail["queue_claim"]), current)
    # Historical claims did not seal the original renewable expiry. This is the
    # verified allocation/event, never a fabricated complete immutable snapshot.
    return current


def require_inherited_invocation_queue(
    start: DeliveryInvocationStart,
    dispatch: RecoveryDispatchRecord,
    task: Task,
    scope: RecoveryScope,
    project_id: ProjectId,
    admission: RoleQueueAdmission,
    steps: tuple[QueuedRoleStep, ...],
    baselines: tuple[BaselineQueueConsumption, ...],
    claim: QueueClaim,
) -> None:
    """Pure proof of exact allocation, historical role boundary and source epoch."""
    start.validate_integrity()
    request, item = start.request, claim.work_item
    if (
        (admission.task_id, admission.repository_id, admission.allocation_sha256)
        != (task.id, dispatch.repository_id, dispatch.dispatch_sha256)
        or dispatch.task_id != task.id
        or request.role is not AgentRole.CODER
        or (
            start.work_item_id,
            request.task_id,
            request.role,
            request.attempt,
            start.checkpoint_sequence,
            start.lease_id,
        )
        != (
            item.id,
            item.task_id,
            item.role,
            item.attempt,
            item.checkpoint_sequence,
            claim.lease.id,
        )
        or item.task_id != task.id
        or item.repository_id != dispatch.repository_id
        or item.repository_scopes != (task.repository,)
        or start.started_at < claim.claimed_at
    ):
        raise RecoveryRejected("inherited invocation differs from its original claim or admission")
    by_id = {step.work_item.id: step for step in steps}
    if len(by_id) != len(steps) or item.id not in by_id:
        raise RecoveryRejected("inherited invocation has no unique original role step")
    for step in steps:
        if (
            step.boundary.task_id != task.id
            or step.work_item.repository_id != dispatch.repository_id
            or step.work_item.repository_scopes != (task.repository,)
            or step.allocation_sha256 != dispatch.dispatch_sha256
        ):
            raise RecoveryRejected("inherited invocation role step changed its allocation scope")
    previous = None
    for record in baselines:
        binding = record.binding
        binding.require_task(task)
        binding.require_predecessor(previous)
        if (
            binding.scope.team_id != scope.team_id
            or binding.scope.repository_id != dispatch.repository_id
            or binding.scope.repository_root != task.repository
            or binding.scope.project_id != project_id
        ):
            raise RecoveryRejected("inherited invocation baseline changed its allocation scope")
        previous = binding
    original = by_id[item.id]
    selected, found = resolve_step_overlays(
        original, baselines, baseline_sha256=request.execution_baseline_sha256, latest=False
    )
    if not found:
        _require_inherited_baseline(original, by_id, baselines, request.execution_baseline_sha256)
    if request.execution_baseline_sha256 is not None:
        anchors = tuple(
            record.binding
            for record in baselines
            if record.binding.binding_sha256 == request.execution_baseline_sha256
        )
        if len(anchors) != 1 or anchors[0].execution_base_ref != request.execution_base_ref:
            raise RecoveryRejected("inherited invocation lost its exact execution baseline")
    boundary = selected.boundary
    if (
        boundary.task_id,
        boundary.role,
        boundary.attempt,
        boundary.checkpoint_sequence,
        boundary.source_revision,
    ) != (
        request.task_id,
        request.role,
        request.attempt,
        start.checkpoint_sequence,
        request.source_revision,
    ):
        raise RecoveryRejected("inherited invocation differs from its historical role boundary")


def _require_inherited_baseline(
    original: QueuedRoleStep,
    steps: Mapping[str, QueuedRoleStep],
    records: tuple[BaselineQueueConsumption, ...],
    baseline_sha256: str | None,
) -> None:
    """Authenticate an inherited epoch through bounded immutable queue parent identities."""
    current = original
    seen: set[str] = set()
    while True:
        identity = current.work_item.id
        if identity in seen or len(seen) >= _MAX_QUEUE_HISTORY:
            raise RecoveryRejected("inherited invocation baseline queue parent lineage is cyclic")
        seen.add(identity)
        anchors = tuple(record for record in records if record.next_work_item_id == identity)
        if current == original:
            anchors = tuple(record for record in anchors if record.work_item_id != identity)
        if anchors:
            anchor = anchors[-1]
            bound = (
                resolve_step_overlays(
                    current, records, baseline_sha256=baseline_sha256, latest=False
                )[0]
                if anchor.work_item_id == identity
                else current
            )
            if (
                anchor.binding.binding_sha256 != baseline_sha256
                or bound.boundary.source_revision != anchor.binding.execution_source_revision
                or bound.work_item.repository_id != anchor.binding.scope.repository_id
                or bound.work_item.repository_scopes != (anchor.binding.scope.repository_root,)
                or anchor.task_id != bound.boundary.task_id
            ):
                raise RecoveryRejected(
                    "inherited invocation crossed its exact baseline source epoch"
                )
            if anchor.work_item_id != identity:
                parent = _parent(current, steps)
                if parent is None or parent.work_item.id != anchor.work_item_id:
                    raise RecoveryRejected(
                        "inherited invocation baseline lost its exact predecessor"
                    )
                predecessor = resolve_step_overlays(parent, records)[0]
                if record_digest(predecessor) != anchor.prior_step_sha256:
                    raise RecoveryRejected("inherited invocation baseline predecessor changed")
            return
        parent = _parent(current, steps)
        if parent is None:
            raise RecoveryRejected("inherited invocation has no exact baseline source record")
        current = parent


def _parent(child: QueuedRoleStep, steps: Mapping[str, QueuedRoleStep]) -> QueuedRoleStep | None:
    identity = child.work_item.parent_work_item_id
    if identity is None:
        return None
    parent = steps.get(identity)
    if parent is None:
        raise RecoveryRejected("inherited invocation baseline parent step is missing")
    return parent
