"""Real-Git/SQLite multi-round continuation with sealed feedback and progress inputs."""

import fcntl
import hashlib
import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.continuation import (
    ContinuationExecutionUncertain,
    InterruptionBudgetExhausted,
    InterruptionObservation,
)
from ai_software_engineer.agents.models import AgentErrorCode, AgentRequest
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain import (
    AgentRole,
    Artifact,
    ArtifactKind,
    ChangedFile,
    ChangeType,
    CoderProgressArtifact,
    Finding,
    FindingSeverity,
    ImplementationReportArtifact,
    PlanArtifact,
    QaCriterionStatus,
    QaReportArtifact,
    QaReportStatus,
    QaTestStatus,
    ReviewReportArtifact,
    ReviewVerdict,
    Task,
    TaskStatus,
)
from ai_software_engineer.domain.continuation import InterruptionContinuationPolicy
from ai_software_engineer.domain.retry_policy import DeliveryRetryPolicy, TransientRetryPolicy
from ai_software_engineer.git import WorkspacePolicyError
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.retry import _active_progress, _latest
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import (
    make_coder_progress_artifact,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
)
from tests.git.test_worktree import _git
from tests.orchestration.test_native_continuation import (
    NOW,
    Fixture,
    Guard,
    _reclaim,
    claim,
)


