"""Current engineering isolation never converts unknown knowledge history to no-start."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest

from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.context import ContextCorruption
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.enums import AgentRole, TeamRole
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationFailure,
    KnowledgeInvocationIntent,
    KnowledgeInvocationOutcome,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeRunBinding,
    KnowledgeSnapshot,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionReservation,
    BaselineOperatorAuthorization,
)
from ai_software_engineer.manager.capacity_input_reader import PriorInvocationFence
from ai_software_engineer.manager.knowledge_invocation_proof import (
    read_capacity_claim_snapshot,
    read_replay_guarded_claims,
)
from ai_software_engineer.manager.knowledge_isolation import (
    KnowledgePreparationIsolationProof,
    read_unknown_knowledge_preparation,
    require_current_isolation_boundary,
)
from ai_software_engineer.manager.legacy_containment import LocalBootObservation
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionSurvey,
    LegacyRescuePrerequisiteError,
)
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep
from tests.manager.test_baseline_knowledge_claim_proof import Facts, knowledge_failure
from tests.manager.test_capacity_legacy_claim_snapshot import _marker
from tests.manager.test_execution_baseline import Setup, setup
from tests.manager.test_execution_baseline_invocations import _claim
from tests.manager.test_replay_guarded_claim_observation import replay_facts
from tests.work_queue.test_mysql_queue import queued_item


def test_knowledge_isolation_consumes_one_ordinary_work_attempt() -> None:
    assert BaselinePurpose("knowledge_preparation_isolation").value == (
        "knowledge_preparation_isolation"
    )
    fields = {
        "current_attempt": 5,
        "next_execution_attempt": 6,
        "retry_cause": "knowledge_isolation",
        "knowledge_isolation_sha256": "1" * 64,
    }
    reservation = BaselineExecutionReservation.model_validate(fields)
    assert reservation.original_run_id is None
    assert reservation.current_invocation_start_sha256 is None
    assert reservation.current_invocation_outcome_sha256 is None
    assert reservation.retry_failure is None
    assert not reservation.reservation_already_applied
    for changed in (
        {"next_execution_attempt": 5},
        {"knowledge_isolation_sha256": None},
        {"original_run_id": "run_fabricated"},
        {"current_invocation_start_sha256": "2" * 64},
        {"current_invocation_outcome_sha256": "3" * 64},
        {"reservation_already_applied": True},
        {"containment_sha256": "4" * 64},
    ):
        with pytest.raises(ValueError):
            BaselineExecutionReservation.model_validate({**fields, **changed})


def test_isolation_proof_cannot_be_smuggled_into_uninvoked_reservation() -> None:
    with pytest.raises(ValueError):
        BaselineExecutionReservation.model_validate(
            {
                "current_attempt": 5,
                "next_execution_attempt": 5,
                "retry_cause": "uninvoked",
                "knowledge_isolation_sha256": "1" * 64,
            }
        )


def isolation_fixture(tmp_path: Path) -> tuple[Setup, KnowledgePreparationIsolationProof]:
    f = setup(tmp_path)
    facts = f.collector.facts
    facts = facts.model_copy(
        update={"scope": facts.scope.model_copy(update={"repository_id": "repository_baseline"})}
    )
    item = queued_item(checkpoint_sequence=facts.checkpoint_sequence).model_copy(
        update={
            "id": facts.work_item_id,
            "task_id": facts.task.id,
            "repository_id": facts.scope.repository_id,
            "repository_scopes": (facts.task.repository,),
        }
    )
    # Bind the real baseline checkpoint rather than an arbitrary factory sequence.
    item = item.model_copy(update={"checkpoint_sequence": facts.task_revision})
    claim = _claim(item, "lease_knowledge_isolation")
    step = QueuedRoleStep(
        work_item=item,
        boundary=RoleRunBoundary(
            facts.task.id, AgentRole.CODER, 1, facts.task_revision, f.worktree.head_revision
        ),
        allocation_sha256="b" * 64,
    )
    now = datetime.now(UTC)
    intent = KnowledgeInvocationIntent.create(
        binding=KnowledgeRunBinding(
            run_id="run_knowledge_isolation",
            task_id=facts.task.id,
            role=TeamRole.CODER,
            team_id=facts.scope.team_id,
            project_id=facts.scope.project_id,
            requirement_id="delivery_knowledge_isolation",
            repository_ids=(facts.scope.repository_id,),
            source_revision=f.worktree.head_revision,
            context_manifest_id="ctx_" + "c" * 64,
            snapshot_sha256="a" * 64,
        ),
        phase="intent",
        request_sha256="d" * 64,
        timeout_seconds=2,
        claim=claim,
        created_at=now,
    )
    outcome = KnowledgeInvocationOutcome.create(
        intent=intent,
        state="FAILED",
        completed_at=now,
        failure=KnowledgeInvocationFailure(
            code=AgentErrorCode.SERVICE_PAUSED, safe_message="旧知识调用暂停", transient=False
        ),
    )
    boot = LocalBootObservation(
        machine_sha256="a" * 64, boot_session_sha256="b" * 64, booted_at=now - timedelta(days=1)
    )

    def surveys(path: Path) -> tuple[LegacyLocalExecutionSurvey, LegacyLocalExecutionSurvey]:
        def one(n: int) -> LegacyLocalExecutionSurvey:
            return LegacyLocalExecutionSurvey.create(
                worktree_path=str(path),
                machine_sha256=boot.machine_sha256,
                boot_session_sha256=boot.boot_session_sha256,
                account_sha256="c" * 64,
                observed_at=now + timedelta(microseconds=n),
                scanner_version="fixture-v1",
                blockers=(),
            )

        return one(1), one(2)

    proof = KnowledgePreparationIsolationProof.create(
        scope=facts.scope,
        requirement_id="delivery_native_isolation",
        knowledge_requirement_id=intent.binding.requirement_id,
        dispatch_sha256=step.allocation_sha256,
        task_id=facts.task.id,
        task_intent_sha256=task_intent_sha256(facts.task),
        task_revision=facts.task_revision,
        work_item_id=item.id,
        checkpoint_sequence=item.checkpoint_sequence,
        original_claim=claim,
        original_step=step,
        outcome=outcome,
        context_sha256="d" * 64,
        boot=boot,
        repository_surveys=surveys(f.repository),
        worktree_surveys=surveys(f.worktree.path),
    )
    updated = facts.model_copy(
        update={
            "checkpoint_sequence": facts.task_revision,
            "target_native_rules_sha256": facts.source_native_rules_sha256,
            "implementation_artifact_id": None,
            "progress_artifact_id": "art_progress_kept",
            "source_artifact_ids": ("art_plan_001", "art_progress_kept"),
            "knowledge_isolation": proof,
            "continuation": BaselineExecutionReservation(
                current_attempt=1,
                next_execution_attempt=2,
                retry_cause="knowledge_isolation",
                knowledge_isolation_sha256=proof.proof_sha256,
            ),
        }
    )
    f.collector.facts = updated.model_copy(
        update={"facts_sha256": digest(updated.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    return f, proof


def test_real_git_isolation_requires_current_engineering_decision_and_preserves_all_progress(
    tmp_path: Path,
) -> None:
    f, proof = isolation_fixture(tmp_path)
    before = capture_mutation_inventory(f.worktree.path)
    task_before = f.collector.facts.task.to_wire()
    plan = f.service.propose(None, purpose=BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION)
    assert plan.facts.knowledge_isolation == proof
    assert "VALUE = 2" in plan.complete_capture.patch and "EXTRA = 3" in plan.complete_capture.patch
    cases: tuple[tuple[Literal[True] | None, BaselineContinuationMode], ...] = (
        (None, BaselineContinuationMode.PAUSE),
        (True, BaselineContinuationMode.RESUME),
    )
    for confirmation, mode in cases:
        with pytest.raises(ValueError):
            BaselineOperatorAuthorization.for_plan(
                plan,
                principal=LocalOperatorPrincipal.trusted_local(),
                reference="current trusted isolation decision",
                submitted_at=datetime.now(UTC),
                continuation_mode=mode,
                confirm_current_knowledge_execution_isolated=confirmation,
            )
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="current trusted isolation decision",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_current_knowledge_execution_isolated=True,
    )
    binding = f.service.execute(plan.plan_sha256, authority=authority)
    assert binding.knowledge_isolation_sha256 == proof.proof_sha256
    assert binding.execution_source_revision == f.worktree.head_revision
    assert binding.execution_base_ref == f.collector.facts.task.base_ref
    assert binding.superseded_progress_artifact_id is None
    assert binding.superseded_implementation_artifact_id is None
    assert binding.source_artifact_ids == ("art_plan_001", "art_progress_kept")
    assert binding.continuation_mode is BaselineContinuationMode.PAUSE
    assert capture_mutation_inventory(f.worktree.path) == before
    assert f.collector.facts.task.to_wire() == task_before
    assert f.service.execute(plan.plan_sha256, authority=authority) == binding
    assert proof.historical_execution_status == "UNKNOWN"
    fields = {
        "task_id": plan.facts.task.id,
        "work_item_id": plan.facts.work_item_id,
        "next_work_item_id": "work_isolated_successor",
        "prior_step_sha256": "f" * 64,
        "plan": plan,
        "binding": binding,
    }
    receipt = BaselineQueueConsumption.model_validate(fields)
    assert receipt.binding.knowledge_isolation_sha256 == proof.proof_sha256
    for change in (
        {"next_work_item_id": plan.facts.work_item_id},
        {"binding": binding.model_copy(update={"knowledge_isolation_sha256": None})},
        {"binding": binding.model_copy(update={"knowledge_isolation_sha256": "e" * 64})},
        {
            "binding": binding.model_copy(
                update={"superseded_progress_artifact_id": "art_progress_kept"}
            )
        },
    ):
        with pytest.raises(ValueError):
            BaselineQueueConsumption.model_validate({**fields, **change})


def test_current_survey_refuses_live_or_changed_boundary(tmp_path: Path) -> None:
    f, proof = isolation_fixture(tmp_path)

    class Observer:
        active = False

        def observe(
            self, *, worktree_root: Path, boot: LocalBootObservation
        ) -> LegacyLocalExecutionSurvey:
            return LegacyLocalExecutionSurvey.create(
                worktree_path=str(worktree_root),
                machine_sha256=boot.machine_sha256,
                boot_session_sha256=boot.boot_session_sha256,
                account_sha256="c" * 64,
                observed_at=datetime.now(UTC),
                scanner_version="fixture-v1",
                blockers=("PROCESS_SCAN_INCOMPLETE",) if self.active else (),
            )

    observer = Observer()
    require_current_isolation_boundary(
        proof,
        observer=observer,
        boot=proof.boot,
        repository_root=f.repository,
        worktree_root=f.worktree.path,
    )
    observer.active = True
    with pytest.raises(LegacyRescuePrerequisiteError):
        require_current_isolation_boundary(
            proof,
            observer=observer,
            boot=proof.boot,
            repository_root=f.repository,
            worktree_root=f.worktree.path,
        )
    with pytest.raises(ValueError):
        require_current_isolation_boundary(
            proof,
            observer=observer,
            boot=proof.boot.model_copy(update={"boot_session_sha256": "f" * 64}),
            repository_root=f.repository,
            worktree_root=f.worktree.path,
        )


def legacy_reader_fixture(tmp_path: Path, *, task_scope: bool = False) -> Facts:
    """Replace only test-owned HTTP fixture bytes with a genuine old unknown pause."""
    f = knowledge_failure(tmp_path)
    for path in f.records.root.glob("*.json"):
        path.unlink()
    requirement_id = f.task.id if task_scope else "delivery_multi_legacy_isolation"
    snapshot = KnowledgeSnapshot.create(
        team_id=f.collector.scope.team_id,
        project_id=f.collector.scope.project_id,
        requirement_id=requirement_id,
        repository_ids=(f.item.repository_id,),
    )
    root = KnowledgeRecordStore(tmp_path / "knowledge/runs")
    root.put("snapshots", snapshot.snapshot_sha256, snapshot)
    binding = f.intent.binding.model_copy(
        update={
            "requirement_id": requirement_id,
            "snapshot_sha256": snapshot.snapshot_sha256,
            "run_id": "run_knowledge_"
            + digest((f.intent.binding.context_manifest_id, snapshot.snapshot_sha256))[:32],
        }
    )
    intent = KnowledgeInvocationIntent.create(
        binding=binding,
        phase=f.intent.phase,
        request_sha256=f.intent.request_sha256,
        timeout_seconds=f.intent.timeout_seconds,
        claim=f.claim,
        created_at=f.intent.created_at,
    )
    outcome = KnowledgeInvocationOutcome.create(
        intent=intent,
        state="FAILED",
        failure=KnowledgeInvocationFailure(
            code=AgentErrorCode.SERVICE_PAUSED, safe_message="legacy pause", transient=False
        ),
        completed_at=f.outcome.completed_at,
    )
    from ai_software_engineer.knowledge.invocation import invocation_lane_sha256

    records = KnowledgeRecordStore(root.root / "invocations" / invocation_lane_sha256(binding))
    records.put("knowledge-invocation-intents", binding.run_id + ":" + intent.phase, intent)
    records.put("knowledge-invocation-outcomes", binding.run_id + ":" + intent.phase, outcome)
    f.collector.requirement_id = "delivery_multi_legacy_isolation"
    return replace(f, records=records, intent=intent, outcome=outcome)


def read_legacy(f: Facts) -> KnowledgeInvocationOutcome:
    outcome, claim, step, context = read_unknown_knowledge_preparation(
        state=f.collector.state,
        task=f.task,
        item=f.item,
        scope=f.collector.scope,
        requirement_id=f.collector.requirement_id,
        queue=f.collector.queue,
        require_step=f.collector._require_step,
        no_start_reader=f.collector._capacity_input_reader(),
    )
    assert claim == f.claim and step == f.collector.queue.step_for_claim(f.claim)
    assert len(context) == 64
    return outcome


def test_legacy_reader_verifies_real_joint_scope_without_rewriting_unknown_history(
    tmp_path: Path,
) -> None:
    f = legacy_reader_fixture(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    assert read_legacy(f) == f.outcome
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}


def test_legacy_joint_coder_cannot_borrow_task_scope(tmp_path: Path) -> None:
    f = legacy_reader_fixture(tmp_path, task_scope=True)
    with pytest.raises(KnowledgeError, match="LEGACY_KNOWLEDGE_SCOPE_CHANGED"):
        read_legacy(f)


@pytest.mark.parametrize("corrupt", ["snapshot", "context", "original_claim"])
def test_legacy_reader_refuses_changed_original_facts(
    tmp_path: Path, corrupt: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = legacy_reader_fixture(tmp_path)
    if corrupt == "original_claim":
        monkeypatch.setattr(
            f.collector.queue,
            "original_claim",
            lambda identity: _claim(f.item, "lease_foreign"),
        )
    elif corrupt == "context":
        (tmp_path / "contexts" / f"{f.intent.binding.context_manifest_id}.json").write_text("{}")
    else:
        root = KnowledgeRecordStore(tmp_path / "knowledge/runs")
        (root.root / root._name("snapshots", f.intent.binding.snapshot_sha256)).write_text("{}")
    with pytest.raises((ValueError, KnowledgeError, ContextCorruption)):
        read_legacy(f)


def append_unknown_preparation(f: Facts, lease_id: str) -> None:
    claim = _claim(f.item.model_copy(update={"id": "work_" + lease_id}), lease_id)
    intent = KnowledgeInvocationIntent.create(
        binding=f.intent.binding.model_copy(update={"run_id": "run_" + lease_id}),
        phase="intent",
        request_sha256="e" * 64,
        timeout_seconds=2,
        claim=claim,
        created_at=f.intent.created_at,
    )
    outcome = KnowledgeInvocationOutcome.create(
        intent=intent,
        state="FAILED",
        failure=KnowledgeInvocationFailure(
            code=AgentErrorCode.SERVICE_PAUSED, safe_message="legacy unknown", transient=False
        ),
        completed_at=f.outcome.completed_at,
    )
    key = intent.binding.run_id + ":intent"
    f.records.put("knowledge-invocation-intents", key, intent)
    f.records.put("knowledge-invocation-outcomes", key, outcome)


@pytest.mark.parametrize("reader", ["capacity", "replay"])
def test_legacy_readers_exclude_only_the_exact_independently_isolated_lease(
    tmp_path: Path, reader: str
) -> None:
    fixture = replay_facts(tmp_path) if reader == "replay" else None
    f = fixture.facts if fixture is not None else knowledge_failure(tmp_path, returned=True)
    append_unknown_preparation(f, "lease_independently_isolated")

    def read(excluded: frozenset[str]) -> object:
        # Keep both public typed reader calls explicit so type checking covers the seams.
        if fixture is not None:
            return read_replay_guarded_claims(
                state=f.collector.state,
                task=f.task,
                scope=f.collector.scope,
                requirement_id=f.collector.requirement_id,
                queue=f.collector.queue,
                require_step=f.collector._require_step,
                isolated_lease_ids=excluded,
                item=f.item,
                claims=(f.claim,),
                no_start_reader=f.collector._capacity_input_reader(),
                fence=PriorInvocationFence(fixture.start),
            )
        return read_capacity_claim_snapshot(
            state=f.collector.state,
            task=f.task,
            scope=f.collector.scope,
            requirement_id=f.collector.requirement_id,
            queue=f.collector.queue,
            require_step=f.collector._require_step,
            isolated_lease_ids=excluded,
            marker=_marker(f),
            historical=f.claim,
        )

    with pytest.raises(ValueError):
        read(frozenset())
    excluded = frozenset(("lease_independently_isolated",))
    assert read(excluded)
    append_unknown_preparation(f, "lease_foreign_unproved")
    with pytest.raises(ValueError):
        read(excluded)


@pytest.mark.parametrize("alias_work_item", [False, True])
def test_legacy_reader_rejects_another_pending_intent_on_the_same_real_lease(
    tmp_path: Path, alias_work_item: bool
) -> None:
    f = legacy_reader_fixture(tmp_path)
    claim = (
        f.claim.model_copy(
            update={"work_item": f.claim.work_item.model_copy(update={"id": "work_alias"})}
        )
        if alias_work_item
        else f.claim
    )
    another = KnowledgeInvocationIntent.create(
        binding=f.intent.binding.model_copy(update={"run_id": "run_other_pending"}),
        phase="assessment",
        request_sha256="e" * 64,
        timeout_seconds=2,
        claim=claim,
        created_at=f.intent.created_at,
    )
    f.records.put("knowledge-invocation-intents", another.binding.run_id + ":assessment", another)
    with pytest.raises(ValueError, match=r"一个|同一真实 claim"):
        read_legacy(f)


def test_isolation_cannot_refund_exhausted_ordinary_work(tmp_path: Path) -> None:
    f, proof = isolation_fixture(tmp_path)
    from ai_software_engineer.manager.baseline_production import ProductionBaselineFactCollector

    collector = ProductionBaselineFactCollector.__new__(ProductionBaselineFactCollector)
    task = f.collector.facts.task.model_copy(
        update={"attempts": f.collector.facts.task.max_attempts}
    )
    with pytest.raises(ValueError, match="普通工作额度"):
        collector._reservation(task, proof.original_claim.work_item, (), knowledge_isolation=proof)


def test_old_reservation_wire_omits_isolation_fields() -> None:
    value = BaselineExecutionReservation(
        current_attempt=1, next_execution_attempt=1, retry_cause="uninvoked"
    )
    assert "knowledge_isolation_sha256" not in value.to_wire()
