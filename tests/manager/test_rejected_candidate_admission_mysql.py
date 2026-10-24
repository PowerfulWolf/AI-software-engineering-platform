"""Retained reporting needs an actually consumed binding and fresh MySQL claim."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.artifact import ImplementationReportArtifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import BaselineInputMode
from ai_software_engineer.manager.baseline_admission import BaselineInitialWorkspaceAdmission
from ai_software_engineer.manager.baseline_models import BaselineContinueAuthorization
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.work_queue.baseline import consume_baseline, release_baseline_pause
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard, WorkerLease
from tests.manager.test_rejected_candidate_baseline_production import (
    rejected_candidate_production as rejected_candidate_production,
)
from tests.work_queue.test_mysql_queue import OWNER_TOKEN, dispatcher
from tests.work_queue.test_rejected_candidate_baseline_mysql import RejectedQueueFixture
from tests.work_queue.test_rejected_candidate_baseline_mysql import rejected_queue as rejected_queue

pytestmark = pytest.mark.mysql


def test_consumed_candidate_report_reopens_real_current_claim_and_full_workspace(
    rejected_queue: RejectedQueueFixture,
    tmp_path: Path,
) -> None:
    f = rejected_queue
    native = f.production.native
    old_task = f.repository.get(f.binding.task_id)
    old_outcome = f.production.outcome.to_wire()
    f.release_crashed_owner()
    f.queue._clock = lambda: datetime.now(UTC)
    waiting = consume_baseline(f.queue, f.plan, f.binding)
    assert waiting.wait_disposition is not None
    authorization = BaselineContinueAuthorization.create(
        scope=f.binding.scope,
        task_id=old_task.id,
        task_intent_sha256=task_intent_sha256(old_task),
        task_revision=f.repository.current_revision(old_task.id),
        work_item_id=waiting.id,
        execution_baseline_sha256=f.binding.binding_sha256,
        expected_source_revision=f.binding.execution_source_revision,
        checkpoint_sequence=waiting.checkpoint_sequence,
        expected_disposition_sha256=waiting.wait_disposition.disposition_sha256,
        inventory_sha256=f.binding.after_inventory_sha256,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="isolated exact second decision to continue retained candidate",
        submitted_at=datetime.now(UTC),
    )
    assert release_baseline_pause(f.queue, f.binding, authorization)
    assert not release_baseline_pause(f.queue, f.binding, authorization)
    tick = dispatcher(f.queue, "worker_retained_candidate_report").tick(now=datetime.now(UTC))
    assert tick.claim is not None
    claim = tick.claim
    assert claim.work_item.id == waiting.id and claim.work_item.attempt == 2
    assert claim.work_item.role is AgentRole.CODER
    lease = WorkerLease(f.queue, claim, OWNER_TOKEN)
    guard = WorkerExecutionGuard()
    guard.lease = lease
    lease.start()
    try:
        store = FileExecutionBaselineStore(tmp_path / "mysql-queue-baseline-records")
        admission = BaselineInitialWorkspaceAdmission(
            inputs=StoredCoderExecutionInputResolver(store),
            task_reader=lambda: f.repository.get(old_task.id),
            artifacts=native.artifacts,
            git=native.git,
            guard=guard,
        )
        request = native.request.model_copy(
            update={
                "attempt": 2,
                "run_id": "run_retained_candidate_fresh",
                "source_revision": f.binding.execution_source_revision,
                "execution_base_ref": f.binding.execution_base_ref,
                "execution_baseline_sha256": f.binding.binding_sha256,
                "context_manifest_id": "ctx_" + "e" * 64,
                "continuation_checkpoint_id": None,
                "continuation_changed_paths": (),
            }
        )
        report = f.production.outcome.result.artifact
        assert isinstance(report, ImplementationReportArtifact)
        report = report.model_copy(
            update={
                "schema_version": "v0.1",
                "source_revision": request.source_revision,
                "context_manifest_id": request.context_manifest_id,
                "producer": report.producer.model_copy(
                    update={
                        "agent_id": claim.assignment.agent_id,
                        "run_id": request.run_id,
                    }
                ),
            }
        )
        admission.authorize(request, native.worktree.path)
        assert (
            admission.retained_candidate_report_base(
                request,
                native.worktree.path,
                report,
            )
            == old_task.base_ref
        )
        with pytest.raises(ValueError):
            admission.retained_candidate_report_base(
                request.model_copy(update={"execution_baseline_sha256": "f" * 64}),
                native.worktree.path,
                report,
            )
        changed = native.worktree.path / "src/app.py"
        original = changed.read_bytes()
        changed.write_text("VALUE = 999\n")
        with pytest.raises(ValueError):
            admission.retained_candidate_report_base(request, native.worktree.path, report)
        changed.write_bytes(original)
        assert (
            admission.retained_candidate_report_base(
                request,
                native.worktree.path,
                report,
            )
            == old_task.base_ref
        )
        assert f.binding.input_mode is BaselineInputMode.PRESERVE_DRAFT
        assert f.repository.get(old_task.id).base_ref == old_task.base_ref
        assert f.production.outcome.to_wire() == old_outcome
    finally:
        lease.stop()
