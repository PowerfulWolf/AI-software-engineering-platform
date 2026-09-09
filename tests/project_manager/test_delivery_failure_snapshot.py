"""Runtime failure must not leave the parent displaying its pre-run NEW snapshot."""

from datetime import timedelta
from pathlib import Path
from typing import Never

import pytest

from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.project_manager.delivery import (
    ApproveProductSpec,
    DeliveryBackendFailure,
    DeliveryCommandRejected,
    DeliveryFailureSnapshot,
    ProjectDeliveryCheckpointCatalog,
    StartProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryStage,
    ProjectDeliveryCheckpoint,
)
from tests.e2e.test_unified_project_entry import NOW, _copy_fixture, _OfflineBackend


class FailedRuntimeBackend(_OfflineBackend):
    wrong_identity = False

    def run_delivery(self, checkpoint: ProjectDeliveryCheckpoint) -> Never:
        assert self.dispatch is not None
        task = self.dispatch.task.model_copy(
            update={
                "id": "task_other" if self.wrong_identity else self.dispatch.task.id,
                "status": TaskStatus.FAILED,
                "attempts": 1,
                "updated_at": NOW + timedelta(hours=1),
            }
        )
        raise DeliveryBackendFailure(
            DeliveryFailureCode.INVARIANT_VIOLATION,
            "Delivery stopped safely",
            snapshot=DeliveryFailureSnapshot(
                task=task,
                task_revision=4,
                candidate_revision="c" * 40,
            ),
        )


@pytest.mark.parametrize("wrong_identity", [False, True])
def test_failure_readback_updates_parent_without_rewriting_task(
    tmp_path: Path,
    wrong_identity: bool,
) -> None:
    project = _copy_fixture(tmp_path, "java")
    platform = tmp_path / "platform"
    backend = FailedRuntimeBackend(platform)
    backend.wrong_identity = wrong_identity
    service = UnifiedProjectEntryService(
        backend=backend,
        catalog=ProjectDeliveryCheckpointCatalog(platform / "projects"),
    )
    started = service.start(
        StartProjectDelivery(
            project_root=str(project.resolve()),
            requirement="Add greeting",
            submitted_at=NOW,
        )
    )
    command = ApproveProductSpec(
        delivery_id=started.checkpoint.delivery_id,
        expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
        approval_reference="test-approved",
        submitted_at=NOW + timedelta(minutes=1),
    )
    if wrong_identity:
        with pytest.raises(DeliveryCommandRejected, match="failure snapshot"):
            service.approve(command)
        return
    result = service.approve(command)
    cp = result.checkpoint
    assert cp.stage is DeliveryStage.BLOCKED
    assert cp.task_status is TaskStatus.FAILED and cp.task_revision == 4
    assert cp.candidate_revision == "c" * 40
    assert cp.stage_attempts.delivering == 1
    assert cp.checkpointed_at == NOW + timedelta(hours=1)
    assert service.status(cp.delivery_id).checkpoint == cp


def test_production_backend_reads_actual_runtime_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_software_engineer.project_manager import production_backend
    from ai_software_engineer.store import SqliteTaskRepository
    from tests.e2e.test_delivery_checkpoint import _checkpoint, _full_fields
    from tests.orchestration.test_output_parent_contract import AllInputsAsParentsAdapter
    from tests.orchestration.test_retry import _runner

    task, repository, runner = _runner(tmp_path, AllInputsAsParentsAdapter())
    result = runner.run_task(task.id)
    events = repository.list_events(task.id)
    repository.close()

    class Backend(production_backend.ProductionProjectDeliveryBackend):
        def __init__(self) -> None:
            self._dsn = str(tmp_path / "state.sqlite3")

        def _run_delivery(self, checkpoint: ProjectDeliveryCheckpoint) -> Never:
            raise RuntimeError("private provider details")

    monkeypatch.setattr(production_backend, "MySqlTaskRepository", SqliteTaskRepository)
    cp = _checkpoint(
        Path(task.repository),
        **{**_full_fields(), "task_id": task.id},
        stage=DeliveryStage.DELIVERING,
    )
    with pytest.raises(DeliveryBackendFailure) as caught:
        Backend().run_delivery(cp)
    snapshot = caught.value.snapshot
    assert snapshot is not None
    assert snapshot.task == result.task
    assert snapshot.task_revision == len(events)
    assert snapshot.candidate_revision == next(
        event.source_revision for event in events if event.reason == "candidate_ready"
    )
    assert "private provider details" not in caught.value.safe_summary
    with SqliteTaskRepository(tmp_path / "state.sqlite3") as reopened:
        assert reopened.list_events(task.id) == events
