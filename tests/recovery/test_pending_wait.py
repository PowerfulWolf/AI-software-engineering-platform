"""A durable released wait reattaches approved recovery progress without replay."""

from dataclasses import replace
from datetime import timedelta
from itertools import pairwise
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from ai_software_engineer.domain import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.dispatch import _record_digest
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.entry import NativeRecoveryExecution, NativeRecoveryPending
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryRejected
from ai_software_engineer.recovery.records import RecoveryInvocationRecord, RecoverySeedRecord
from ai_software_engineer.recovery.resume import DeliveryResumeOutcome
from ai_software_engineer.work_queue.execution_store import (
    QueuedRoleStep,
    RoleQueueAdmission,
    record_digest,
)
from tests.recovery.test_pending_execution import PendingFixture, fixture
from tests.recovery.test_task_record import record_for
from tests.work_queue.test_dispatcher import item


def admitted_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PendingFixture:
    f = fixture(tmp_path, monkeypatch)
    store, plan = f.recovery.open_plan(f.path)
    authorization = store.get_authorization(plan.plan_sha256)
    record = record_for(plan, authorization)
    record = record.model_copy(
        update={
            "task": record.task.model_copy(
                update={
                    "max_attempts": 8,
                    "metadata": {
                        **record.task.metadata,
                        "execution_plan_id": f.dispatch.execution_plan_id,
                    },
                }
            )
        }
    )
    record = record.model_copy(update={"record_sha256": record.recompute_sha256()})
    store.put_task_record(record)
    dispatch = f.dispatch.model_copy(
        update={
            "task": record.task,
            "project_request_id": record.rebound_request.id,
            "execution_plan_sha256": plan.source.execution_plan_sha256,
            "recovery_task_record_sha256": record.record_sha256,
        }
    )
    dispatch = dispatch.model_copy(update={"dispatch_sha256": _record_digest(dispatch)})
    type(dispatch).model_validate(dispatch.to_wire())
    capture = plan.capture.to_capture()
    capture = replace(
        capture,
        worktree=replace(
            capture.worktree,
            task_id=record.task.id,
            head_revision=record.task.base_ref,
            branch=record.task.branch_name or f"ai/{record.task.id}/attempt-1",
        ),
    )
    seed = RecoverySeedRecord.create(
        plan_sha256=plan.plan_sha256,
        dispatch_sha256=dispatch.dispatch_sha256,
        capture=CapturedChanges.from_capture(capture),
    )
    store.put_seed(seed)
    invocation = RecoveryInvocationRecord(
        recovery_plan_sha256=plan.plan_sha256,
        seed_record_sha256=seed.record_sha256,
        run_id="run_original_recovery",
        context_manifest_id="ctx_" + "a" * 64,
        record_sha256="0" * 64,
    )
    invocation = invocation.model_copy(update={"record_sha256": invocation.recompute_sha256()})
    store.put_invocation(invocation)
    snapshot = f.snapshot.model_copy(
        update={
            "task": record.task.model_copy(
                update={
                    "status": TaskStatus.IMPLEMENTING,
                    "attempts": 4,
                    "updated_at": max(f.snapshot.task.updated_at, record.task.created_at)
                    + timedelta(minutes=1),
                }
            ),
            "task_revision": 8,
        }
    )
    f.dispatch, f.snapshot = dispatch, snapshot
    f.backend._delivery_snapshot.return_value = snapshot
    monkeypatch.setattr(f.recovery, "_dispatch_for", lambda *_: dispatch)
    monkeypatch.setattr(
        "ai_software_engineer.recovery.resume.read_recovery_task", lambda *_: snapshot.task
    )
    return f


