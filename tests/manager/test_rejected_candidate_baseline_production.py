"""Rejected native candidate recovery keeps exact existing intent and work budget."""

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import AgentResult, AgentRunStatus
from ai_software_engineer.domain import (
    AgentRole,
    ChangedFile,
    ChangeType,
    Task,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.execution_baseline import BaselinePurpose
from ai_software_engineer.domain.workforce import RoleAssignment
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import BaselineExecutionFacts
from ai_software_engineer.manager.baseline_production import (
    BaselineProposeCommand,
    ProductionBaselineFactCollector,
    native_rules_at_revision,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.dispatch import DispatchCommitRecord
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.manager.rejected_candidate_output import RejectedCandidateOutputProof
from ai_software_engineer.manager.rejected_candidate_owner import (
    RejectedCandidateExpiredOwnerSettlement,
    TaskProcessLockGuard,
)
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRecordMissing,
    ContinuationRejected,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.owned_sessions import OwnedSessionController
from ai_software_engineer.store import SqliteTaskRepository
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, RoleQueueAdmission
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.models import QueueArtifactReceipt, QueuedWorkItem
from ai_software_engineer.work_queue.worker import AcceptedArtifactStore, WorkerExecutionGuard
from tests.domain.factories import make_implementation_artifact
from tests.git.test_worktree import _git
from tests.manager.test_completed_output_checkpoint import CompletedQueue
from tests.manager.test_delivery_wait import seal_start
from tests.orchestration.test_native_continuation import Guard
from tests.orchestration.test_native_continuation_v2 import V2Fixture


def command(**changes: object) -> BaselineProposeCommand:
    return BaselineProposeCommand.model_validate(
        {
            "purpose": "rejected_candidate_rescue",
            "delivery_id": "delivery_fixture",
            "task_id": "task_fixture",
            "expected_task_intent_sha256": "1" * 64,
            "expected_task_revision": 3,
            "expected_work_item_id": "work_fixture",
            "expected_source_revision": "a" * 40,
            **changes,
        }
    )


def test_rejected_candidate_proposal_is_target_free_and_preserves_existing_mode() -> None:
    proposed = command()
    assert proposed.target_base_ref is None
    assert proposed.input_mode.value == "preserve_draft"


@pytest.mark.parametrize(
    "changes", [{"target_base_ref": "b" * 40}, {"input_mode": "coder_reapply"}]
)
def test_rejected_candidate_proposal_cannot_choose_a_source_or_reapply_mode(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        command(**changes)


@dataclass
class RejectedCandidateProductionFixture:
    native: V2Fixture
    queue: CompletedQueue
    collector: ProductionBaselineFactCollector
    outcome: DeliveryInvocationOutcome
    ledger: FileContinuationStore
    root: Path

    @property
    def task(self) -> Task:
        return self.native.repository.get(self.native.task.id)

    def proof(self) -> RejectedCandidateOutputProof:
        with self.collector.execution_scope():
            proof = self.collector._rejected_candidate_output(
                self.task, self.queue.item, self.queue.bound
            )
            assert proof is not None
            return proof

    def facts(self) -> BaselineExecutionFacts:
        proof = self.proof()
        values = BaselineExecutionFacts(
            task=self.task,
            scope=self.collector.scope,
            task_revision=proof.task_revision,
            work_item_id=self.queue.item.id,
            checkpoint_sequence=self.queue.item.checkpoint_sequence,
            quiescence_proof_sha256="1" * 64,
            runtime_manifest_sha256="2" * 64,
            source_native_rules_sha256="3" * 64,
            target_native_rules_sha256="3" * 64,
            source_artifact_ids=self.native.request.input_artifact_ids,
            continuation=self.collector._reservation(
                self.task, self.queue.item, (), rejected_candidate_output=proof
            ),
            rejected_candidate_output=proof,
            permissions=self.native.request.permissions,
            denied_paths=(),
            facts_sha256="0" * 64,
        )
        return values.model_copy(
            update={
                "facts_sha256": digest(values.model_dump(mode="json", exclude={"facts_sha256"}))
            }
        )


class RejectedCandidateQueue(CompletedQueue):
    def settle_rejected_candidate_expired_owner(
        self,
        *,
        task_id: str,
        task_lock: TaskProcessLockGuard,
        collect_current: Callable[[], RejectedCandidateOutputProof],
        seal: Callable[[RejectedCandidateExpiredOwnerSettlement], str],
    ) -> bool:
        # This non-SQL fixture represents no ACTIVE claim. Real SQL expiry,
        # heartbeat and persistence are covered by the queue MySQL tests.
        del collect_current, seal
        assert task_id == self.item.task_id and task_lock.inherited_fds
        task_lock.check_task_scope(task_id)
        return False

    def items_for_task(self, task_id: str) -> tuple[QueuedWorkItem, ...]:
        assert task_id == self.item.task_id
        return (self.item,)

    def list_assignments(self) -> tuple[RoleAssignment, ...]:
        return (self.original.assignment,)


@pytest.fixture
def rejected_candidate_production(tmp_path: Path) -> Iterator[RejectedCandidateProductionFixture]:
    """Actual Git/SQLite/owned stop facts; no real model, database or live requirement."""
    descriptor = os.open(tmp_path / "original.lock", os.O_RDWR | os.O_CREAT, 0o600)
    native = V2Fixture(tmp_path, Guard(descriptor))
    process: subprocess.Popen[bytes] | None = None
    try:
        native.repository.close()
        native.task = Task.model_validate(
            {
                **native.task.to_wire(),
                "branch_name": "ai/feature/rejected-candidate-source",
                "metadata": {**native.task.metadata, "repository_id": native.scope.repository_id},
            }
        )
        native.repository = SqliteTaskRepository(tmp_path / "tasks-named.sqlite")
        native.repository.create(native.task)
        native.repository.record_attempt(native.task.id, 1)
        native._event(TaskStatus.PLANNING, "task_validated", ())
        native._event(TaskStatus.IMPLEMENTING, "plan_validated", ("art_plan_001",))
        native.git.remove(native.worktree)
        native.git = GitWorktreeManager(
            Path(native.task.repository),
            tmp_path / "worktrees",
            branch_names={native.task.id: native.task.branch_name},
        )
        native.worktree = native.git.create(
            WorktreeSpec(
                task_id=native.task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=native.task.base_ref,
            )
        )
        native.activate(1)
        queue = RejectedCandidateQueue(native)
        queue.bound = queue.bound.model_copy(
            update={"allocation_sha256": native.scope.dispatch_sha256}
        )
        queue.item = queue.item.model_copy(
            update={"status": WorkItemStatus.RUNNING, "wait_disposition": None, "wait_reason": None}
        )
        native.claim = queue.original
        start = seal_start(native, queue, tmp_path)
        continuation = native.service()
        assert continuation.started(native.request, native.worktree.path) is not None
        (native.worktree.path / "src/app.py").write_text("VALUE = 2\n")
        _git(native.worktree.path, "add", "src/app.py")
        _git(native.worktree.path, "commit", "-m", "test-owned unaccepted historical candidate")
        candidate = _git(native.worktree.path, "rev-parse", "HEAD")
        native.worktree = replace(native.worktree, head_revision=candidate)
        process = subprocess.Popen(
            (sys.executable, "-c", "import time; time.sleep(0.2)"), start_new_session=True
        )
        controller = OwnedSessionController(process)
        assert process.wait(timeout=5) == 0
        session_proof = controller.require_empty()
        stop = NativeProcessStop.create(
            process_id=process.pid,
            group_id=process.pid,
            kind="completed",
            returncode=0,
            stopped_at=datetime.now(UTC),
            session_proof=session_proof,
        )
        continuation.record_native_stop(
            native.request,
            native.worktree.path,
            process_stop=stop,
            output_present=True,
            cause=None,
            original_error_code=None,
        )
        ledger_root = tmp_path / "continuations" / native.task.id
        ledger_root.parent.mkdir(mode=0o700)
        ledger = FileContinuationStore.initialize(ledger_root, task_id=native.task.id)
        ledger.put_capture_start(native.store.capture_start(native.request.run_id))
        ledger.put_capture_stop(native.store.capture_stop(native.request.run_id))
        template = make_implementation_artifact()
        report = template.model_copy(
            update={
                "schema_version": "v1.0",
                "task_id": native.task.id,
                "source_revision": candidate,
                "context_manifest_id": native.request.context_manifest_id,
                "parent_artifact_ids": native.request.input_artifact_ids,
                "producer": template.producer.model_copy(
                    update={
                        "run_id": native.request.run_id,
                        "agent_id": native.claim.assignment.agent_id,
                    }
                ),
                "content": template.content.model_copy(
                    update={
                        "commit_sha": candidate,
                        "changed_files": (
                            ChangedFile(
                                path="src/app.py",
                                change=ChangeType.MODIFIED,
                                lines_added=1,
                                lines_deleted=1,
                            ),
                        ),
                    }
                ),
            }
        )
        result = AgentResult(
            run_id=native.request.run_id,
            task_id=native.task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=native.request.source_revision,
            context_manifest_id=native.request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=report,
        )
        outcome = DeliveryInvocationOutcome(start=start, result=result, outcome_sha256="0" * 64)
        outcome = outcome.model_copy(
            update={
                "outcome_sha256": digest(
                    outcome.model_dump(mode="json", exclude={"outcome_sha256"})
                )
            }
        )
        KnowledgeRecordStore(tmp_path / "invocations").put(
            "invocation-outcomes", queue.item.id, outcome
        )
        native.guard.live = False
        collector = ProductionBaselineFactCollector.__new__(ProductionBaselineFactCollector)
        collector.allocation = DispatchCommitRecord.model_construct(
            task=native.repository.get(native.task.id),
            task_id=native.task.id,
            dispatch_sha256=native.scope.dispatch_sha256,
        )
        collector.scope = EngineeringScope(
            team_id=native.scope.team_id,
            project_id=native.scope.project_id,
            repository_id=native.scope.repository_id,
            repository_root=native.task.repository,
        )
        collector.requirement_id = native.scope.requirement_id
        collector.repository = native.repository
        collector.state = tmp_path
        collector.queue = cast(MySqlRoleQueue, queue)
        collector.git = native.git
        collector.capacity_artifacts = native.artifacts
        collector.permissions = native.request.permissions
        collector.guard = WorkerExecutionGuard()
        collector.locks_root = tmp_path / "idle-locks"
        collector._scope_held = False
        collector._idle_cursor = None
        collector.purpose = BaselinePurpose.REJECTED_CANDIDATE_RESCUE
        collector._proposal_command = None
        collector.route_root = tmp_path / "model-routes"
        collector.native_rules = native_rules_at_revision(
            native.git, repository_id=collector.scope.repository_id, revision=native.task.base_ref
        )
        collector.runtime_manifest_sha256 = "2" * 64
        collector.structured_project_rules = ()
        collector.inputs = StoredCoderExecutionInputResolver(
            FileExecutionBaselineStore(tmp_path / "baseline-records")
        )
        queue.queue_admission = RoleQueueAdmission(
            task_id=native.task.id,
            repository_id=collector.scope.repository_id,
            allocation_sha256=native.scope.dispatch_sha256,
            legacy_artifacts=tuple(
                QueueArtifactReceipt(
                    artifact_id=a.artifact_id,
                    sha256=a.integrity.sha256,
                )
                for a in native.artifacts.list_for_task(native.task.id)
            ),
        )
        collector.artifacts = AcceptedArtifactStore(
            native.artifacts, cast(MySqlRoleQueue, queue), native.task.id, collector.guard
        )
        yield RejectedCandidateProductionFixture(
            native, queue, collector, outcome, ledger, tmp_path
        )
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        native.repository.close()
        os.close(descriptor)


def test_exact_stopped_rejected_candidate_is_reopened_without_rewriting_history(
    rejected_candidate_production: RejectedCandidateProductionFixture,
) -> None:
    f = rejected_candidate_production
    before = capture_mutation_inventory(f.native.worktree.path)
    history = {p: p.read_bytes() for p in f.root.rglob("*.json")}
    proof = f.proof()
    assert proof.outcome == f.outcome
    assert proof.candidate_parent_revision == f.native.request.source_revision
    assert proof.candidate_revision == f.native.worktree.head_revision
    assert proof.complete_capture.patch
    assert proof.complete_capture.base_revision == f.task.base_ref
    facts = f.facts()
    assert facts.continuation is not None
    assert facts.continuation.retry_cause == "rejected_candidate_output"
    assert facts.continuation.current_attempt == f.task.attempts
    assert facts.continuation.next_execution_attempt == f.task.attempts + 1
    assert facts.continuation.retry_failure is None
    assert not facts.continuation.reservation_already_applied
    assert f.queue.item.status is WorkItemStatus.RUNNING
    assert f.task.base_ref == f.native.request.source_revision and f.task.attempts == 1
    assert f.task.retry_failures is None
    assert capture_mutation_inventory(f.native.worktree.path) == before
    assert all(p.read_bytes() == content for p, content in history.items())


@pytest.mark.parametrize("path", ["src/app.py", "extra.txt", "ignored.tmp"])
def test_changed_candidate_or_extra_ignored_bytes_fail_closed(
    rejected_candidate_production: RejectedCandidateProductionFixture,
    path: str,
) -> None:
    f = rejected_candidate_production
    (f.native.worktree.path / path).write_text("unexpected change\n")
    with pytest.raises((ValueError, ContinuationRejected)):
        f.proof()
    assert f.queue.item.status is WorkItemStatus.RUNNING
    assert f.task.attempts == 1


def test_rejected_candidate_still_requires_original_claim_and_real_stop(
    rejected_candidate_production: RejectedCandidateProductionFixture,
) -> None:
    f = rejected_candidate_production
    f.queue.original = f.queue.original.model_copy(update={"worker_id": "worker_foreign"})
    with pytest.raises((ValueError, ContinuationRejected)):
        f.proof()
    assert f.task.attempts == 1 and f.outcome.result.status is AgentRunStatus.SUCCEEDED


def test_supported_success_cannot_be_overwritten_without_exact_rejection_proof(
    rejected_candidate_production: RejectedCandidateProductionFixture,
) -> None:
    f = rejected_candidate_production
    with pytest.raises(ValueError, match="成功结果"):
        f.collector._reservation(f.task, f.queue.item, ())
    proof = f.proof()
    f.collector.purpose = BaselinePurpose.COMPLETED_OUTPUT_RESCUE
    with pytest.raises(ValueError, match="精确原调用身份"):
        f.collector._reservation(f.task, f.queue.item, (), rejected_candidate_output=proof)


def test_full_collector_uses_exact_running_scope_and_complete_unpublished_facts(
    rejected_candidate_production: RejectedCandidateProductionFixture,
) -> None:
    f = rejected_candidate_production
    with f.collector.execution_scope():
        facts = f.collector.collect(None)
        assert f.collector.collect(None) == facts
        assert f.collector.source_worktree(facts) == f.native.worktree
    assert facts.rejected_candidate_output is not None
    assert facts.completed_output is None and facts.implementation_artifact_id is None
    assert facts.task == f.task and facts.task_revision == 2
    assert f.queue.item.status is WorkItemStatus.RUNNING
    assert f.task.attempts == 1


def test_raw_original_run_publication_forbids_candidate_recovery(
    rejected_candidate_production: RejectedCandidateProductionFixture,
) -> None:
    f = rejected_candidate_production
    f.native._accept(
        make_implementation_artifact(),
        run_id=f.native.request.run_id,
        source=f.native.worktree.head_revision,
    )
    with pytest.raises(ValueError, match="发布产物"):
        f.proof()
    assert f.task.attempts == 1


def test_missing_original_stop_is_never_inferred_from_expired_claim(
    rejected_candidate_production: RejectedCandidateProductionFixture,
) -> None:
    f = rejected_candidate_production
    (f.root / "continuations" / f.task.id / f"capture-stop-{f.native.request.run_id}.json").unlink()
    with pytest.raises(ContinuationRecordMissing):
        f.proof()
    assert f.queue.item.status is WorkItemStatus.RUNNING and f.task.attempts == 1


def test_rejected_candidate_collect_refuses_foreign_running_and_nonrunning_items(
    rejected_candidate_production: RejectedCandidateProductionFixture,
) -> None:
    f = rejected_candidate_production
    f.queue.item = f.queue.item.model_copy(update={"status": WorkItemStatus.READY})
    with f.collector.execution_scope(), pytest.raises(ValueError, match="原运行工作项"):
        f.collector.collect(None)
    assert f.task.attempts == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_id", "task_foreign"),
        ("expected_task_intent_sha256", "f" * 64),
        ("expected_task_revision", 99),
        ("expected_work_item_id", "work_foreign"),
        ("expected_source_revision", "f" * 40),
        ("delivery_id", "delivery_foreign"),
    ],
)
def test_stale_proposal_rejects_before_expired_owner_proof_or_seal(
    rejected_candidate_production: RejectedCandidateProductionFixture,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str | int,
) -> None:
    f = rejected_candidate_production
    command = BaselineProposeCommand(
        purpose=BaselinePurpose.REJECTED_CANDIDATE_RESCUE,
        delivery_id=f.collector.requirement_id,
        task_id=f.task.id,
        expected_task_intent_sha256=task_intent_sha256(f.task),
        expected_task_revision=f.native.repository.current_revision(f.task.id),
        expected_work_item_id=f.queue.item.id,
        expected_source_revision=f.native.request.source_revision,
    ).model_copy(update={field: value})
    f.collector.bind_proposal(command)

    def attempt_expiry(
        *,
        task_id: str,
        task_lock: TaskProcessLockGuard,
        collect_current: Callable[[], RejectedCandidateOutputProof],
        seal: Callable[[RejectedCandidateExpiredOwnerSettlement], str],
    ) -> bool:
        del seal
        task_lock.check_task_scope(task_id)
        collect_current()
        raise AssertionError("stale command must reject before owner settlement")

    def forbidden_proof(*args: object) -> RejectedCandidateOutputProof:
        del args
        raise AssertionError("stale command cannot collect or publish original proof")

    monkeypatch.setattr(f.queue, "settle_rejected_candidate_expired_owner", attempt_expiry)
    monkeypatch.setattr(f.collector, "_rejected_candidate_output", forbidden_proof)
    store = f.collector.inputs.store
    assert store is not None
    before = {path: path.read_bytes() for path in store.root.iterdir()}
    with pytest.raises(ValueError, match="事实已变化"), f.collector.execution_scope():
        raise AssertionError("stale command cannot enter the idle execution scope")
    assert {path: path.read_bytes() for path in store.root.iterdir()} == before
    assert f.task.attempts == 1 and f.queue.item.status is WorkItemStatus.RUNNING