class V2Fixture(Fixture):
    """Create a new v2 Task from NEW; never mutate the already-frozen v1 Task."""

    def __init__(
        self,
        root: Path,
        guard: Guard,
        *,
        work_limit: int = 5,
        transient_limit: int = 5,
        denied_paths: tuple[str, ...] = (),
    ) -> None:
        super().__init__(
            root, guard, coder_transient_limit=transient_limit, denied_paths=denied_paths
        )
        self.repository.close()
        retry = DeliveryRetryPolicy(
            max_work_attempts=work_limit,
            coder=TransientRetryPolicy(max_transient_failures=transient_limit),
        )
        assert self.task.constraints is not None
        self.task = Task.model_validate(
            {
                **self.task.to_wire(),
                "retry_policy": retry.to_wire(),
                "max_attempts": retry.execution_limit,
                "constraints": self.task.constraints.model_copy(
                    update={"max_attempts": retry.execution_limit}
                ).to_wire(),
                "interruption_continuation_policy": InterruptionContinuationPolicy.for_retry_budget(
                    max_work_attempts=work_limit,
                    max_coder_transient_failures=transient_limit,
                ).to_wire(),
            }
        )
        self.database = root / "tasks-v2.sqlite"
        self.repository = SqliteTaskRepository(self.database)
        self.repository.create(self.task)
        self.repository.record_attempt(self.task.id, 1)
        self._event(TaskStatus.PLANNING, "task_validated", ())
        self._event(TaskStatus.IMPLEMENTING, "plan_validated", ("art_plan_001",))
        self.artifacts = FileArtifactStore(root / "accepted-artifacts")
        self._accept(make_plan_artifact(), run_id="run_v2_plan", source=self.task.base_ref)
        self.activate(1)

    def _event(
        self,
        status: TaskStatus,
        reason: str,
        artifacts: tuple[str, ...],
        *,
        source: str | None = None,
    ) -> None:
        current = self.repository.get(self.task.id)
        sequence = self.repository.current_revision(self.task.id) + 1
        self.repository.append_event(
            build_event(
                current,
                status,
                event_id=f"evt_v2_{sequence:03d}",
                reason=reason,
                source_revision=source or self.task.base_ref,
                artifact_ids=artifacts,
                occurred_at=current.updated_at + timedelta(seconds=1),
            )
        )

    def _accept(self, template: Artifact, *, run_id: str, source: str) -> Artifact:
        index = len(self.artifacts.list_for_task(self.task.id))
        artifact = template.model_copy(
            update={
                "task_id": self.task.id,
                "source_revision": source,
                "created_at": NOW - timedelta(minutes=1) + timedelta(seconds=index),
                "context_manifest_id": (
                    self.request.context_manifest_id
                    if run_id == self.request.run_id
                    else "ctx_" + hashlib.sha256(run_id.encode()).hexdigest()
                ),
                "producer": template.producer.model_copy(update={"run_id": run_id}),
            }
        )
        sealed = seal_artifact(artifact, validated_at=NOW)
        reference = self.artifacts.put(sealed)
        return self.artifacts.get(reference.artifact_id)

    def _bindings(
        self,
    ) -> tuple[tuple[str, ...], dict[ArtifactKind, str | None], CoderProgressArtifact | None]:
        artifacts = self.artifacts.list_for_task(self.task.id)
        plan = _latest(artifacts, PlanArtifact)
        implementation = _latest(artifacts, ImplementationReportArtifact)
        progress = _active_progress(_latest(artifacts, CoderProgressArtifact), implementation)
        qa, review = _latest(artifacts, QaReportArtifact), _latest(artifacts, ReviewReportArtifact)
        assert plan is not None
        inputs = (
            plan,
            *(item for item in (qa, review) if item is not None),
            *((progress,) if progress is not None else ()),
        )
        return (
            tuple(item.artifact_id for item in inputs),
            {
                ArtifactKind.CODER_PROGRESS: progress.artifact_id if progress is not None else None,
                ArtifactKind.IMPLEMENTATION_REPORT: implementation.artifact_id
                if implementation is not None
                else None,
            },
            progress,
        )

    def activate(self, attempt: int) -> AgentRequest:
        inputs, supersedes, progress = self._bindings()
        self.request = self.request.model_copy(
            update={
                "run_id": f"run_v2_coder_{attempt:03d}",
                "attempt": attempt,
                "context_manifest_id": "ctx_"
                + hashlib.sha256(f"context-{attempt}".encode()).hexdigest(),
                "source_revision": self.repository.list_events(self.task.id)[-1].source_revision,
                "input_artifact_ids": inputs,
                "expected_parent_artifact_ids": inputs,
                "expected_supersedes_by_kind": supersedes,
                "continuation_checkpoint_id": progress.artifact_id
                if progress is not None
                else None,
                "continuation_changed_paths": tuple(
                    sorted(item.path for item in progress.content.changed_files)
                )
                if progress is not None
                else (),
            }
        )
        base_claim = claim(self.repository.get(self.task.id), attempt)
        self.claim = base_claim.model_copy(
            update={
                "work_item": base_claim.work_item.model_copy(
                    update={
                        "parent_work_item_id": f"work_native_{attempt - 1}"
                        if attempt > 1
                        else None,
                    }
                ),
            }
        )
        return self.request

    def _validate_request(self, request: AgentRequest) -> None:
        inputs, supersedes, progress = self._bindings()
        if (
            request.input_artifact_ids != inputs
            or request.expected_parent_artifact_ids != inputs
            or request.expected_supersedes_by_kind != supersedes
            or request.permissions != self.request.permissions
            or request.continuation_checkpoint_id
            != (progress.artifact_id if progress is not None else None)
            or request.continuation_changed_paths
            != (
                tuple(sorted(item.path for item in progress.content.changed_files))
                if progress is not None
                else ()
            )
        ):
            raise ContinuationRejected("changed current sealed feedback/progress bindings")

    def service(self) -> NativeCoderContinuation:
        return NativeCoderContinuation(
            scope=self.scope,
            store=self.store,
            git_workspace=self.git,
            guard=self.guard,
            current_task=lambda: self.repository.get(self.task.id),
            current_revision=lambda: self.repository.current_revision(self.task.id),
            claim=lambda: self.claim,
            has_accepted_output=lambda: any(
                item.producer.role is not AgentRole.ORCHESTRATOR
                for item in self.artifacts.list_for_task(self.task.id)
            ),
            has_accepted_output_for_request=lambda request: any(
                item.producer.run_id == request.run_id
                and item.context_manifest_id == request.context_manifest_id
                for item in self.artifacts.list_for_task(self.task.id)
            ),
            current_source_revision=lambda: (
                self.repository.list_events(self.task.id)[-1].source_revision
            ),
            validate_active_request=self._validate_request,
            clock=lambda: NOW,
        )

    def interrupt(
        self,
        service: NativeCoderContinuation,
        *,
        text: str | None = "VALUE = 2\n",
        provider: bool = False,
    ) -> ExecutionInterruptionReceipt:
        root = self.worktree.path
        before = service.started(self.request, root)
        assert before is not None
        if text is not None:
            (root / "src/app.py").write_text(text)
        observed = service.interrupted(
            self.request,
            root,
            before=before,
            cause="provider_transient" if provider else "local_execution_limit",
            original_error_code=AgentErrorCode.PROVIDER_UNAVAILABLE
            if provider
            else AgentErrorCode.TIMEOUT,
            process_stop=self.stopped(local=not provider),
            output_present=False,
        )
        assert observed is InterruptionObservation.CAPTURED
        return self.store.get_receipt(self.request.run_id)

    def reserve(self, service: NativeCoderContinuation) -> int | None:
        return service.next_attempt(
            self.repository.get(self.task.id), self.result(), self.repository
        )

    def restart(self) -> None:
        self.repository.close()
        self.repository = SqliteTaskRepository(self.database)
        self.store = FileContinuationStore(self.store_root, task_id=self.task.id)

    def progress(self) -> str:
        (self.worktree.path / "src/app.py").write_text("VALUE = 2\n")
        template = make_coder_progress_artifact()
        template = template.model_copy(
            update={
                "content": template.content.model_copy(
                    update={
                        "changed_files": (
                            ChangedFile(
                                path="src/app.py",
                                change=ChangeType.MODIFIED,
                                lines_added=1,
                                lines_deleted=1,
                            ),
                        ),
                        "tests_run": (),
                    }
                )
            }
        )
        progress = self._accept(template, run_id=self.request.run_id, source=self.task.base_ref)
        self._event(
            TaskStatus.CONTINUE_REQUIRED, "coder_requested_continuation", (progress.artifact_id,)
        )
        self._event(TaskStatus.QUEUED, "coder_continuation_queued", (progress.artifact_id,))
        self.repository.record_attempt(self.task.id, 2)
        self._event(TaskStatus.IMPLEMENTING, "coder_continuation_resumed", (progress.artifact_id,))
        self.activate(2)
        return progress.artifact_id

    def feedback(self, *, reviewer: bool) -> tuple[str, ...]:
        root = self.worktree.path
        (root / "src/app.py").write_text("VALUE = 2\n")
        _git(root, "add", "src/app.py")
        _git(root, "commit", "-m", "platform candidate fixture")
        candidate = _git(root, "rev-parse", "HEAD")
        self.worktree = replace(self.worktree, head_revision=candidate)
        implementation = make_implementation_artifact()
        implementation = implementation.model_copy(
            update={"content": implementation.content.model_copy(update={"commit_sha": candidate})}
        )
        accepted_implementation = self._accept(
            implementation, run_id=self.request.run_id, source=candidate
        )
        assert isinstance(accepted_implementation, ImplementationReportArtifact)
        implementation = accepted_implementation
        self._event(
            TaskStatus.QA, "candidate_ready", (implementation.artifact_id,), source=candidate
        )
        qa_template = make_qa_artifact()
        if not reviewer:
            qa_template = qa_template.model_copy(
                update={
                    "content": qa_template.content.model_copy(
                        update={
                            "status": QaReportStatus.FAIL,
                            "criteria_results": tuple(
                                item.model_copy(update={"status": QaCriterionStatus.FAIL})
                                for item in qa_template.content.criteria_results
                            ),
                            "tests_run": tuple(
                                item.model_copy(update={"status": QaTestStatus.FAIL})
                                for item in qa_template.content.tests_run
                            ),
                            "findings": (
                                Finding(
                                    finding_id="finding_v2_qa",
                                    severity=FindingSeverity.MAJOR,
                                    message="Greeting still fails the acceptance test.",
                                    file="src/app.py",
                                    line=1,
                                    evidence_ids=("ev_qa_tests",),
                                    recommendation="Fix the greeting and rerun the focused test.",
                                ),
                            ),
                        }
                    )
                }
            )
        qa = self._accept(qa_template, run_id="run_v2_qa_001", source=candidate)
        finding_ids: tuple[str, ...] = (qa.artifact_id,)
        if reviewer:
            self._event(TaskStatus.REVIEW, "qa_passed", finding_ids, source=candidate)
            review_template = make_review_artifact()
            review_template = review_template.model_copy(
                update={
                    "content": review_template.content.model_copy(
                        update={
                            "verdict": ReviewVerdict.REJECT,
                            "findings": (
                                Finding(
                                    finding_id="finding_v2_review",
                                    severity=FindingSeverity.MAJOR,
                                    message="The implementation misses the error case.",
                                    file="src/app.py",
                                    line=1,
                                    evidence_ids=("ev_review_diff",),
                                    recommendation="Handle the error case before resubmitting.",
                                ),
                            ),
                        }
                    )
                }
            )
            review = self._accept(review_template, run_id="run_v2_reviewer_001", source=candidate)
            finding_ids = (qa.artifact_id, review.artifact_id)
        self.repository.record_attempt(self.task.id, 2)
        self._event(
            TaskStatus.IMPLEMENTING,
            "review_rejected_route_to_coder" if reviewer else "qa_failed_route_to_coder",
            (finding_ids[-1],),
            source=candidate,
        )
        self.activate(2)
        return finding_ids


