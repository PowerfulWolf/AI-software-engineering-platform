"""A completed but rejected progress report preserves its exact legal draft."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import AgentErrorCode, AgentRunStatus, CodexCliAgentAdapter
from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.workspace_admission import ConditionalWorkspaceAdmission
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain.artifact import ChangedFile
from ai_software_engineer.domain.enums import ChangeType, WorkItemStatus
from ai_software_engineer.git import WorkspacePolicyError, WorktreeCaptureRejected
from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
from ai_software_engineer.manager.rejected_output_checkpoint import (
    RejectedCoderOutputAdmission,
    read_rejected_checkpoint,
)
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    MySqlRoleQueue,
    RoleQueueAdmission,
)
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.models import QueueArtifactReceipt
from ai_software_engineer.work_queue.ports import QueueCorruption
from ai_software_engineer.work_queue.worker import AcceptedArtifactStore, WorkerExecutionGuard
from tests.agents.test_codex_cli import _CoderRunner, _repository
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request
from tests.domain.factories import make_plan_artifact
from tests.git.test_worktree import _git
from tests.manager.test_delivery_wait import (
    WaitQueue,
    _outcome,
    _reject_wait,
    _successful_progress,
    service,
)
from tests.manager.test_wait_fact_collection import collector
from tests.orchestration.test_native_continuation import NOW, Guard, claim
from tests.orchestration.test_native_continuation_v2 import V2Fixture


@dataclass
class RejectedFixture:
    native: V2Fixture
    queue: WaitQueue
    entry: DeliveryWaitService
    facts: DeliveryWaitFactCollector
    outcome: DeliveryInvocationOutcome
    stop_sha256: str
    original_files: dict[Path, bytes]

    def collect(self, root: Path) -> None:
        guard = WorkerExecutionGuard()
        with guard.task_scope(root / "idle-locks", self.native.task.id):
            self.facts.collect(
                self.native.repository.get(self.native.task.id), self.queue.bound, guard
            )


@contextmanager
def rejected_fixture(
    tmp_path: Path, *, inherited: bool = False, work_limit: int = 5, mismatch: bool = True
) -> Iterator[RejectedFixture]:
    descriptor = os.open(tmp_path / "owner.lock", os.O_RDWR | os.O_CREAT, 0o600)
    native = V2Fixture(tmp_path, Guard(descriptor), work_limit=work_limit)
    try:
        queue = WaitQueue(native)
        native.claim = queue.original
        _reject_wait(queue, "PLATFORM_BUG")
        if inherited:
            (native.worktree.path / "src/app.py").write_text("VALUE = 7\n")
        continuation = native.service()
        continuation.started(native.request, native.worktree.path)
        (native.worktree.path / "src/app.py").write_text("VALUE = 2\n")
        progress = _successful_progress(native, queue)
        assert progress.artifact is not None
        content = progress.artifact.content.model_copy(
            update={
                "checkpoint_sequence": native.request.attempt + (8 if mismatch else 0),
                "changed_files": (
                    ChangedFile(
                        path="src/app.py",
                        change=ChangeType.MODIFIED,
                        lines_added=1,
                        lines_deleted=1,
                    ),
                ),
            }
        )
        progress = progress.model_copy(
            update={"artifact": progress.artifact.model_copy(update={"content": content})}
        )
        assert progress.artifact is not None
        outcome = _outcome(native, queue, tmp_path, progress)
        continuation.record_native_stop(
            native.request,
            native.worktree.path,
            process_stop=NativeProcessStop.create(
                process_id=999_999,
                group_id=999_999,
                returncode=0,
                kind="completed",
                stopped_at=NOW + timedelta(seconds=1),
            ),
            output_present=True,
            cause=None,
            original_error_code=None,
        )
        capture_root = tmp_path / "continuations" / native.task.id
        capture_root.parent.mkdir(mode=0o700)
        capture_store = FileContinuationStore.initialize(capture_root, task_id=native.task.id)
        capture_store.put_capture_start(native.store.capture_start(native.request.run_id))
        stop = capture_store.put_capture_stop(native.store.capture_stop(native.request.run_id))
        artifacts = FileArtifactStore(tmp_path / "artifacts")
        artifacts.put(
            seal_artifact(
                make_plan_artifact().model_copy(update={"task_id": native.task.id}),
                validated_at=NOW,
            )
        )
        reference = artifacts.put(seal_artifact(progress.artifact, validated_at=NOW))
        queue.accepted_artifacts = (
            AcceptedRoleArtifact(
                task_id=native.task.id,
                work_item_id=queue.item.id,
                lease_id=queue.original.lease.id,
                dispatch_sequence=queue.original.work_item.dispatch_sequence,
                checkpoint_sequence=queue.bound.boundary.checkpoint_sequence,
                run_id=native.request.run_id,
                context_manifest_id=native.request.context_manifest_id,
                source_revision=native.request.source_revision,
                receipt=QueueArtifactReceipt(
                    artifact_id=reference.artifact_id, sha256=reference.sha256
                ),
            ),
        )
        original_files = {p: p.read_bytes() for p in capture_root.iterdir()}
        native.guard.live = False
        facts = collector(native, queue, tmp_path)
        entry = service(native, queue, tmp_path)
        entry.artifacts = artifacts
        entry.fact_collector = facts.collect
        entry.stop_observer = facts.observe_stop
        yield RejectedFixture(
            native, queue, entry, facts, outcome, stop.process_stop.stop_sha256, original_files
        )
    finally:
        native.repository.close()
        os.close(descriptor)


def test_completed_rejected_progress_gets_a_separate_exact_checkpoint(tmp_path: Path) -> None:
    with rejected_fixture(tmp_path) as fixture:
        fixture.collect(tmp_path)
        proof = fixture.entry.inspect(fixture.queue.command())
        assert [kind.value for kind in proof.permitted_resolutions] == [
            "RETRY_REJECTED_CODER_OUTPUT"
        ]
        assert not proof.missing
        assert proof.process_stop_sha256 == fixture.stop_sha256
        assert proof.invocation_outcome_sha256 == fixture.outcome.outcome_sha256
        assert proof.retry_cause is None
        assert all(path.read_bytes() == body for path, body in fixture.original_files.items())
        assert not list((tmp_path / "continuations").rglob("receipt*.json"))
        fixture.collect(tmp_path)
        assert (
            fixture.entry.inspect(fixture.queue.command()).rejected_output == proof.rejected_output
        )


@pytest.mark.parametrize("path", ["ignored.tmp", "AGENTS.md", "src/AGENTS.md"])
def test_rejected_checkpoint_never_admits_ignored_or_protected_mutations(
    tmp_path: Path, path: str
) -> None:
    with rejected_fixture(tmp_path) as fixture:
        (fixture.native.worktree.path / path).write_text("unauthorized\n")
        with pytest.raises((ContinuationRejected, WorktreeCaptureRejected, WorkspacePolicyError)):
            fixture.collect(tmp_path)
        assert read_rejected_checkpoint(tmp_path, fixture.queue.item.id) is None


def test_rejected_checkpoint_keeps_legal_existing_dirty_work(tmp_path: Path) -> None:
    with rejected_fixture(tmp_path, inherited=True) as fixture:
        fixture.collect(tmp_path)
        proof = fixture.entry.inspect(fixture.queue.command())
        assert proof.rejected_output is not None and not proof.missing
        assert (fixture.native.worktree.path / "src/app.py").read_text() == "VALUE = 2\n"


def test_rejected_checkpoint_requires_an_empty_index(tmp_path: Path) -> None:
    with rejected_fixture(tmp_path) as fixture:
        _git(fixture.native.worktree.path, "add", "src/app.py")
        with pytest.raises(ContinuationRejected):
            fixture.collect(tmp_path)
        assert read_rejected_checkpoint(tmp_path, fixture.queue.item.id) is None


def test_rejected_admission_missing_decision_is_never_a_dirty_allowance(tmp_path: Path) -> None:
    with rejected_fixture(tmp_path) as fixture:
        admission = RejectedCoderOutputAdmission(
            state=tmp_path,
            git=fixture.native.git,
            task_reader=lambda: fixture.native.repository.get(fixture.native.task.id),
            claim_reader=lambda: fixture.queue.original,
            retry_reader=lambda _: None,
        )
        with pytest.raises(ContinuationRejected, match="缺少当前精确决定"):
            admission.authorize(fixture.native.request, fixture.native.worktree.path)


def test_collector_rejects_queue_drift_before_publication(tmp_path: Path) -> None:
    with rejected_fixture(tmp_path) as fixture:
        fixture.queue.item = fixture.queue.item.model_copy(update={"status": WorkItemStatus.CLOSED})
        with pytest.raises(ContinuationRejected):
            fixture.collect(tmp_path)
        assert read_rejected_checkpoint(tmp_path, fixture.queue.item.id) is None


def test_conditional_admission_without_decision_keeps_real_adapter_dirty_gate(
    tmp_path: Path,
) -> None:
    root, base = _repository(tmp_path)
    (root / "src").mkdir()
    (root / "src/draft.py").write_text("draft = True\n")
    request = _coder_request().model_copy(update={"source_revision": base})
    runner = _CoderRunner(request)
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture-model",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=runner,
        initial_workspace_admission=ConditionalWorkspaceAdmission(lambda _: None),
    )
    result = adapter.run(request)
    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None and result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert not runner.calls
    assert (root / "src/draft.py").read_text() == "draft = True\n"


@pytest.mark.parametrize(
    "drift", [None, "run", "context", "source", "permissions", "parent", "inventory"]
)
def test_rejected_admission_rechecks_exact_new_claim_and_retained_workspace(
    tmp_path: Path, drift: str | None
) -> None:
    with rejected_fixture(tmp_path) as fixture:
        fixture.collect(tmp_path)
        record = read_rejected_checkpoint(tmp_path, fixture.queue.item.id)
        assert record is not None
        evidence = record.evidence
        fixture.native.repository.record_attempt(fixture.native.task.id, 2)
        task = fixture.native.repository.get(fixture.native.task.id)
        current = claim(task, 2)
        current = current.model_copy(
            update={
                "work_item": current.work_item.model_copy(
                    update={
                        "parent_work_item_id": evidence.work_item_id,
                        "checkpoint_sequence": evidence.checkpoint_sequence,
                    }
                )
            }
        )
        request = fixture.native.request.model_copy(
            update={
                "attempt": 2,
                "run_id": "run_fresh_retry",
                "context_manifest_id": "ctx_" + "9" * 64,
            }
        )
        if drift == "run":
            request = request.model_copy(update={"run_id": evidence.previous_run_id})
        elif drift == "context":
            request = request.model_copy(
                update={"context_manifest_id": evidence.previous_context_manifest_id}
            )
        elif drift == "source":
            request = request.model_copy(update={"source_revision": "f" * 40})
        elif drift == "permissions":
            request = request.model_copy(
                update={
                    "permissions": request.permissions.model_copy(update={"write_paths": ("**",)})
                }
            )
        elif drift == "parent":
            current = current.model_copy(
                update={
                    "work_item": current.work_item.model_copy(
                        update={"parent_work_item_id": "work_unrelated"}
                    )
                }
            )
        elif drift == "inventory":
            (fixture.native.worktree.path / "src/app.py").write_text("VALUE = 8\n")
        admission = RejectedCoderOutputAdmission(
            state=tmp_path,
            git=fixture.native.git,
            task_reader=lambda: task,
            claim_reader=lambda: current,
            retry_reader=lambda _: evidence,
        )
        if drift is None:
            admission.authorize(request, fixture.native.worktree.path)
        else:
            with pytest.raises((ContinuationRejected, WorktreeCaptureRejected)):
                admission.authorize(request, fixture.native.worktree.path)


def test_consumed_rejection_filters_only_exact_artifact_and_keeps_parent_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with rejected_fixture(tmp_path) as fixture:
        artifacts = fixture.entry.artifacts
        assert artifacts is not None
        plan = artifacts.get("art_plan_001")
        publication = fixture.queue.accepted_artifacts[0]
        admission = RoleQueueAdmission(
            task_id=fixture.native.task.id,
            repository_id=fixture.queue.item.repository_id,
            allocation_sha256=fixture.queue.bound.allocation_sha256,
            legacy_artifacts=(
                QueueArtifactReceipt(artifact_id=plan.artifact_id, sha256=plan.integrity.sha256),
            ),
        )
        monkeypatch.setattr(fixture.queue, "admission", lambda _: admission, raising=False)
        monkeypatch.setattr(
            fixture.queue,
            "rejected_output_artifact_ids",
            lambda _: frozenset((publication.receipt.artifact_id,)),
            raising=False,
        )
        accepted = AcceptedArtifactStore(
            artifacts,
            cast(MySqlRoleQueue, fixture.queue),
            fixture.native.task.id,
            WorkerExecutionGuard(),
        )
        assert accepted.list_for_task(fixture.native.task.id) == (plan,)
        with pytest.raises(QueueCorruption):
            accepted.get(publication.receipt.artifact_id)
        assert (
            artifacts.get(publication.receipt.artifact_id).artifact_id
            == publication.receipt.artifact_id
        )


def test_rejected_output_does_not_refund_or_extend_exhausted_work_budget(tmp_path: Path) -> None:
    with rejected_fixture(tmp_path, work_limit=1) as fixture:
        fixture.collect(tmp_path)
        inspected = fixture.entry.inspect(fixture.queue.command())
        assert inspected.rejected_output is not None
        assert "BUDGET_EXHAUSTED" in inspected.missing
        assert not inspected.permitted_resolutions
        assert not fixture.queue.consumed


def test_normal_completed_progress_is_never_captured_as_rejected(tmp_path: Path) -> None:
    with rejected_fixture(tmp_path, mismatch=False) as fixture:
        fixture.collect(tmp_path)
        assert read_rejected_checkpoint(tmp_path, fixture.queue.item.id) is None
        inspected = fixture.entry.inspect(fixture.queue.command())
        assert inspected.rejected_output is None
        assert not inspected.permitted_resolutions


def test_saved_rejected_checkpoint_validates_its_standalone_wire(tmp_path: Path) -> None:
    import json

    from jsonschema import Draft202012Validator

    with rejected_fixture(tmp_path) as fixture:
        fixture.collect(tmp_path)
        record = read_rejected_checkpoint(tmp_path, fixture.queue.item.id)
        assert record is not None
        schemas = Path(__file__).resolve().parents[2] / "schemas"
        schema = json.loads((schemas / "rejected-coder-output-checkpoint.schema.json").read_text())
        validator = Draft202012Validator(schema)
        wire = record.model_dump(mode="json", exclude_none=True)
        assert validator.is_valid(wire)
        wire["capture_stop"]["output_present"] = False
        assert not validator.is_valid(wire)
