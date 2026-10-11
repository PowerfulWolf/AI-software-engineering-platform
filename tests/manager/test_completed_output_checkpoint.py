"""Completed-but-unaccepted Coder facts preserve history and consume ordinary work."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.agents.codex_cli import CodexCliAgentAdapter
from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.domain import AgentRole, Task, TaskStatus
from ai_software_engineer.domain.engineering_authority import (
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.git import GitWorktreeManager, WorkspacePolicyError, WorktreeSpec
from ai_software_engineer.git.baseline import GitExecutionBaselineAdapter
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.git.worktree import WorktreeCaptureRejected
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionFacts,
    BaselineExecutionReservation,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.baseline_production import ProductionBaselineFactCollector
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.completed_output_checkpoint import (
    CompletedCoderOutputUnavailableProof,
    require_completed_output_workspace,
)
from ai_software_engineer.manager.dispatch import DispatchCommitRecord
from ai_software_engineer.manager.execution_baseline import ExecutionBaselineService
from ai_software_engineer.orchestration.capture_reconciliation import CaptureStopProcessUncertain
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRecordMissing,
    ContinuationRejected,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.store import SqliteTaskRepository
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, MySqlRoleQueue
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueArtifactReceipt
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.git.test_worktree import _git
from tests.manager.test_baseline_wait_fact_collection import IdleQueue
from tests.manager.test_delivery_wait import seal_start
from tests.manager.test_execution_baseline import Collector, setup
from tests.orchestration.test_native_continuation import NOW, Guard
from tests.orchestration.test_native_continuation_v2 import V2Fixture

_SCHEMA = Path(__file__).parents[2] / "schemas" / "completed-coder-output-unavailable.schema.json"


def _outcome(start: DeliveryInvocationStart, result: AgentResult) -> DeliveryInvocationOutcome:
    value = DeliveryInvocationOutcome(start=start, result=result, outcome_sha256="0" * 64)
    return value.model_copy(
        update={"outcome_sha256": digest(value.model_dump(mode="json", exclude={"outcome_sha256"}))}
    )


def _capture_start(start: ExecutionCaptureStart, **changes: object) -> ExecutionCaptureStart:
    return ExecutionCaptureStart.create(
        **{**start.model_dump(mode="python", exclude={"start_sha256"}), **changes}
    )


def _capture_stop(stop: ExecutionCaptureStop, **changes: object) -> ExecutionCaptureStop:
    return ExecutionCaptureStop.create(
        **{**stop.model_dump(mode="python", exclude={"observation_sha256"}), **changes}
    )


class CompletedQueue(IdleQueue):
    retired_output_artifacts: frozenset[str] = frozenset()

    def rejected_output_artifact_ids(self, task_id: str) -> frozenset[str]:
        assert task_id == self.item.task_id
        return self.retired_output_artifacts


@dataclass
class CompletedFixture:
    native: V2Fixture
    queue: CompletedQueue
    collector: ProductionBaselineFactCollector
    start: DeliveryInvocationStart
    outcome: DeliveryInvocationOutcome
    capture_start: ExecutionCaptureStart
    capture_stop: ExecutionCaptureStop
    ledger: FileContinuationStore
    root: Path

    @property
    def task(self) -> Task:
        return self.native.repository.get(self.native.task.id)

    def proof(self, **changes: object) -> CompletedCoderOutputUnavailableProof:
        return CompletedCoderOutputUnavailableProof.create(
            **{
                "outcome": self.outcome,
                "capture_start": self.capture_start,
                "capture_stop": self.capture_stop,
                **changes,
            }
        )

    def collect(self) -> CompletedCoderOutputUnavailableProof | None:
        with self.collector.execution_scope():
            assert self.queue.entered and self.collector.guard.inherited_fds
            return self.collector._completed_output(self.task, self.queue.item, self.queue.bound)

    def capture(self) -> CapturedMutations:
        return CapturedMutations.from_capture(
            self.native.git.capture_mutations(self.native.worktree, self.native.request.permissions)
        )

    def sealed_bytes(self) -> dict[Path, bytes]:
        return {path: path.read_bytes() for path in self.root.rglob("*.json")}


@pytest.fixture
def completed(
    tmp_path: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[CompletedFixture]:
    descriptor = os.open(tmp_path / "original.lock", os.O_RDWR | os.O_CREAT, 0o600)
    problem = getattr(request, "param", None)
    stopped_provider = isinstance(problem, str) and problem.startswith("stopped_provider")
    rejected_output = isinstance(problem, str) and problem.startswith("invalid_")
    variant = (
        problem.removeprefix("invalid_")
        if isinstance(problem, str) and problem.startswith("invalid_")
        else problem
    )
    native = V2Fixture(
        tmp_path,
        Guard(descriptor),
        work_limit=1 if variant in {"exhausted", "stopped_provider_exhausted"} else 5,
    )
    process: subprocess.Popen[bytes] | None = None
    try:
        if variant in {"named", "named_policy"} or rejected_output or stopped_provider:
            # Baseline migration requires a semantic branch frozen in a fresh
            # NEW Task. Never alter a sealed invocation or an existing Task row.
            native.repository.close()
            native.task = Task.model_validate(
                {
                    **native.task.to_wire(),
                    "branch_name": "ai/feature/completed-source",
                    **(
                        {
                            "engineering_policy": EngineeringPolicy.bounded_local(
                                scope=EngineeringScope(
                                    team_id=native.scope.team_id,
                                    project_id=native.scope.project_id,
                                    repository_id=native.scope.repository_id,
                                    repository_root=native.task.repository,
                                ),
                                principal=LocalOperatorPrincipal.trusted_local(),
                            )
                        }
                        if variant == "named_policy"
                        else {}
                    ),
                }
            )
            assert native.task.status is TaskStatus.NEW
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

        def forbidden_model(self: CodexCliAgentAdapter, request: AgentRequest) -> AgentResult:
            raise AssertionError("completed-output fact collection must never invoke a model")

        monkeypatch.setattr(CodexCliAgentAdapter, "run", forbidden_model)
        queue = CompletedQueue(native)
        native.claim = queue.original
        if stopped_provider:
            # Permanent provider failure introduces no new mutations. The lawful
            # retained draft was already present at the immutable capture start.
            (native.worktree.path / "src/app.py").write_text("VALUE = 2\n")
        start = seal_start(native, queue, tmp_path)
        continuation = native.service()
        assert continuation.started(native.request, native.worktree.path) is not None
        if not stopped_provider:
            (native.worktree.path / "src/app.py").write_text("VALUE = 2\n")
        if variant in {"live_process", "stopped_provider_live_process"}:
            process = subprocess.Popen(
                (sys.executable, "-c", "import time; time.sleep(60)"), start_new_session=True
            )
            # A stale/forged historical observation must never defeat the current
            # real PGID probe. This test-owned process is cleaned up below.
            returncode = 1 if stopped_provider else 0
        else:
            process = subprocess.Popen(
                (
                    sys.executable,
                    "-c",
                    "raise SystemExit(1)" if stopped_provider else "raise SystemExit(0)",
                ),
                start_new_session=True,
            )
            returncode = process.wait(timeout=5)
        stop = NativeProcessStop.create(
            process_id=process.pid,
            group_id=process.pid,
            returncode=returncode,
            kind="failed" if stopped_provider else "completed",
            stopped_at=NOW + timedelta(seconds=1),
        )
        continuation.record_native_stop(
            native.request,
            native.worktree.path,
            process_stop=stop,
            output_present=not stopped_provider and variant != "output_absent",
            cause=None,
            original_error_code=AgentErrorCode.AUTHENTICATION_ERROR if stopped_provider else None,
        )
        capture_start = native.store.capture_start(native.request.run_id)
        capture_stop = native.store.capture_stop(native.request.run_id)
        ledger_root = tmp_path / "continuations" / native.task.id
        ledger_root.parent.mkdir(mode=0o700)
        ledger = FileContinuationStore.initialize(ledger_root, task_id=native.task.id)
        ledger.put_capture_start(capture_start)
        if variant not in {"missing_stop", "stopped_provider_missing_stop"}:
            ledger.put_capture_stop(capture_stop)
        result = (
            AgentResult.model_validate(
                {
                    **native.result().to_wire(),
                    "error": AgentFailure(
                        code=AgentErrorCode.AUTHENTICATION_ERROR,
                        message="原提供方凭证前提不满足。",
                        transient=False,
                    ),
                }
            )
            if stopped_provider
            else AgentResult.model_validate(
                {
                    **native.result().to_wire(),
                    "error": AgentFailure(
                        code=AgentErrorCode.INVALID_OUTPUT,
                        message="原产出未接纳; GIT_CONTRACT。",
                        transient=False,
                    ),
                }
            )
            if rejected_output
            else native.result()
        )
        outcome = _outcome(start, result)
        records = KnowledgeRecordStore(tmp_path / "invocations")
        records.put("invocation-outcomes", queue.item.id, outcome)
        native.guard.live = False
        task = native.repository.get(native.task.id)
        # Public Host coverage owns admission/dispatch validation. This seam uses
        # its already trusted allocation plus real Git, SQLite and Task lock.
        collector = ProductionBaselineFactCollector.__new__(ProductionBaselineFactCollector)
        collector.allocation = DispatchCommitRecord.model_construct(
            task=task, task_id=task.id, dispatch_sha256=native.scope.dispatch_sha256
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
        collector.permissions = native.request.permissions
        collector.guard = WorkerExecutionGuard()
        collector.locks_root = tmp_path / "idle-locks"
        collector._scope_held = False
        collector._idle_cursor = None
        yield CompletedFixture(
            native, queue, collector, start, outcome, capture_start, capture_stop, ledger, tmp_path
        )
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        native.repository.close()
        os.close(descriptor)


def test_exact_completed_failed_outcome_roundtrips_model_and_schema(
    completed: CompletedFixture,
) -> None:
    proof = completed.proof()
    proof.validate_integrity()
    assert proof.output_content_status == "unknown"
    assert proof.outcome.result.status is AgentRunStatus.FAILED
    assert proof.outcome.result.artifact is None
    assert proof.outcome.result.error == AgentFailure(
        code=AgentErrorCode.WORK_INTERRUPTED, message="草稿已保留。", transient=False
    )
    assert proof.capture_stop.process_stop.returncode == 0
    assert proof.capture_stop.output_present
    assert "workspace_ready" not in proof.to_wire()
    assert "capture" not in proof.to_wire()
    assert CompletedCoderOutputUnavailableProof.model_validate(proof.to_wire()) == proof
    Draft202012Validator(json.loads(_SCHEMA.read_text())).validate(proof.to_wire())


@pytest.mark.parametrize(
    "problem",
    [
        "output_absent",
        "cause",
        "original_error",
        "stop_failed",
        "returncode",
        "transient",
        "code",
        "status",
        "artifact",
    ],
)
@pytest.mark.parametrize("completed", [None, "invalid_named"], indirect=True)
def test_unsafe_completion_combinations_fail_model_and_static_schema(
    completed: CompletedFixture, problem: str
) -> None:
    f = completed
    proof = f.proof()
    wire = proof.to_wire()
    stop = cast(WirePayload, wire["capture_stop"])
    native_stop = cast(WirePayload, stop["process_stop"])
    result = cast(WirePayload, cast(WirePayload, wire["outcome"])["result"])
    error = cast(WirePayload, result["error"])
    if problem == "output_absent":
        stop["output_present"] = False
    elif problem == "cause":
        stop["cause"] = "provider_transient"
    elif problem == "original_error":
        stop["original_error_code"] = "PROVIDER_UNAVAILABLE"
    elif problem == "stop_failed":
        native_stop.update(kind="failed", returncode=7)
    elif problem == "returncode":
        native_stop["returncode"] = 7
    elif problem == "transient":
        error["transient"] = True
    elif problem == "code":
        error["code"] = "PROVIDER_ERROR"
    elif problem == "status":
        result["status"] = "TIMED_OUT"
        error["code"] = "TIMEOUT"
    else:
        result["artifact"] = f.native.artifacts.list_for_task(f.native.task.id)[0].to_wire()
    assert list(Draft202012Validator(json.loads(_SCHEMA.read_text())).iter_errors(wire))
    # Reseal independently valid components so a stale digest does not mask the
    # semantic gate. Inherently invalid AgentResult/stop combinations reject at
    # their own typed boundary.
    with pytest.raises((ValidationError, ValueError)):
        outcome = _outcome(f.start, AgentResult.model_validate(result))
        process_stop = NativeProcessStop.create(
            **{key: value for key, value in native_stop.items() if key != "stop_sha256"}
        )
        capture_stop = _capture_stop(
            f.capture_stop,
            process_stop=process_stop,
            output_present=stop["output_present"],
            cause=stop.get("cause"),
            original_error_code=stop.get("original_error_code"),
        )
        f.proof(outcome=outcome, capture_stop=capture_stop)


@pytest.mark.parametrize(
    "problem", ["request", "work_item", "lease", "checkpoint", "stop_ref", "stop_run", "stop_time"]
)
def test_proof_rejects_resealed_foreign_original_execution(
    completed: CompletedFixture, problem: str
) -> None:
    f = completed
    start, stop = f.capture_start, f.capture_stop
    if problem == "request":
        start = _capture_start(
            start, request=start.request.model_copy(update={"context_manifest_id": "ctx_foreign"})
        )
    elif problem == "work_item":
        start = _capture_start(
            start,
            claim=start.claim.model_copy(
                update={
                    "work_item": start.claim.work_item.model_copy(update={"id": "work_foreign"})
                }
            ),
        )
    elif problem == "lease":
        claim = start.claim
        start = _capture_start(
            start,
            claim=claim.model_copy(
                update={
                    "assignment": claim.assignment.model_copy(update={"lease_id": "lease_foreign"}),
                    "lease": claim.lease.model_copy(update={"id": "lease_foreign"}),
                }
            ),
        )
    elif problem == "checkpoint":
        start = _capture_start(start, task_revision=start.task_revision + 1)
    elif problem == "stop_ref":
        stop = _capture_stop(stop, capture_start_sha256="f" * 64)
    elif problem == "stop_run":
        stop = _capture_stop(stop, run_id="run_foreign")
    else:
        process = NativeProcessStop.create(
            **{
                **stop.process_stop.model_dump(exclude={"stop_sha256"}),
                "stopped_at": start.started_at - timedelta(seconds=1),
            }
        )
        stop = _capture_stop(stop, process_stop=process)
    if start != f.capture_start:
        stop = _capture_stop(stop, capture_start_sha256=start.start_sha256)
    with pytest.raises(ValueError):
        f.proof(capture_start=start, capture_stop=stop)


@pytest.mark.parametrize(
    "component",
    ["outcome", "invocation_start", "capture_start", "capture_stop", "process_stop", "proof"],
)
def test_each_original_digest_is_checked(completed: CompletedFixture, component: str) -> None:
    f = completed
    proof = f.proof()
    if component == "proof":
        bad = proof.model_copy(update={"proof_sha256": "f" * 64})
        with pytest.raises(ValueError, match="摘要"):
            bad.validate_integrity()
        return
    values: dict[str, object] = {}
    if component == "outcome":
        values["outcome"] = f.outcome.model_copy(update={"outcome_sha256": "f" * 64})
    elif component == "invocation_start":
        values["outcome"] = f.outcome.model_copy(
            update={"start": f.start.model_copy(update={"start_sha256": "f" * 64})}
        )
    elif component == "capture_start":
        values["capture_start"] = f.capture_start.model_copy(update={"start_sha256": "f" * 64})
    elif component == "capture_stop":
        values["capture_stop"] = f.capture_stop.model_copy(update={"observation_sha256": "f" * 64})
    else:
        values["capture_stop"] = f.capture_stop.model_copy(
            update={
                "process_stop": f.capture_stop.process_stop.model_copy(
                    update={"stop_sha256": "f" * 64}
                )
            }
        )
    with pytest.raises((ValueError, ContinuationRejected)):
        f.proof(**values)


def test_fenced_collector_rechecks_original_claim_stop_without_mutating_history(
    completed: CompletedFixture,
) -> None:
    f = completed
    before = f.sealed_bytes()
    task, events, item = f.task, f.native.repository.list_events(f.task.id), f.queue.item
    inventory = capture_mutation_inventory(f.native.worktree.path)
    assert f.collect() == f.proof()
    assert f.collect() == f.proof()
    assert f.queue.entries == 2 and not f.queue.entered
    assert f.task == task and f.native.repository.list_events(task.id) == events
    assert f.queue.item == item and not f.queue.consumed
    assert capture_mutation_inventory(f.native.worktree.path) == inventory
    assert f.sealed_bytes() == before


def test_collector_requires_real_task_lock(completed: CompletedFixture) -> None:
    f = completed
    before = f.sealed_bytes()
    with pytest.raises(ContinuationRejected):
        f.collector._completed_output(f.task, f.queue.item, f.queue.bound)
    assert f.sealed_bytes() == before and not f.queue.consumed


@pytest.mark.parametrize(
    "completed", ["missing_stop", "output_absent", "live_process"], indirect=True
)
def test_failed_outcome_without_exact_stopped_output_cannot_be_collected(
    completed: CompletedFixture,
) -> None:
    f = completed
    before, task = f.sealed_bytes(), f.task
    with pytest.raises((ContinuationRecordMissing, ValidationError, CaptureStopProcessUncertain)):
        f.collect()
    assert f.sealed_bytes() == before and f.task == task and not f.queue.consumed


@pytest.mark.parametrize(
    "problem",
    ["team", "project", "repository", "requirement", "dispatch", "claim", "source", "permissions"],
)
@pytest.mark.parametrize("completed", [None, "invalid_named"], indirect=True)
def test_fenced_collector_rejects_foreign_scope_claim_source_and_frozen_permissions(
    completed: CompletedFixture, problem: str
) -> None:
    f = completed
    if problem in {"team", "project", "repository"}:
        f.collector.scope = f.collector.scope.model_copy(
            update={f"{problem}_id": f"{problem}_foreign"}
        )
    elif problem == "requirement":
        f.collector.requirement_id = "delivery_foreign"
    elif problem == "dispatch":
        f.collector.allocation = f.collector.allocation.model_copy(
            update={"dispatch_sha256": "f" * 64}
        )
    elif problem == "claim":
        f.queue.original = f.queue.original.model_copy(update={"worker_id": "worker_foreign"})
    elif problem == "source":
        f.queue.bound = f.queue.bound.model_copy(
            update={"boundary": replace(f.queue.bound.boundary, source_revision="f" * 40)}
        )
    else:
        f.collector.permissions = f.collector.permissions.model_copy(
            update={"write_paths": ("**",)}
        )
    before = f.sealed_bytes()
    with pytest.raises((ValueError, ContinuationRejected)):
        f.collect()
    assert f.sealed_bytes() == before and not f.queue.consumed


@pytest.mark.parametrize("same_work", [True, False])
@pytest.mark.parametrize("completed", [None, "invalid_named"], indirect=True)
def test_existing_original_or_later_publication_cannot_be_overwritten(
    completed: CompletedFixture, same_work: bool
) -> None:
    f = completed
    f.queue.accepted_artifacts = (
        AcceptedRoleArtifact(
            task_id=f.task.id,
            work_item_id=f.queue.item.id if same_work else "work_later",
            lease_id=f.start.lease_id,
            dispatch_sequence=0,
            checkpoint_sequence=f.start.checkpoint_sequence
            if same_work
            else f.start.checkpoint_sequence + 1,
            run_id=f.native.request.run_id,
            context_manifest_id=f.native.request.context_manifest_id,
            source_revision=f.native.request.source_revision,
            receipt=QueueArtifactReceipt(artifact_id="art_progress_retained", sha256="a" * 64),
        ),
    )
    before = f.sealed_bytes()
    with pytest.raises(ValueError, match="发布或交付采纳"):
        f.collect()
    assert f.sealed_bytes() == before and not f.queue.consumed


@pytest.mark.parametrize("problem", [None, "current_work", "unconsumed", "ancestor"])
def test_only_exact_retired_publication_from_different_history_is_excluded(
    completed: CompletedFixture, problem: str | None
) -> None:
    f = completed
    retired_id = "art_progress_rejected_exact"
    f.queue.retired_output_artifacts = (
        frozenset() if problem == "unconsumed" else frozenset({retired_id})
    )
    publication = AcceptedRoleArtifact(
        task_id=f.task.id,
        work_item_id=f.queue.item.id if problem == "current_work" else "work_history",
        lease_id="lease_history",
        dispatch_sequence=0,
        # Queue checkpoint identity may be shared by historical and current work;
        # only the consumed decision's exact ID retires a historical publication.
        checkpoint_sequence=f.start.checkpoint_sequence,
        run_id="run_history",
        context_manifest_id="ctx_" + "b" * 64,
        source_revision=f.native.request.source_revision,
        receipt=QueueArtifactReceipt(
            artifact_id="art_progress_ancestor" if problem == "ancestor" else retired_id,
            sha256="a" * 64,
        ),
    )
    f.queue.accepted_artifacts = (publication,)
    before = f.sealed_bytes()
    if problem is None:
        assert f.collect() == f.proof()
    else:
        with pytest.raises(ValueError, match="发布或交付采纳"):
            f.collect()
    assert f.queue.accepted_artifacts == (publication,)
    assert f.sealed_bytes() == before and not f.queue.consumed


def test_completed_output_workspace_covers_legal_draft_and_explicit_cache(
    completed: CompletedFixture,
) -> None:
    f = completed
    cache = f.native.worktree.path / ".pytest_cache" / "fixture"
    cache.parent.mkdir()
    cache.write_text("cache facts\n")
    capture = f.capture()
    assert capture.to_capture().changed_paths == ("src/app.py",)
    before = capture_mutation_inventory(f.native.worktree.path)
    require_completed_output_workspace(f.proof(), capture, before, f.native.request.permissions, ())
    assert capture_mutation_inventory(f.native.worktree.path) == before


@pytest.mark.parametrize("path", ["ignored.tmp", "src/ignored.tmp"])
@pytest.mark.parametrize("completed", [None, "invalid_named"], indirect=True)
def test_git_ignored_noncaches_cannot_evade_full_inventory(
    completed: CompletedFixture, path: str
) -> None:
    f = completed
    (f.native.worktree.path / path).write_text("retained unknown source\n")
    capture = f.capture()
    assert path not in capture.to_capture().changed_paths
    before = capture_mutation_inventory(f.native.worktree.path)
    with pytest.raises((ValueError, WorkspacePolicyError)):
        require_completed_output_workspace(
            f.proof(), capture, before, f.native.request.permissions, ()
        )
    assert capture_mutation_inventory(f.native.worktree.path) == before


def test_authorized_noncaches_still_require_complete_draft_coverage(
    completed: CompletedFixture,
) -> None:
    f = completed
    partial = f.capture()
    (f.native.worktree.path / "src/extra.py").write_text("EXTRA = 3\n")
    inventory = capture_mutation_inventory(f.native.worktree.path)
    with pytest.raises(ValueError, match="全部非缓存变更"):
        require_completed_output_workspace(
            f.proof(), partial, inventory, f.native.request.permissions, ()
        )
    assert capture_mutation_inventory(f.native.worktree.path) == inventory


@pytest.mark.parametrize("problem", ["source", "task", "root", "permissions", "denied"])
@pytest.mark.parametrize("completed", [None, "invalid_named"], indirect=True)
def test_workspace_authorization_remains_bound_to_original_execution(
    completed: CompletedFixture, problem: str
) -> None:
    f = completed
    capture, permissions = f.capture(), f.native.request.permissions
    denied: tuple[str, ...] = ()
    if problem == "source":
        capture = capture.model_copy(update={"source_revision": "f" * 40})
    elif problem == "task":
        capture = capture.model_copy(update={"task_id": "task_foreign"})
    elif problem == "root":
        capture = capture.model_copy(update={"worktree_path": str(f.root)})
    elif problem == "permissions":
        permissions = permissions.model_copy(update={"write_paths": ("**",)})
    else:
        denied = ("src/app.py",)
    with pytest.raises((ValueError, WorkspacePolicyError)):
        require_completed_output_workspace(
            f.proof(),
            capture,
            capture_mutation_inventory(f.native.worktree.path),
            permissions,
            denied,
        )


def test_secret_draft_is_rejected_by_existing_real_git_capture(completed: CompletedFixture) -> None:
    f = completed
    (f.native.worktree.path / "src/app.py").write_text("password = 'fixture-private-value'\n")
    inventory, history = capture_mutation_inventory(f.native.worktree.path), f.sealed_bytes()
    with pytest.raises(WorktreeCaptureRejected):
        f.capture()
    assert capture_mutation_inventory(f.native.worktree.path) == inventory
    assert f.sealed_bytes() == history and not f.queue.consumed


def test_completed_output_reservation_charges_only_next_normal_work(
    completed: CompletedFixture,
) -> None:
    f = completed
    task, before = f.task, f.sealed_bytes()
    reservation = f.collector._reservation(task, f.queue.item, (), completed_output=f.proof())
    assert reservation.retry_cause == "completed_output_unavailable"
    assert reservation.current_attempt == 1 and reservation.next_execution_attempt == 2
    assert reservation.completed_output_sha256 == f.proof().proof_sha256
    assert reservation.current_invocation_start_sha256 == f.start.start_sha256
    assert reservation.current_invocation_outcome_sha256 == f.outcome.outcome_sha256
    assert reservation.retry_failure is None and not reservation.reservation_already_applied
    assert (
        reservation.interruption_receipt_sha256 is None and reservation.containment_sha256 is None
    )
    assert task.retry_failures is None and task.work_attempt == 1
    assert f.task == task and f.sealed_bytes() == before and not f.queue.consumed


@pytest.mark.parametrize("completed", ["exhausted"], indirect=True)
def test_completed_output_never_refunds_exhausted_work(completed: CompletedFixture) -> None:
    f = completed
    task, before = f.task, f.sealed_bytes()
    assert task.work_budget_exhausted and task.transient_failures(f.native.request.role) == 0
    with pytest.raises(ValueError, match="工作额度"):
        f.collector._reservation(task, f.queue.item, (), completed_output=f.proof())
    assert f.task == task and f.sealed_bytes() == before and not f.queue.consumed


def test_completed_output_cannot_reuse_already_reserved_successor(
    completed: CompletedFixture,
) -> None:
    f = completed
    with pytest.raises(ValueError, match="精确原执行"):
        f.collector._reservation(
            f.task.model_copy(update={"attempts": 2}), f.queue.item, (), completed_output=f.proof()
        )


@pytest.mark.parametrize(
    "problem", ["sha256", "size", "mode", "kind", "missing", "ignored_omission"]
)
@pytest.mark.parametrize("completed", ["named"], indirect=True)
def test_final_plan_model_rejects_incomplete_or_mismatched_inventory(
    completed: CompletedFixture, problem: str
) -> None:
    f = completed
    proof = f.proof()
    reservation = f.collector._reservation(f.task, f.queue.item, (), completed_output=proof)
    facts = BaselineExecutionFacts(
        task=f.task,
        scope=f.collector.scope,
        task_revision=f.native.repository.current_revision(f.task.id),
        work_item_id=f.queue.item.id,
        checkpoint_sequence=f.queue.item.checkpoint_sequence,
        quiescence_proof_sha256="1" * 64,
        runtime_manifest_sha256="2" * 64,
        source_native_rules_sha256="3" * 64,
        target_native_rules_sha256="3" * 64,
        source_artifact_ids=f.native.request.input_artifact_ids,
        continuation=reservation,
        completed_output=proof,
        permissions=f.native.request.permissions,
        denied_paths=(),
        facts_sha256="0" * 64,
    )
    facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    facts.validate_integrity()
    assert "workspace_ready" not in facts.to_wire()
    repository = Path(f.task.repository)
    (repository / "README.md").write_text("updated fixture baseline\n")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-m", "new fixture source baseline")
    target = _git(repository, "rev-parse", "HEAD")
    service = ExecutionBaselineService(
        store=FileExecutionBaselineStore(f.root / "private-baseline"),
        git=GitExecutionBaselineAdapter(f.native.git),
        facts=Collector(facts, f.native.worktree),
    )
    plan = service.propose(target)
    wire = plan.to_wire()
    assert ExecutionBaselinePlan.model_validate(wire) == plan
    inventory = cast(WirePayload, wire["before_inventory"])
    files = cast(list[WirePayload], inventory["files"])
    actual = next(item for item in files if item["path"] == "src/app.py")
    if problem == "sha256":
        actual["sha256"] = "f" * 64
    elif problem == "size":
        actual["size"] = cast(int, actual["size"]) + 1
    elif problem == "mode":
        actual["mode"] = 0o755
    elif problem == "kind":
        actual["kind"] = "symlink"
    elif problem == "missing":
        files.remove(actual)
    else:
        files.append(
            {
                "path": "src/ignored.tmp",
                "kind": "file",
                "sha256": "f" * 64,
                "mode": 0o644,
                "size": 10,
            }
        )
    with pytest.raises(ValidationError):
        ExecutionBaselinePlan.model_validate(wire)
    assert service.store.plan(plan.plan_sha256) == plan


@pytest.mark.parametrize(
    "problem", ["receipt", "refund", "containment", "already_applied", "next_attempt"]
)
@pytest.mark.parametrize("completed", [None, "invalid_named"], indirect=True)
def test_completed_reservation_forbids_other_capabilities_or_refund(
    completed: CompletedFixture, problem: str
) -> None:
    f = completed
    reservation = f.collector._reservation(f.task, f.queue.item, (), completed_output=f.proof())
    wire = reservation.to_wire()
    if problem == "receipt":
        wire["interruption_receipt_sha256"] = "f" * 64
    elif problem == "refund":
        wire["retry_failure"] = {
            "role": "coder",
            "attempt": 1,
            "run_id": f.native.request.run_id,
            "code": "PROVIDER_UNAVAILABLE",
        }
    elif problem == "containment":
        wire["containment_sha256"] = "f" * 64
    elif problem == "already_applied":
        wire["reservation_already_applied"] = True
    else:
        wire["next_execution_attempt"] = 3
    with pytest.raises(ValidationError):
        BaselineExecutionReservation.model_validate(wire)


def test_optional_completed_fields_preserve_old_canonical_bytes_keys_and_digests(
    tmp_path: Path,
) -> None:
    facts = setup(tmp_path).collector.facts
    assert facts.task.status is TaskStatus.IMPLEMENTING
    old_facts = facts.model_dump(mode="json", exclude={"completed_output"})
    assert "completed_output" not in facts.model_dump(mode="json")
    assert facts.model_dump(mode="json") == old_facts
    assert facts.facts_sha256 == digest(
        {key: value for key, value in old_facts.items() if key != "facts_sha256"}
    )
    facts.validate_integrity()
    reservation = BaselineExecutionReservation(
        current_attempt=1,
        next_execution_attempt=1,
        retry_cause="uninvoked",
        reservation_already_applied=True,
    )
    old_reservation = {
        "current_attempt": 1,
        "next_execution_attempt": 1,
        "retry_cause": "uninvoked",
        "original_run_id": None,
        "current_invocation_start_sha256": None,
        "current_invocation_outcome_sha256": None,
        "interruption_receipt_sha256": None,
        "retry_failure": None,
        "reservation_already_applied": True,
    }
    assert reservation.model_dump(mode="json") == old_reservation
    assert "completed_output_sha256" not in reservation.to_wire()
    assert digest(reservation.model_dump(mode="json")) == digest(old_reservation)
    records = KnowledgeRecordStore(tmp_path / "compatibility-records")
    key = digest(facts.to_wire())
    records.put("old-baseline-facts", key, facts)
    body = next(records.root.rglob("*.json")).read_bytes()
    reopened = KnowledgeRecordStore(records.root, read_only=True)
    restored = reopened.get("old-baseline-facts", key, BaselineExecutionFacts)
    assert restored == facts and digest(restored.to_wire()) == key
    assert next(records.root.rglob("*.json")).read_bytes() == body