@pytest.fixture
def work_limit() -> int:
    return 5


@pytest.fixture
def transient_limit() -> int:
    return 5


@pytest.fixture
def denied_paths() -> tuple[str, ...]:
    return ()


@pytest.fixture
def v2_fixture(
    tmp_path: Path, work_limit: int, transient_limit: int, denied_paths: tuple[str, ...]
) -> Iterator[V2Fixture]:
    fd = os.open(tmp_path / "v2-task.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    value = V2Fixture(
        tmp_path,
        Guard(fd),
        work_limit=work_limit,
        transient_limit=transient_limit,
        denied_paths=denied_paths,
    )
    try:
        yield value
    finally:
        value.repository.close()
        os.close(fd)


def test_two_interruptions_keep_branch_draft_and_distinct_immutable_lineage(
    v2_fixture: V2Fixture,
) -> None:
    f = v2_fixture
    service = f.service()
    first = f.interrupt(service)
    assert f.reserve(service) == 2
    f.activate(2)
    service = f.service()
    assert service.prepare(f.request, f.worktree.path) is not None
    admission = f.store.admission_for_run(f.request.run_id)
    assert admission is not None
    # No new write: inherited dirty draft still needs a new stopped receipt,
    # rather than being misclassified as a clean provider retry or violation.
    second = f.interrupt(service, text=None, provider=True)
    assert second.mutation_paths == ()
    assert second.previous_admission_sha256 == admission.admission_sha256
    assert f.reserve(service) == 3
    f.activate(3)
    service = f.service()
    assert service.prepare(f.request, f.worktree.path) is not None
    before = service.started(f.request, f.worktree.path)
    assert before is not None
    (f.worktree.path / "src/app.py").write_text("VALUE = 3\n")
    service.finished(f.request, f.worktree.path, before=before)
    receipts = f.store.receipts_for_task(f.task.id)
    admissions = f.store.admissions_for_task(f.task.id)
    assert receipts == (first, second)
    assert len(admissions) == 2
    assert len({item.new_request.run_id for item in admissions}) == 2
    assert len({item.new_request.context_manifest_id for item in admissions}) == 2
    assert len({item.next_lease_id for item in admissions}) == 2
    assert len({item.next_work_item_id for item in admissions}) == 2
    assert _git(f.worktree.path, "branch", "--show-current") == f.worktree.branch
    assert _git(f.worktree.path, "rev-parse", "HEAD") == f.task.base_ref
    assert f.repository.get(f.task.id).work_attempt == 2
    assert f.repository.get(f.task.id).transient_failures(AgentRole.CODER) == 1
    assert not (f.store_root / "receipt.json").exists()
    assert not (f.store_root / "admission.json").exists()


