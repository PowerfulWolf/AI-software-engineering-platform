"""Legacy knowledge reentry appends under its proof lock before ordinary dispatch."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from ai_software_engineer.domain.delivery_resolution import RejectedKnowledgePreparationEvidence
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.manager.delivery import (
    DeliveryCommandRejected,
    ProjectDeliveryResult,
    ResumeProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryStage,
    ProjectDeliveryCheckpoint,
)
from tests.recovery.test_delivery_continuation import _service
from tests.recovery.test_execution_records import continuation_allocation


def _proof(checkpoint: ProjectDeliveryCheckpoint) -> RejectedKnowledgePreparationEvidence:
    assert checkpoint.task_id is not None and checkpoint.task_revision is not None
    return RejectedKnowledgePreparationEvidence(
        scope=EngineeringScope(
            team_id="team_test",
            project_id="project_test",
            repository_id=checkpoint.repository_id,
            repository_root=checkpoint.repository_root,
        ),
        requirement_id=checkpoint.delivery_id,
        task_id=checkpoint.task_id,
        work_item_id="work_rejected_knowledge",
        role=AgentRole.CODER,
        original_lease_id="lease_original",
        original_claim_sha256="1" * 64,
        original_attempt=7,
        original_dispatch_sequence=0,
        checkpoint_sequence=checkpoint.task_revision,
        previous_run_id="run_knowledge_original",
        previous_context_manifest_id="ctx_" + "2" * 64,
        source_revision="3" * 40,
        observation_sha256="4" * 64,
        context_sha256="5" * 64,
        workspace_inventory_sha256="6" * 64,
        workspace_capture_sha256="7" * 64,
        current_lease_id="lease_original",
        current_claim_sha256="1" * 64,
        current_dispatch_sequence=0,
    )


@pytest.mark.parametrize("mode", ["exact", "none", "wrong_task", "wrong_claim", "changed_cursor"])
def test_legacy_reentry_holds_proof_scope_through_append_and_releases_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    dispatch = continuation_allocation(tmp_path)
    service, store = _service(tmp_path, dispatch, retain_candidate=False)
    before = store.current(dispatch.source_delivery_id)
    blocked = ProjectDeliveryCheckpoint.create(
        **{
            **before.to_wire(),
            "sequence": before.sequence + 1,
            "previous_checkpoint_sha256": before.checkpoint_sha256,
            "task_status": TaskStatus.IMPLEMENTING,
            "failure_code": DeliveryFailureCode.INVARIANT_VIOLATION,
            "failed_stage": DeliveryStage.DELIVERING,
        }
    )
    store.put(blocked)
    # Compare all immutable checkpoint records, independent of store filename conventions.
    original = {path: path.read_bytes() for path in store._root.rglob("*.json")}
    assert original
    proof = _proof(blocked)
    if mode == "wrong_task":
        proof = proof.model_copy(update={"task_id": "task_foreign"})
    if mode == "wrong_claim":
        proof = proof.model_copy(update={"current_claim_sha256": "9" * 64})
    held = False
    resumed: list[ProjectDeliveryCheckpoint] = []

    @contextmanager
    def proof_scope(
        current: ProjectDeliveryCheckpoint,
    ) -> Iterator[RejectedKnowledgePreparationEvidence | None]:
        nonlocal held
        assert current == blocked
        held = True
        try:
            if mode == "changed_cursor":
                store.put(
                    ProjectDeliveryCheckpoint.create(
                        **{
                            **blocked.to_wire(),
                            "sequence": blocked.sequence + 1,
                            "previous_checkpoint_sha256": blocked.checkpoint_sha256,
                        }
                    )
                )
            yield None if mode == "none" else proof
            if mode == "exact":
                assert store.current(blocked.delivery_id).stage is DeliveryStage.DELIVERING
        finally:
            held = False

    def resume(command: ResumeProjectDelivery) -> ProjectDeliveryResult:
        assert not held
        current = store.current(command.delivery_id)
        resumed.append(current)
        return ProjectDeliveryResult(checkpoint=current)

    monkeypatch.setattr(service, "resume", resume)
    command = ResumeProjectDelivery(delivery_id=blocked.delivery_id)
    if mode in {"wrong_task", "wrong_claim", "changed_cursor"}:
        with pytest.raises(DeliveryCommandRejected):
            service.retry_rejected_knowledge_preparation(command, proof_scope=proof_scope)
        assert not resumed
    else:
        result = service.retry_rejected_knowledge_preparation(command, proof_scope=proof_scope)
        if mode == "none":
            assert result.checkpoint == blocked and not resumed
        else:
            current = result.checkpoint
            assert resumed == [current]
            assert current.stage is DeliveryStage.DELIVERING
            assert current.task_id == blocked.task_id
            assert current.task_revision == blocked.task_revision
            assert current.task_status is TaskStatus.IMPLEMENTING
            assert current.stage_attempts == blocked.stage_attempts
            assert current.previous_checkpoint_sha256 == blocked.checkpoint_sha256
    assert not held
    assert all(path.read_bytes() == data for path, data in original.items())
