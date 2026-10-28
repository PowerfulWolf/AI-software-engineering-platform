from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_software_engineer.domain.enums import TaskStatus
from ai_software_engineer.manager.active_successor import active_successor_dispatch
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.manager.production_host import TeamHost


def _checkpoint(root: Path) -> ProjectDeliveryCheckpoint:
    return ProjectDeliveryCheckpoint.create(
        delivery_id="delivery_alpha",
        sequence=1,
        repository_id="repository_alpha",
        repository_root=str(root),
        preparation_sha256="a" * 64,
        request_id="request_alpha",
        request_revision=1,
        product_checkpoint_sha256="b" * 64,
        product_spec_id="product_alpha",
        product_spec_sha256="c" * 64,
        approval_id="approval_alpha",
        approval_sha256="d" * 64,
        technical_design_id="design_alpha",
        technical_design_sha256="e" * 64,
        execution_plan_id="plan_alpha",
        execution_plan_sha256="f" * 64,
        planning_preview_id="preview_alpha",
        planning_preview_sha256="1" * 64,
        dispatch_commit_id="dispatch_commit_" + "2" * 64,
        dispatch_commit_sha256="3" * 64,
        task_id="task_source",
        task_revision=1,
        task_status=TaskStatus.BLOCKED,
        stage=DeliveryStage.BLOCKED,
        stage_attempts=DeliveryStageAttempts(delivering=1),
        next_action=DeliveryNextAction.REQUEST_HUMAN,
        failure_code="INVALID_AGENT_OUTPUT",
        failure_summary="preserved source",
        failed_stage=DeliveryStage.DELIVERING,
        checkpointed_at=datetime(2026, 10, 28, 8, tzinfo=UTC),
    )


def _successor(
    checkpoint: ProjectDeliveryCheckpoint,
    *,
    task_id: str = "task_successor",
    source_delivery_id: str | None = None,
) -> RecoveryDispatchRecord:
    task = SimpleNamespace(
        id=task_id,
        metadata={
            "recovery_of_task_id": checkpoint.task_id,
            "recovery_of_delivery_id": source_delivery_id or checkpoint.delivery_id,
            "recovery_source_checkpoint_sha256": checkpoint.checkpoint_sha256,
        },
    )
    return RecoveryDispatchRecord.model_construct(
        id="dispatch_commit_" + "4" * 64,
        repository_id=checkpoint.repository_id,
        task_id=task_id,
        task=task,
        dispatch_sha256="5" * 64,
        committed_at=checkpoint.checkpointed_at + timedelta(minutes=1),
    )


def test_active_successor_is_selected_from_exact_recovery_lineage(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)
    successor = _successor(checkpoint)

    result = active_successor_dispatch(
        checkpoint,
        (checkpoint,),
        (successor,),
        task_status=lambda task_id: "IMPLEMENTING" if task_id == successor.task_id else None,
    )

    assert result is successor


def test_active_successor_rejects_wrong_source_checkpoint(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)
    successor = _successor(checkpoint)
    successor.task.metadata["recovery_source_checkpoint_sha256"] = "9" * 64

    with pytest.raises(ValueError, match="source checkpoint"):
        active_successor_dispatch(
            checkpoint,
            (checkpoint,),
            (successor,),
            task_status=lambda _task_id: "IMPLEMENTING",
        )


def test_active_successor_rejects_ambiguous_live_successors(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)
    first = _successor(checkpoint, task_id="task_successor_a")
    second = _successor(checkpoint, task_id="task_successor_b")

    with pytest.raises(ValueError, match="ambiguous"):
        active_successor_dispatch(
            checkpoint,
            (checkpoint,),
            (first, second),
            task_status=lambda _task_id: "IMPLEMENTING",
        )


def test_active_successor_rejects_history_head_drift(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)
    successor = _successor(checkpoint)
    stale_head = checkpoint.model_copy(
        update={"checkpointed_at": checkpoint.checkpointed_at + timedelta(seconds=1)}
    )

    with pytest.raises(ValueError, match="history head"):
        active_successor_dispatch(
            checkpoint,
            (stale_head,),
            (successor,),
            task_status=lambda _task_id: "IMPLEMENTING",
        )


def test_active_successor_ignores_foreign_recovery_source(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)
    successor = _successor(checkpoint, source_delivery_id="delivery_foreign")

    assert (
        active_successor_dispatch(
            checkpoint,
            (checkpoint,),
            (successor,),
            task_status=lambda _task_id: "IMPLEMENTING",
        )
        is None
    )


def test_host_wait_binding_accepts_successor_before_native_checkpoint_publish(
    tmp_path: Path,
) -> None:
    checkpoint = _checkpoint(tmp_path)
    successor = _successor(checkpoint)
    host = object.__new__(TeamHost)
    host._runtime = lambda _project_id: SimpleNamespace(
        requirements=SimpleNamespace(
            status=lambda _delivery_id: SimpleNamespace(
                checkpoint=SimpleNamespace(children=(SimpleNamespace(checkpoint=checkpoint),))
            )
        )
    )
    host._active_successor_dispatch = lambda _project_id, _checkpoint: successor

    native, dispatch = host._delivery_wait_binding(
        "project_alpha", "delivery_multi_alpha", successor.task_id
    )

    assert native is checkpoint
    assert dispatch is successor


def test_host_wait_binding_rejects_foreign_work_item(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)
    host = object.__new__(TeamHost)
    host._runtime = lambda _project_id: SimpleNamespace(
        requirements=SimpleNamespace(
            status=lambda _delivery_id: SimpleNamespace(
                checkpoint=SimpleNamespace(children=(SimpleNamespace(checkpoint=checkpoint),))
            )
        )
    )
    host._active_successor_dispatch = lambda _project_id, _checkpoint: None

    with pytest.raises(ValueError, match="不属于当前 Project Requirement"):
        host._delivery_wait_binding("project_alpha", "delivery_multi_alpha", "task_foreign")


def test_effective_baseline_checkpoint_rebinds_successor_without_journal_write(
    tmp_path: Path,
) -> None:
    checkpoint = _checkpoint(tmp_path)
    successor = _successor(checkpoint)
    host = object.__new__(TeamHost)

    projected = host._effective_baseline_checkpoint(
        checkpoint,
        successor,
        task_revision=2,
        task_status=TaskStatus.IMPLEMENTING,
    )

    assert projected.delivery_id == checkpoint.delivery_id
    assert projected.dispatch_commit_id == successor.id
    assert projected.dispatch_commit_sha256 == successor.dispatch_sha256
    assert projected.task_id == successor.task_id
    assert projected.task_revision == 2
    assert projected.task_status is TaskStatus.IMPLEMENTING
    assert projected.stage is DeliveryStage.DELIVERING
    assert projected.failure_code is None
    assert projected.failure_summary is None
    assert projected.failed_stage is None
    assert projected.checkpoint_sha256 == projected.recompute_sha256()
    assert checkpoint.task_id != projected.task_id