def test_progress_then_interruption_retains_exact_progress_input(v2_fixture: V2Fixture) -> None:
    f = v2_fixture
    progress_id = f.progress()
    before_events = f.repository.list_events(f.task.id)
    service = f.service()
    receipt = f.interrupt(service, text="VALUE = 3\n", provider=True)
    assert receipt.request.continuation_checkpoint_id == progress_id
    assert receipt.request.continuation_changed_paths == ("src/app.py",)
    assert f.reserve(service) == 3
    f.activate(3)
    prompt = f.service().prepare(f.request, f.worktree.path)
    assert prompt is not None and "VALUE = 3" in prompt
    admission = f.store.admission_for_run(f.request.run_id)
    assert admission is not None and admission.new_request.continuation_checkpoint_id == progress_id
    assert admission.new_request.input_artifact_ids == ("art_plan_001", progress_id)
    assert f.repository.list_events(f.task.id) == before_events
    assert f.repository.get(f.task.id).work_attempt == 2


@pytest.mark.parametrize("reviewer", [False, True])
def test_feedback_coder_interruption_consumes_exact_sealed_findings(
    v2_fixture: V2Fixture, reviewer: bool
) -> None:
    f = v2_fixture
    findings = f.feedback(reviewer=reviewer)
    candidate = f.request.source_revision
    assert candidate != f.task.base_ref
    artifact_bytes = {
        path.name: path.read_bytes()
        for path in (f.store_root.parent / "accepted-artifacts").iterdir()
    }
    before_events = f.repository.list_events(f.task.id)
    service = f.service()
    receipt = f.interrupt(service, text="VALUE = 3\n", provider=True)
    assert receipt.request.input_artifact_ids == ("art_plan_001", *findings)
    assert receipt.request.expected_supersedes_by_kind == {
        ArtifactKind.CODER_PROGRESS: None,
        ArtifactKind.IMPLEMENTATION_REPORT: "art_impl_001",
    }
    assert f.reserve(service) == 3
    f.activate(3)
    assert f.service().prepare(f.request, f.worktree.path) is not None
    admission = f.store.admission_for_run(f.request.run_id)
    assert admission is not None and admission.new_request.source_revision == candidate
    assert admission.new_request.input_artifact_ids == receipt.request.input_artifact_ids
    assert f.repository.list_events(f.task.id) == before_events
    assert {
        path.name: path.read_bytes()
        for path in (f.store_root.parent / "accepted-artifacts").iterdir()
    } == artifact_bytes
    producer_ids = {
        artifact.producer.role: artifact.producer.agent_id
        for artifact in f.artifacts.list_for_task(f.task.id)
    }
    assert len(set(producer_ids.values())) == len(producer_ids)