def test_admitted_fourth_attempt_wait_reattaches_before_first_attempt_interruption_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = admitted_fixture(tmp_path, monkeypatch)
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts(
            task_id=f.snapshot.task.id,
            work_item_id="work_pending_recovery",
            role=AgentRole.CODER,
            classification="INVALID_OUTPUT",
            source_revision=f.snapshot.task.base_ref,
            task_intent_sha256=task_intent_sha256(f.snapshot.task),
            checkpoint_sequence=8,
            budget_available=True,
        )
    )
    pending = NativeRecoveryExecution(
        f.plan, f.dispatch, NativeRecoveryPending(f.snapshot, disposition)
    )
    reader = Mock(return_value=pending)
    monkeypatch.setattr(f.recovery, "pending_execution_wait", reader, raising=False)
    interruption = Mock()
    interruption.propose.side_effect = RecoveryRejected("原中断恢复只支持第 1 次执行")
    monkeypatch.setattr(
        "ai_software_engineer.recovery.resume.RecoveryInterruptionService", lambda *_: interruption
    )
    result = f.controller._continue_coder_recovery(
        f.current, ResumeProjectDelivery(delivery_id=f.current.delivery_id)
    )
    assert result.outcome is DeliveryResumeOutcome.WAITING_HUMAN
    assert result.checkpoint.stage is DeliveryStage.DELIVERING
    assert result.checkpoint.task_id == f.snapshot.task.id
    assert result.checkpoint.task_status is TaskStatus.IMPLEMENTING
    assert result.checkpoint.task_revision == 8
    assert f.journal.list(f.current.delivery_id)[0] == f.current
    assert disposition.next_action in result.next_action
    reader.assert_called_once_with(f.path)
    interruption.propose.assert_not_called()
    f.execution.assert_not_called()
    f.backend.run_delivery.assert_not_called()


def queue_reader(
    f: PendingFixture,
    monkeypatch: pytest.MonkeyPatch,
    fault: str = "",
) -> tuple[MagicMock, MagicMock]:
    task = f.snapshot.task
    role = {
        TaskStatus.IMPLEMENTING: AgentRole.CODER,
        TaskStatus.QA: AgentRole.QA,
        TaskStatus.REVIEW: AgentRole.REVIEWER,
    }[task.status]
    source = "e" * 40 if fault == "baseline" else f.snapshot.candidate_revision or task.base_ref
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts(
            task_id=task.id,
            work_item_id="work_pending_recovery",
            role=role,
            classification="INVALID_OUTPUT",
            source_revision=source,
            task_intent_sha256="f" * 64 if fault == "intent" else task_intent_sha256(task),
            checkpoint_sequence=f.snapshot.task_revision,
            budget_available=True,
        )
    )
    work = item(
        id="work_pending_recovery",
        task_id=task.id,
        repository_id=f.dispatch.repository_id,
        role=role,
        attempt=task.attempts,
        repository_scopes=(task.repository,),
        checkpoint_sequence=f.snapshot.task_revision,
        status=WorkItemStatus.WAITING_DEPENDENCY,
        wait_reason=disposition.reason,
        wait_disposition=disposition,
    )
    if fault in {"closed", "running", "untyped"}:
        work = work.model_copy(
            update={
                "status": {
                    "closed": WorkItemStatus.CLOSED,
                    "running": WorkItemStatus.RUNNING,
                    "untyped": WorkItemStatus.WAITING_DEPENDENCY,
                }[fault],
                "wait_reason": disposition.reason if fault == "untyped" else None,
                "wait_disposition": None,
            }
        )
    boundary = RoleRunBoundary(
        task.id,
        role,
        task.attempts,
        f.snapshot.task_revision,
        "d" * 40 if fault == "source" else source,
    )
    step = QueuedRoleStep(
        work_item=work,
        boundary=boundary,
        allocation_sha256="d" * 64 if fault == "allocation" else f.dispatch.dispatch_sha256,
    )
    admission = RoleQueueAdmission(
        task_id=task.id,
        repository_id=f.dispatch.repository_id,
        allocation_sha256=f.dispatch.dispatch_sha256,
        legacy_artifacts=(),
    )

    def row(value):
        return {
            "id": task.id if isinstance(value, RoleQueueAdmission) else work.id,
            "task_id": task.id,
            "payload_json": value.model_dump_json(),
            "sha256": record_digest(value),
        }

    queue_row = {
        key: getattr(work, key)
        for key in (
            "id",
            "task_id",
            "repository_id",
            "role",
            "attempt",
            "checkpoint_sequence",
            "status",
        )
    }
    queue_row.update(
        role=work.role.value, status=work.status.value, payload_json=work.model_dump_json()
    )
    if fault.startswith("row_"):
        key = fault.removeprefix("row_")
        queue_row[key] = {
            "id": "work_foreign",
            "task_id": "task_foreign",
            "repository_id": "repository_foreign",
            "role": "qa",
            "attempt": 99,
            "checkpoint_sequence": 99,
            "status": "CLOSED",
        }[key]
    current_claim = {
        "task_id": task.id,
        "work_item_id": work.id,
        "state": "ACTIVE" if fault == "active" else "RELEASED",
        "ended_at": None if fault == "ended" else task.updated_at.isoformat(),
    }
    claims = [] if fault == "no_claim" else [current_claim]
    if fault == "other_active":
        claims.append({**current_claim, "work_item_id": "work_foreign", "state": "ACTIVE"})
    statuses = [
        TaskStatus.NEW,
        TaskStatus.PLANNING,
        TaskStatus.IMPLEMENTING,
        TaskStatus.CONTINUE_REQUIRED,
        TaskStatus.QUEUED,
        TaskStatus.IMPLEMENTING,
        TaskStatus.QA,
    ]
    statuses.extend(
        {
            TaskStatus.IMPLEMENTING: [TaskStatus.REVIEW, TaskStatus.IMPLEMENTING],
            TaskStatus.QA: [TaskStatus.IMPLEMENTING, TaskStatus.QA],
            TaskStatus.REVIEW: [TaskStatus.REVIEW],
        }[task.status]
    )
    event_rows = []
    for revision, (before, after) in enumerate(pairwise(statuses), 1):
        event = StateEvent(
            event_id=f"evt_pending_{revision}",
            task_id=task.id,
            from_status=before,
            to_status=after,
            actor=AgentRole.ORCHESTRATOR,
            attempt=task.attempts,
            reason="candidate_ready" if after is TaskStatus.QA else "checkpoint",
            artifact_ids=(),
            source_revision=f.snapshot.candidate_revision or task.base_ref,
            occurred_at=task.updated_at,
        )
        event_rows.append(
            {
                "event_id": event.event_id,
                "task_id": task.id,
                "revision": revision,
                "payload_json": event.model_dump_json(),
            }
        )
    if fault == "event_gap":
        event_rows.pop()
    elif fault in {"event_row_id", "event_row_task", "event_status", "event_chain"}:
        if fault == "event_row_id":
            event_rows[-1]["event_id"] = "evt_foreign"
        elif fault == "event_row_task":
            event_rows[-1]["task_id"] = "task_foreign"
        else:
            event = StateEvent.model_validate_json(event_rows[-1]["payload_json"])
            event = event.model_copy(
                update={
                    "to_status" if fault == "event_status" else "from_status": TaskStatus.BLOCKED
                }
            )
            event_rows[-1]["payload_json"] = event.model_dump_json()
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [
        None
        if fault == "no_task"
        else {
            "id": task.id,
            "payload_json": task.model_dump_json(),
            "revision": f.snapshot.task_revision,
            "status": task.status.value,
        },
        None if fault == "no_admission" else row(admission),
        None if fault == "no_step" else row(step),
    ]
    cursor.fetchall.side_effect = [
        event_rows,
        [queue_row, queue_row] if fault == "ambiguous" else [queue_row],
        claims,
    ]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(
        "ai_software_engineer.recovery.pending_wait.open_mysql_connection", lambda _: connection
    )
    f.recovery.environment[f.recovery.config.database.dsn_env] = "offline"
    return connection, cursor


