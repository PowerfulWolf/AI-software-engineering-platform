"""Focused public-controller gates for released rejected-candidate baselines."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from ai_software_engineer.domain import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.git.baseline import GitExecutionBaselineAdapter
from ai_software_engineer.manager.baseline_models import (
    BaselineContinueAuthorization,
    BaselineOperatorAuthorization,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
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
from ai_software_engineer.manager.execution_baseline import ExecutionBaselineService
from ai_software_engineer.manager.production_backend import ProductionProjectDeliveryBackend
from ai_software_engineer.manager.rejected_candidate_reentry import RejectedCandidateReentryProof
from ai_software_engineer.recovery.resume import DeliveryResumeController
from ai_software_engineer.work_queue.baseline import BaselineQueueRelease, _paused_item
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from tests.manager.test_execution_baseline import Collector
from tests.manager.test_rejected_candidate_baseline_production import (
    RejectedCandidateProductionFixture,
)
from tests.manager.test_rejected_candidate_baseline_production import (
    rejected_candidate_production as rejected_candidate_production,
)
from tests.recovery.test_delivery_continuation import _service
from tests.recovery.test_execution_records import continuation_allocation


def _blocked() -> SimpleNamespace:
    return SimpleNamespace(
        stage=DeliveryStage.BLOCKED,
        task_id="task_rejected_candidate",
        task_status=TaskStatus.IMPLEMENTING,
        task_revision=2,
        candidate_revision=None,
        failure_code=DeliveryFailureCode.INVARIANT_VIOLATION,
        failed_stage=DeliveryStage.DELIVERING,
        repository_root="/repository",
        repository_id="repository_fixture",
        delivery_id="delivery_rejected_candidate",
        dispatch_commit_id="dispatch_rejected_candidate",
    )


@pytest.mark.parametrize("diagnostic", ["候选与原历史已保留并暂停。请明确继续。", None])
def test_rejected_candidate_reentry_precedes_legacy_stopped_scope(
    monkeypatch: pytest.MonkeyPatch, diagnostic: str | None
) -> None:
    current = _blocked()
    entry = Mock()
    entry.status.return_value = SimpleNamespace(checkpoint=current)
    result = SimpleNamespace(
        checkpoint=current
        if diagnostic is not None
        else SimpleNamespace(stage=DeliveryStage.DELIVERING, next_action="run delivery"),
        diagnostic=diagnostic,
    )
    entry.retry_rejected_candidate_baseline.return_value = result
    entry.retry_stopped_execution.side_effect = AssertionError(
        "rejected candidate recovery must not enter stopped-unknown scope"
    )
    controller = DeliveryResumeController(
        config=Mock(),
        environment={},
        backend=Mock(),
        entry=entry,
        recovery=Mock(),
        verification=Mock(),
    )
    expected = object()
    monkeypatch.setattr(controller, "_result", Mock(return_value=expected))

    assert controller.resume(ResumeProjectDelivery(delivery_id=current.delivery_id)) is expected
    entry.retry_rejected_candidate_baseline.assert_called_once()
    entry.retry_stopped_execution.assert_not_called()


@pytest.mark.parametrize("has_prior_binding", [False, True])
def test_nonrescue_baseline_preserves_legacy_route_with_active_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    has_prior_binding: bool,
) -> None:
    """Other recovery routes may own ACTIVE claims; rescue must not acquire idle."""
    current = cast(ProjectDeliveryCheckpoint, _blocked())
    assert current.task_id is not None
    state = tmp_path / "state"
    (state / "execution-baselines" / current.task_id).mkdir(parents=True)
    facts = SimpleNamespace(workspace=Mock())
    facts.workspace.directory.return_value = state
    queue = Mock(spec=MySqlRoleQueue)
    queue.idle_task_scope.side_effect = ValueError("ACTIVE claims must remain protected")
    backend_mock = Mock(spec=ProductionProjectDeliveryBackend)
    backend_mock._sealed_facts_for_checkpoint.return_value = facts
    backend_mock._role_queue = queue
    store = Mock(spec=FileExecutionBaselineStore)
    store.bindings_for_task.return_value = (
        (SimpleNamespace(purpose=BaselinePurpose.SOURCE_REBIND),) if has_prior_binding else ()
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.baseline_store.FileExecutionBaselineStore",
        Mock(return_value=store),
    )

    with ProductionProjectDeliveryBackend.rejected_candidate_reentry_scope(
        cast(ProductionProjectDeliveryBackend, backend_mock), current
    ) as proof:
        assert proof is None

    store.bindings_for_task.assert_called_once_with(current.task_id)
    queue.idle_task_scope.assert_not_called()


@pytest.mark.parametrize(
    "mode",
    [
        "released",
        "paused",
        "no_rescue",
        "wrong_task",
        "wrong_revision",
        "wrong_dispatch",
        "wrong_claim",
        "changed_cursor",
        "mixed_command",
        "terminal_task",
    ],
)
def test_candidate_reentry_appends_only_under_exact_proof_and_releases_before_dispatch(
    tmp_path: Path,
    rejected_candidate_production: RejectedCandidateProductionFixture,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    """Unit proof scope only; public E2E separately checks real SQL and locks."""
    f = rejected_candidate_production
    facts = f.facts()
    baseline = ExecutionBaselineService(
        store=FileExecutionBaselineStore(tmp_path / "unit-reentry-baselines"),
        git=GitExecutionBaselineAdapter(f.native.git),
        facts=Collector(facts, f.native.worktree),
    )
    plan = baseline.propose(None, purpose=BaselinePurpose.REJECTED_CANDIDATE_RESCUE)
    binding = baseline.execute(
        plan.plan_sha256,
        authority=BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="unit exact candidate pause",
            submitted_at=datetime.now(UTC),
            continuation_mode=BaselineContinuationMode.PAUSE,
        ),
    )
    task = f.task.model_copy(update={"attempts": f.task.attempts + 1})
    ready = f.queue.bound.work_item.model_copy(
        update={
            "id": "work_candidate_resume_next",
            "parent_work_item_id": f.queue.item.id,
            "status": WorkItemStatus.READY,
            "attempt": task.attempts,
            "dispatch_sequence": 1,
            "wait_disposition": None,
            "wait_reason": None,
        }
    )
    paused = _paused_item(ready, task, binding)
    assert paused.wait_disposition is not None
    continuation = BaselineContinueAuthorization.create(
        scope=binding.scope,
        task_id=task.id,
        task_intent_sha256=task_intent_sha256(task),
        task_revision=facts.task_revision,
        work_item_id=ready.id,
        execution_baseline_sha256=binding.binding_sha256,
        expected_source_revision=binding.execution_source_revision,
        checkpoint_sequence=facts.task_revision,
        expected_disposition_sha256=paused.wait_disposition.disposition_sha256,
        inventory_sha256=binding.after_inventory_sha256,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="unit exact candidate resume",
        submitted_at=datetime.now(UTC),
    )
    release = BaselineQueueRelease(
        task_id=task.id, binding=binding, authorization=continuation, ready_work_item=ready
    )
    template_root = tmp_path / "reentry-template"
    template_root.mkdir()
    dispatch = continuation_allocation(template_root)
    entry, store = _service(template_root, dispatch, retain_candidate=False)
    template = store.current(dispatch.source_delivery_id)
    rejected = plan.facts.rejected_candidate_output
    assert rejected is not None
    blocked = ProjectDeliveryCheckpoint.create(
        **{
            **template.to_wire(),
            "delivery_id": rejected.capture_start.scope.requirement_id,
            "repository_id": binding.scope.repository_id,
            "repository_root": binding.scope.repository_root,
            "task_id": task.id,
            "task_status": TaskStatus.IMPLEMENTING,
            "task_revision": facts.task_revision,
            "dispatch_commit_sha256": rejected.capture_start.scope.dispatch_sha256,
            "failure_code": DeliveryFailureCode.INVARIANT_VIOLATION,
            "failure_summary": "Unsupported implementation version rejected by ArtifactStore.",
        }
    )
    store.put(blocked)
    proof = RejectedCandidateReentryProof(
        checkpoint_sha256=blocked.checkpoint_sha256,
        plan=plan,
        binding=binding,
        work_item=paused if mode == "paused" else ready,
        release=None if mode == "paused" else release,
        task=task,
        task_revision=facts.task_revision,
    )
    proof.require_for(blocked)
    if mode == "wrong_task":
        proof = proof.model_copy(update={"task": task.model_copy(update={"id": "task_foreign"})})
    elif mode == "wrong_revision":
        proof = proof.model_copy(update={"task_revision": facts.task_revision + 1})
    elif mode == "wrong_dispatch":
        blocked = ProjectDeliveryCheckpoint.create(
            **{
                **blocked.to_wire(),
                "sequence": blocked.sequence + 1,
                "previous_checkpoint_sha256": blocked.checkpoint_sha256,
                "dispatch_commit_sha256": "f" * 64,
            }
        )
        store.put(blocked)
        proof = proof.model_copy(update={"checkpoint_sha256": blocked.checkpoint_sha256})
    elif mode == "wrong_claim":
        proof = proof.model_copy(
            update={"work_item": ready.model_copy(update={"dispatch_sequence": 99})}
        )
    elif mode == "terminal_task":
        blocked = ProjectDeliveryCheckpoint.create(
            **{
                **blocked.to_wire(),
                "sequence": blocked.sequence + 1,
                "previous_checkpoint_sha256": blocked.checkpoint_sha256,
                "task_status": TaskStatus.BLOCKED,
            }
        )
        store.put(blocked)
    original = {path: path.read_bytes() for path in store._root.rglob("*.json")}
    held = False
    resumed: list[ProjectDeliveryCheckpoint] = []

    @contextmanager
    def proof_scope(
        current: ProjectDeliveryCheckpoint,
    ) -> Iterator[RejectedCandidateReentryProof | None]:
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
            yield None if mode == "no_rescue" else proof
            if mode == "released":
                assert store.current(blocked.delivery_id).stage is DeliveryStage.DELIVERING
        finally:
            held = False

    def resume(command: ResumeProjectDelivery) -> ProjectDeliveryResult:
        assert not held
        current = store.current(command.delivery_id)
        resumed.append(current)
        return ProjectDeliveryResult(checkpoint=current)

    monkeypatch.setattr(entry, "resume", resume)
    command = ResumeProjectDelivery(
        delivery_id=blocked.delivery_id,
        approved_plan_sha256="e" * 64 if mode == "mixed_command" else None,
        approval_reference="mixed unrelated approval" if mode == "mixed_command" else None,
    )
    if mode in {
        "wrong_task",
        "wrong_revision",
        "wrong_dispatch",
        "wrong_claim",
        "changed_cursor",
        "mixed_command",
    }:
        with pytest.raises(DeliveryCommandRejected):
            entry.retry_rejected_candidate_baseline(command, proof_scope=proof_scope)
        assert not resumed
    else:
        result = entry.retry_rejected_candidate_baseline(command, proof_scope=proof_scope)
        if mode == "released":
            assert len(resumed) == 1
            assert result.checkpoint.stage is DeliveryStage.DELIVERING
            assert result.checkpoint.task_id == task.id
            assert result.checkpoint.stage_attempts == blocked.stage_attempts
            assert result.checkpoint.previous_checkpoint_sha256 == blocked.checkpoint_sha256
        else:
            assert result.checkpoint == blocked and not resumed
            assert bool(result.diagnostic) is (mode == "paused")
    assert not held
    assert all(path.read_bytes() == data for path, data in original.items())