@pytest.mark.parametrize("problem", ["drop_feedback", "supersedes", "source", "progress_paths"])
def test_replacement_refuses_changed_current_feedback_or_progress(
    v2_fixture: V2Fixture, problem: str
) -> None:
    f = v2_fixture
    if problem == "progress_paths":
        f.progress()
    else:
        f.feedback(reviewer=True)
    service = f.service()
    f.interrupt(service, text="VALUE = 3\n", provider=True)
    expected = f.request.attempt + 1
    assert f.reserve(service) == expected
    request = f.activate(expected)
    if problem == "drop_feedback":
        request = request.model_copy(update={"input_artifact_ids": ("art_plan_001",)})
    elif problem == "supersedes":
        request = request.model_copy(
            update={
                "expected_supersedes_by_kind": {
                    ArtifactKind.CODER_PROGRESS: None,
                    ArtifactKind.IMPLEMENTATION_REPORT: None,
                }
            }
        )
    elif problem == "source":
        request = request.model_copy(update={"source_revision": f.task.base_ref})
    else:
        request = request.model_copy(update={"continuation_changed_paths": ()})
    with pytest.raises(ContinuationRejected):
        f.service().prepare(request, f.worktree.path)
    assert f.store.admission_for_run(request.run_id) is None


@pytest.mark.parametrize("provider", [False, True])
@pytest.mark.parametrize("budget_committed", [False, True])
def test_second_receipt_budget_replay_after_restart_is_exact_once(
    v2_fixture: V2Fixture, provider: bool, budget_committed: bool
) -> None:
    f = v2_fixture
    service = f.service()
    f.interrupt(service)
    assert f.reserve(service) == 2
    f.activate(2)
    service = f.service()
    assert service.prepare(f.request, f.worktree.path) is not None
    f.interrupt(service, text="VALUE = 3\n", provider=provider)
    immutable = {path.name: path.read_bytes() for path in f.store_root.iterdir()}
    events = f.repository.list_events(f.task.id)
    if budget_committed:
        assert f.reserve(service) == 3
    f.restart()
    _reclaim(f)
    for _ in range(2):
        assert f.service().resume(f.repository.get(f.task.id), f.repository) == 3
    current = f.repository.get(f.task.id)
    assert current.attempts == 3
    assert current.work_attempt == (2 if provider else 3)
    assert current.transient_failures(AgentRole.CODER) == int(provider)
    assert f.repository.list_events(f.task.id) == events
    assert {path.name: path.read_bytes() for path in f.store_root.iterdir()} == immutable
    assert len(f.store.receipts_for_task(f.task.id)) == 2
    assert len(f.store.admissions_for_task(f.task.id)) == 1


