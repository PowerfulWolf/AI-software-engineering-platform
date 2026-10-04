"""Interruption history is read-only and cannot replace current scheduling facts."""

from pathlib import Path

import pytest

from ai_software_engineer.domain.continuation import (
    InterruptionContinuationPolicy,
    task_intent_sha256,
)
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.orchestration.continuation_models import ExecutionInterruptionReceipt
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.team_view.models import (
    DeliveryExecutionView,
    RoleQueueView,
    ScopeView,
    TaskView,
)
from ai_software_engineer.team_view.reader import _continuation_history, _with_execution_state
from tests.domain.factories import make_task
from tests.orchestration.test_continuation_records import make_admission, make_receipt


def test_receipt_and_policy_admission_are_complete_read_only_history(tmp_path: Path) -> None:
    receipt = make_receipt(tmp_path)
    task = make_task().model_copy(
        update={
            "id": receipt.request.task_id,
            "base_ref": receipt.request.source_revision,
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
            "interruption_continuation_policy": InterruptionContinuationPolicy(),
        }
    )
    receipt = ExecutionInterruptionReceipt.create(
        **{**receipt.to_wire(), "task_intent_sha256": task_intent_sha256(task)}
    )
    sidecar = tmp_path / "sidecar"
    parent = sidecar / "state" / "continuations"
    parent.mkdir(parents=True, mode=0o700)
    store = FileContinuationStore.initialize(parent / task.id, task_id=task.id)
    store.put_receipt(receipt)
    store.put_admission(make_admission(receipt))
    before = {path: path.read_bytes() for path in sidecar.rglob("*") if path.is_file()}
    history, observed = _continuation_history(sidecar, task, receipt.scope)
    assert observed == receipt
    assert len(history) == 2
    assert history[0].details["is_progress_or_candidate"] is False
    assert history[1].details["authorization_source"] == "authorized_by_policy"
    assert history[0].task_id == history[1].task_id == task.id
    assert history[0].run_id != history[1].run_id
    assert before == {path: path.read_bytes() for path in sidecar.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="delivery facts"):
        _continuation_history(
            sidecar, task, receipt.scope.model_copy(update={"project_id": "project_foreign"})
        )
    with pytest.raises(ValueError, match="delivery facts"):
        _continuation_history(
            sidecar, task.model_copy(update={"title": "changed scope"}), receipt.scope
        )
    with pytest.raises(ValueError, match="delivery facts"):
        _continuation_history(
            sidecar,
            task.model_copy(update={"interruption_continuation_policy": None}),
            receipt.scope,
        )


def test_missing_continuation_history_creates_no_directory(tmp_path: Path) -> None:
    receipt = make_receipt(tmp_path)
    task = make_task().model_copy(update={"id": receipt.request.task_id})
    sidecar = tmp_path / "missing-sidecar"
    assert _continuation_history(sidecar, task, receipt.scope) == ((), None)
    assert not sidecar.exists()


def test_old_receipt_references_do_not_mask_the_current_qa_claim() -> None:
    now = make_task().created_at
    task = TaskView(
        id="delivery_history",
        project_id="project_history",
        request_id="delivery_multi_history",
        task_id="task_history",
        title="history",
        scope=ScopeView(root="/repo", selected_paths=(".",)),
        status="QA",
        checkpoint_stage="DELIVERING",
        terminal=False,
        last_activity=now,
        next_action="old interruption guidance",
        execution=DeliveryExecutionView(
            state="WAITING",
            responsibility="engineering",
            reason_code="WORK_INTERRUPTED",
            reason="Old interruption",
            next_action="Old recovery",
            policy_id="a" * 64,
            receipt_uri="receipt://old-coder",
        ),
        role_queue=(
            RoleQueueView(
                work_item_id="work_qa_history",
                role=AgentRole.QA,
                attempt=2,
                status=WorkItemStatus.RUNNING,
                lease_liveness="LEASE_VALID",
            ),
        ),
    )
    projected = _with_execution_state(task)
    assert projected.execution is not None and projected.execution.state == "RUNNING"
    assert projected.execution.responsibility == "team"
    assert projected.blocker is None
    assert projected.next_action.startswith("QA 正在执行")
    assert projected.execution.receipt_uri == "receipt://old-coder"