@pytest.mark.parametrize("source", ["original", "baseline"])
@pytest.mark.parametrize("status", [TaskStatus.IMPLEMENTING, TaskStatus.QA, TaskStatus.REVIEW])
def test_real_adoption_reader_uses_exact_released_wait_and_never_executes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    status: TaskStatus,
) -> None:
    f = admitted_fixture(tmp_path, monkeypatch)
    f.snapshot = f.snapshot.model_copy(
        update={
            "task": f.snapshot.task.model_copy(update={"status": status}),
            "task_revision": 7 if status is TaskStatus.REVIEW else 8,
            "candidate_revision": "a" * 40 if status is not TaskStatus.IMPLEMENTING else None,
        }
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.resume.read_recovery_task", lambda *_: f.snapshot.task
    )
    f.backend._delivery_snapshot.side_effect = AssertionError("只读接回不得构造写入型 repository")
    connection, cursor = queue_reader(f, monkeypatch, fault=source)
    result = f.controller._continue_coder_recovery(
        f.current, ResumeProjectDelivery(delivery_id=f.current.delivery_id)
    )
    assert result.checkpoint.stage is DeliveryStage.DELIVERING
    assert result.checkpoint.task_id == f.snapshot.task.id
    assert result.checkpoint.task_revision == f.snapshot.task_revision
    assert result.checkpoint.task_status is status
    assert result.checkpoint.candidate_revision == f.snapshot.candidate_revision or (
        status is TaskStatus.IMPLEMENTING
        and result.checkpoint.candidate_revision == f.snapshot.task.base_ref
    )
    f.execution.assert_not_called()
    f.backend.run_delivery.assert_not_called()
    f.backend._delivery_snapshot.assert_not_called()
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()
    assert all(
        call.args[0].startswith(("SELECT", "START TRANSACTION"))
        for call in cursor.execute.call_args_list
    )


