"""Delivery hash-chain adoption for independently triggered successor Tasks."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.orchestration import RetryDeliveryResult
from ai_software_engineer.project_manager.delivery import (
    ProjectDeliveryCheckpointCatalog,
    UnifiedProjectEntryService,
)
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.project_manager.dispatch import ContinuationDispatchRecord
from tests.recovery.test_execution_records import continuation_allocation

NOW = datetime(2026, 9, 9, 8, 0, tzinfo=UTC)


def _service(
    tmp_path: Path, dispatch: ContinuationDispatchRecord
) -> tuple[UnifiedProjectEntryService, FileProjectDeliveryCheckpointStore]:
    registry = tmp_path / "registry"
    state = registry / dispatch.project_id / "state"
    state.mkdir(parents=True)
    store = FileProjectDeliveryCheckpointStore(state / "project-deliveries")
    source = ProjectDeliveryCheckpoint.create(
        delivery_id=dispatch.source_delivery_id,
        sequence=1,
        project_id=dispatch.project_id,
        project_root=dispatch.task.repository,
        preparation_sha256="1" * 64,
        request_id=dispatch.project_request_id,
        request_revision=1,
        product_checkpoint_sha256="2" * 64,
        product_spec_id="product_spec_alpha",
        product_spec_sha256="3" * 64,
        approval_id="product_approval_" + "4" * 64,
        approval_sha256="5" * 64,
        technical_design_id="technical_design_alpha",
        technical_design_sha256="6" * 64,
        execution_plan_id=dispatch.execution_plan_id,
        execution_plan_sha256=dispatch.execution_plan_sha256,
        planning_preview_id="planning_preview_" + "7" * 64,
        planning_preview_sha256="8" * 64,
        dispatch_commit_id=dispatch.source_dispatch_id,
        dispatch_commit_sha256="9" * 64,
        task_id=dispatch.source_task_id,
        task_revision=7,
        task_status=TaskStatus.BLOCKED,
        candidate_revision=dispatch.source_revision,
        stage=DeliveryStage.BLOCKED,
        stage_attempts=DeliveryStageAttempts(delivering=1),
        next_action=DeliveryNextAction.REQUEST_HUMAN,
        failure_code=DeliveryFailureCode.TRANSIENT_PROVIDER_FAILURE,
        failure_summary="QA provider stopped after the candidate was committed",
        checkpointed_at=NOW,
    )
    store.put(source)
    return (
        UnifiedProjectEntryService(
            backend=Mock(),
            catalog=ProjectDeliveryCheckpointCatalog(registry),
        ),
        store,
    )


def test_continuation_is_attached_once_and_seals_successor_candidate(tmp_path: Path) -> None:
    dispatch = continuation_allocation(tmp_path)
    service, store = _service(tmp_path, dispatch)

    started = service.begin_continuation(dispatch, at=NOW + timedelta(minutes=1))
    assert started.checkpoint.stage is DeliveryStage.DELIVERING
    assert started.checkpoint.task_id == dispatch.task_id
    assert started.checkpoint.dispatch_commit_id == dispatch.id
    assert started.checkpoint.candidate_revision is None
    assert service.begin_continuation(dispatch, at=NOW + timedelta(minutes=2)) == started

    task = dispatch.task.model_copy(
        update={
            "status": TaskStatus.DONE,
            "attempts": 1,
            "updated_at": NOW + timedelta(minutes=3),
        }
    )
    delivered = RetryDeliveryResult(
        task=task,
        candidate_revision="a" * 40,
        artifact_ids=("art_plan", "art_impl", "art_qa_001", "art_review"),
        context_manifest_ids=tuple(f"ctx_{index:064x}" for index in range(1, 5)),
        run_ids=("run_plan", "run_coder", "run_qa_001", "run_review"),
        event_ids=("evt_plan", "evt_coder", "evt_qa_001", "evt_review"),
    )
    finished = service.finish_continuation(
        dispatch,
        delivered,
        at=task.updated_at,
    )

    assert finished.checkpoint.stage is DeliveryStage.DONE
    assert finished.checkpoint.candidate_revision == "a" * 40
    assert finished.checkpoint.task_status is TaskStatus.DONE
    assert len(store.list(dispatch.source_delivery_id)) == 3
    assert service.finish_continuation(dispatch, delivered, at=task.updated_at) == finished
    assert len(store.list(dispatch.source_delivery_id)) == 3
