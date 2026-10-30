"""Recovery dispatch ancestry follows exact terminal Delivery source facts."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.dispatch import (
    DispatchCommitRecord,
    RecoveryDispatchRecord,
    _record_digest,
)
from ai_software_engineer.recovery.allocation_lineage import resolve_planner_dispatch
from ai_software_engineer.recovery.models import RecoveryRejected
from tests.manager.test_dispatch_authority import _durable_facts


def _source_checkpoint(
    planner: DispatchCommitRecord,
    *,
    candidate_revision: str | None,
) -> ProjectDeliveryCheckpoint:
    return ProjectDeliveryCheckpoint.create(
        delivery_id="delivery_recovery_source",
        sequence=1,
        repository_id=planner.repository_id,
        repository_root=planner.task.repository,
        preparation_sha256="1" * 64,
        request_id=planner.project_request_id,
        request_revision=1,
        product_checkpoint_sha256="2" * 64,
        product_spec_id="product_spec_source",
        product_spec_sha256="3" * 64,
        approval_id="product_approval_" + "4" * 64,
        approval_sha256="5" * 64,
        technical_design_id="technical_design_source",
        technical_design_sha256="6" * 64,
        execution_plan_id=planner.execution_plan_id,
        execution_plan_sha256=planner.execution_plan_sha256,
        planning_preview_id="planning_preview_" + "7" * 64,
        planning_preview_sha256="8" * 64,
        dispatch_commit_id=planner.id,
        dispatch_commit_sha256=planner.dispatch_sha256,
        task_id=planner.task_id,
        task_revision=7,
        task_status=TaskStatus.BLOCKED,
        candidate_revision=candidate_revision,
        stage=DeliveryStage.BLOCKED,
        stage_attempts=DeliveryStageAttempts(delivering=1),
        next_action=DeliveryNextAction.REQUEST_HUMAN,
        failure_code=DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED,
        failure_summary="Coder retry budget exhausted after an earlier candidate was reviewed",
        failed_stage=DeliveryStage.DELIVERING,
        checkpointed_at=datetime(2026, 10, 30, tzinfo=UTC),
    )


def _recovery_lineage(
    tmp_path: Path, *, candidate_revision: str | None
) -> tuple[RecoveryDispatchRecord, DispatchCommitRecord, ProjectDeliveryCheckpoint]:
    _, _, planner, _, _ = _durable_facts(tmp_path)
    source = _source_checkpoint(planner, candidate_revision=candidate_revision)
    plan_sha256 = "9" * 64
    task_id = f"task_recovery_{plan_sha256[:32]}"
    task = planner.task.model_copy(
        update={
            "id": task_id,
            "metadata": {
                **planner.task.metadata,
                "recovery_plan_sha256": plan_sha256,
                "recovery_source_checkpoint_sha256": source.checkpoint_sha256,
                "recovery_of_task_id": source.task_id,
                "recovery_of_delivery_id": source.delivery_id,
            },
        }
    )
    phases = tuple(
        phase.model_copy(
            update={
                "assignment": phase.assignment.model_copy(update={"task_id": task_id}),
                "lease": phase.lease.model_copy(update={"task_id": task_id}),
            }
        )
        for phase in planner.phases
    )
    recovery = RecoveryDispatchRecord(
        id=f"dispatch_commit_{plan_sha256}",
        repository_id=planner.repository_id,
        task_id=task_id,
        project_request_id=planner.project_request_id,
        execution_plan_id=planner.execution_plan_id,
        execution_plan_sha256=planner.execution_plan_sha256,
        execution_plan_phase_ids=planner.execution_plan_phase_ids,
        recovery_plan_sha256=plan_sha256,
        recovery_task_record_sha256="8" * 64,
        workforce_snapshot_sha256="7" * 64,
        task=task,
        phases=phases,
        committed_at=planner.committed_at,
        dispatch_sha256="0" * 64,
    )
    recovery = recovery.model_copy(update={"dispatch_sha256": _record_digest(recovery)})
    recovery.validate_integrity()
    source.validate_integrity()
    planner.validate_integrity()
    return recovery, planner, source


@pytest.mark.parametrize("candidate_revision", [None, "b" * 40])
def test_recovery_ancestry_accepts_exact_terminal_source_with_historical_candidate(
    tmp_path: Path, candidate_revision: str | None
) -> None:
    recovery, planner, source = _recovery_lineage(tmp_path, candidate_revision=candidate_revision)

    resolved = resolve_planner_dispatch(
        recovery, {recovery.id: recovery, planner.id: planner}, (source,)
    )

    assert resolved == planner


@pytest.mark.parametrize(
    ("metadata_field", "wrong_value"),
    [
        ("recovery_source_checkpoint_sha256", "f" * 64),
        ("recovery_of_task_id", "task_unrelated"),
        ("recovery_of_delivery_id", "delivery_unrelated"),
    ],
)
def test_recovery_ancestry_rejects_wrong_source_identity(
    tmp_path: Path, metadata_field: str, wrong_value: str
) -> None:
    recovery, planner, source = _recovery_lineage(tmp_path, candidate_revision="b" * 40)
    task = recovery.task.model_copy(
        update={"metadata": {**recovery.task.metadata, metadata_field: wrong_value}}
    )
    recovery = recovery.model_copy(update={"task": task, "dispatch_sha256": "0" * 64})
    recovery = recovery.model_copy(update={"dispatch_sha256": _record_digest(recovery)})

    with pytest.raises(RecoveryRejected, match="recovery source is absent"):
        resolve_planner_dispatch(recovery, {recovery.id: recovery, planner.id: planner}, (source,))


def test_recovery_ancestry_rejects_unknown_source_dispatch(tmp_path: Path) -> None:
    recovery, planner, source = _recovery_lineage(tmp_path, candidate_revision="b" * 40)
    source = ProjectDeliveryCheckpoint.create(
        **{
            **source.to_wire(),
            "dispatch_commit_id": "dispatch_commit_" + "f" * 64,
        }
    )
    task = recovery.task.model_copy(
        update={
            "metadata": {
                **recovery.task.metadata,
                "recovery_source_checkpoint_sha256": source.checkpoint_sha256,
            }
        }
    )
    recovery = recovery.model_copy(update={"task": task, "dispatch_sha256": "0" * 64})
    recovery = recovery.model_copy(update={"dispatch_sha256": _record_digest(recovery)})

    with pytest.raises(RecoveryRejected, match="candidate successor ancestry is incomplete"):
        resolve_planner_dispatch(recovery, {recovery.id: recovery, planner.id: planner}, (source,))


def test_recovery_ancestry_rejects_changed_approved_plan(tmp_path: Path) -> None:
    recovery, planner, source = _recovery_lineage(tmp_path, candidate_revision="b" * 40)
    changed_plan_sha256 = "e" * 64
    assert changed_plan_sha256 != planner.execution_plan_sha256
    task = recovery.task.model_copy(
        update={
            "metadata": {
                **recovery.task.metadata,
                "execution_plan_sha256": changed_plan_sha256,
            }
        }
    )
    recovery = recovery.model_copy(
        update={
            "task": task,
            "execution_plan_sha256": changed_plan_sha256,
            "dispatch_sha256": "0" * 64,
        }
    )
    recovery = recovery.model_copy(update={"dispatch_sha256": _record_digest(recovery)})
    recovery = RecoveryDispatchRecord.model_validate(recovery.to_wire())
    recovery.validate_integrity()

    with pytest.raises(RecoveryRejected, match="candidate successor changed its approved plan"):
        resolve_planner_dispatch(recovery, {recovery.id: recovery, planner.id: planner}, (source,))


def test_recovery_ancestry_rejects_nonterminal_source(tmp_path: Path) -> None:
    recovery, planner, source = _recovery_lineage(tmp_path, candidate_revision="b" * 40)
    source = ProjectDeliveryCheckpoint.create(
        **{
            **source.to_wire(),
            "stage": DeliveryStage.DELIVERING,
            "failure_code": None,
            "failure_summary": None,
            "failed_stage": None,
        }
    )
    task = recovery.task.model_copy(
        update={
            "metadata": {
                **recovery.task.metadata,
                "recovery_source_checkpoint_sha256": source.checkpoint_sha256,
            }
        }
    )
    recovery = recovery.model_copy(update={"task": task, "dispatch_sha256": "0" * 64})
    recovery = recovery.model_copy(update={"dispatch_sha256": _record_digest(recovery)})

    with pytest.raises(RecoveryRejected, match="recovery source is absent"):
        resolve_planner_dispatch(recovery, {recovery.id: recovery, planner.id: planner}, (source,))