@pytest.mark.parametrize("fault", ["no_task", "closed", "running", "untyped"])
def test_durable_reader_does_not_invent_a_wait_from_missing_or_historical_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    f = admitted_fixture(tmp_path, monkeypatch)
    queue_reader(f, monkeypatch, fault)
    assert f.recovery.pending_execution_wait(f.path) is None
    assert f.journal.current(f.current.delivery_id) == f.current
    f.execution.assert_not_called()
    f.backend._delivery_snapshot.assert_not_called()


@pytest.mark.parametrize(
    "fault",
    [
        "intent",
        "source",
        "allocation",
        "ambiguous",
        "no_admission",
        "no_step",
        "active",
        "ended",
        "no_claim",
        "other_active",
        "row_id",
        "row_task_id",
        "row_repository_id",
        "row_role",
        "row_attempt",
        "row_checkpoint_sequence",
        "row_status",
        "event_gap",
        "event_row_id",
        "event_row_task",
        "event_status",
        "event_chain",
    ],
)
def test_durable_reader_rejects_drift_or_unreleased_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    f = admitted_fixture(tmp_path, monkeypatch)
    connection, _ = queue_reader(f, monkeypatch, fault)
    with pytest.raises(RecoveryRejected):
        f.recovery.pending_execution_wait(f.path)
    assert f.journal.current(f.current.delivery_id) == f.current
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()
    f.execution.assert_not_called()
    f.backend._delivery_snapshot.assert_not_called()


@pytest.mark.parametrize("record", ["authorization", "task", "seed", "invocation"])
def test_wait_adoption_requires_every_original_approved_recovery_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record: str,
) -> None:
    f = admitted_fixture(tmp_path, monkeypatch)
    connection, _ = queue_reader(f, monkeypatch)
    (tmp_path / "recovery" / f"{record}-{f.plan.plan_sha256}.json").unlink()
    with pytest.raises(RecoveryRejected):
        f.recovery.pending_execution_wait(f.path)
    connection.cursor.assert_not_called()
    assert f.journal.current(f.current.delivery_id) == f.current
    f.execution.assert_not_called()
    f.backend._delivery_snapshot.assert_not_called()


@pytest.mark.parametrize("fault", ["dispatch", "seed", "invocation_seed", "invocation_plan"])
def test_wait_adoption_rejects_changed_approved_dispatch_or_seed_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    f = admitted_fixture(tmp_path, monkeypatch)
    connection, _ = queue_reader(f, monkeypatch)
    store, plan = f.recovery.open_plan(f.path)
    if fault == "dispatch":
        dispatch = f.dispatch.model_copy(update={"recovery_task_record_sha256": "f" * 64})
        dispatch = dispatch.model_copy(update={"dispatch_sha256": _record_digest(dispatch)})
        monkeypatch.setattr(f.recovery, "_dispatch_for", lambda *_: dispatch)
    elif fault == "seed":
        seed = store.get_seed(plan.plan_sha256).model_copy(update={"dispatch_sha256": "f" * 64})
        seed = seed.model_copy(update={"record_sha256": seed.recompute_sha256()})
        invocation = store.get_invocation(plan.plan_sha256).model_copy(
            update={
                "seed_record_sha256": seed.record_sha256,
            }
        )
        invocation = invocation.model_copy(update={"record_sha256": invocation.recompute_sha256()})
        monkeypatch.setattr(store, "get_seed", lambda _: seed)
        monkeypatch.setattr(store, "get_invocation", lambda _: invocation)
    else:
        invocation = store.get_invocation(plan.plan_sha256).model_copy(
            update={
                "seed_record_sha256" if fault == "invocation_seed" else "recovery_plan_sha256": (
                    "f" * 64
                )
            }
        )
        invocation = invocation.model_copy(update={"record_sha256": invocation.recompute_sha256()})
        monkeypatch.setattr(store, "get_invocation", lambda _: invocation)
    with pytest.raises(RecoveryRejected, match="匹配的精确批准"):
        f.recovery.pending_execution_wait(f.path)
    connection.cursor.assert_not_called()
    assert f.journal.current(f.current.delivery_id) == f.current
    f.execution.assert_not_called()
    f.backend._delivery_snapshot.assert_not_called()