def test_persisted_admission_unknown_invocation_waits_without_rebind_or_free_attempt(
    v2_fixture: V2Fixture,
) -> None:
    f = v2_fixture
    service = f.service()
    f.interrupt(service)
    assert f.reserve(service) == 2
    f.activate(2)
    assert f.service().prepare(f.request, f.worktree.path) is not None
    immutable = {path.name: path.read_bytes() for path in f.store_root.iterdir()}
    events = f.repository.list_events(f.task.id)
    f.restart()
    with pytest.raises(ContinuationExecutionUncertain):
        f.service().prepare(f.request, f.worktree.path)
    _reclaim(f)
    with pytest.raises(ContinuationExecutionUncertain):
        f.service().prepare(f.request, f.worktree.path)
    assert f.repository.get(f.task.id).status is TaskStatus.IMPLEMENTING
    assert f.repository.get(f.task.id).attempts == 2
    assert f.repository.list_events(f.task.id) == events
    assert {path.name: path.read_bytes() for path in f.store_root.iterdir()} == immutable


@pytest.mark.parametrize("transient_limit", [2])
def test_second_provider_failure_exhaustion_is_preserved_and_idempotent(
    v2_fixture: V2Fixture,
) -> None:
    f = v2_fixture
    service = f.service()
    f.interrupt(service, provider=True)
    assert f.reserve(service) == 2
    f.activate(2)
    service = f.service()
    assert service.prepare(f.request, f.worktree.path) is not None
    f.interrupt(service, text=None, provider=True)
    for _ in range(2):
        assert f.reserve(service) is None
    f.restart()
    _reclaim(f)
    with pytest.raises(InterruptionBudgetExhausted):
        f.service().resume(f.repository.get(f.task.id), f.repository)
    current = f.repository.get(f.task.id)
    assert current.attempts == 2 and current.work_attempt == 1
    assert current.transient_failures(AgentRole.CODER) == 2
    assert len(f.store.admissions_for_task(f.task.id)) == 1


@pytest.mark.parametrize("change", ["deleted", "rename", "mode"])
def test_common_mutations_continue_same_checkout_with_complete_bodies(
    v2_fixture: V2Fixture, change: str
) -> None:
    f = v2_fixture
    service = f.service()
    root = f.worktree.path
    before = service.started(f.request, root)
    assert before is not None
    source = root / "src/app.py"
    if change == "deleted":
        source.unlink()
    elif change == "rename":
        source.rename(root / "src/renamed.py")
    else:
        source.chmod(0o755)
    assert (
        service.interrupted(
            f.request,
            root,
            before=before,
            cause="local_execution_limit",
            original_error_code=AgentErrorCode.TIMEOUT,
            process_stop=f.stopped(),
            output_present=False,
        )
        is InterruptionObservation.CAPTURED
    )
    receipt = f.store.get_receipt(f.request.run_id)
    assert isinstance(receipt.capture, CapturedMutations)
    if change == "deleted":
        assert (
            receipt.capture.mutations[0].before is not None
            and receipt.capture.mutations[0].after is None
        )
    elif change == "rename":
        assert receipt.capture.to_capture().changed_paths == ("src/app.py", "src/renamed.py")
        assert (
            receipt.capture.mutations[0].after is None
            and receipt.capture.mutations[1].before is None
        )
    else:
        mutation = receipt.capture.mutations[0]
        assert mutation.before is not None and mutation.after is not None
        assert (mutation.before.mode, mutation.after.mode) == (0o644, 0o755)
    assert f.reserve(service) == 2
    f.activate(2)
    assert f.service().prepare(f.request, root) is not None
    assert _git(root, "rev-parse", "HEAD") == f.task.base_ref


@pytest.mark.parametrize("denied_paths", [("src/app.py",)])
def test_deleted_denied_path_is_a_real_policy_refusal_without_receipt(
    v2_fixture: V2Fixture,
) -> None:
    f = v2_fixture
    service = f.service()
    before = service.started(f.request, f.worktree.path)
    assert before is not None
    (f.worktree.path / "src/app.py").unlink()
    with pytest.raises(WorkspacePolicyError):
        service.interrupted(
            f.request,
            f.worktree.path,
            before=before,
            cause="local_execution_limit",
            original_error_code=AgentErrorCode.TIMEOUT,
            process_stop=f.stopped(),
            output_present=False,
        )
    assert f.store.receipts_for_task(f.task.id) == ()
    assert f.repository.get(f.task.id).attempts == 1
