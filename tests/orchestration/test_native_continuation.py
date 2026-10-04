"""Native continuation uses real Git and durable accounting without a MySQL dependency."""

import fcntl
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.continuation import (
    InterruptionBudgetExhausted,
    InterruptionObservation,
)
from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    BrainTier,
    ModelRouteReason,
    NetworkAccess,
    RiskTier,
    Task,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.continuation import InterruptionContinuationPolicy
from ai_software_engineer.domain.retry_policy import (
    DeliveryRetryFailure,
    DeliveryRetryPolicy,
    TransientRetryPolicy,
)
from ai_software_engineer.domain.task import TaskConstraints
from ai_software_engineer.domain.workforce import ModelSelection, RoleAssignment, TaskLease
from ai_software_engineer.git import (
    GitWorktreeManager,
    WorkspacePolicyError,
    WorktreeSpec,
)
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.store import SqliteTaskRepository
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from tests.domain.factories import make_task
from tests.git.test_worktree import _create_fixture_repository, _git
from tests.orchestration.test_continuation_records import make_receipt

NOW = datetime(2026, 10, 4, 13, tzinfo=UTC)


class Guard:
    def __init__(self, fd: int) -> None:
        self.inherited_fds: tuple[int, ...] = (fd,)
        self.live = True

    def check(self) -> None:
        if not self.live:
            raise ContinuationRejected("lost fixture claim")

    @contextmanager
    def write_scope(self) -> Iterator[None]:
        self.check()
        yield
        self.check()


def claim(task: Task, attempt: int) -> QueueClaim:
    assignment = RoleAssignment(
        id=f"assignment_native_{attempt}",
        repository_id="repository_continuation",
        task_id=task.id,
        agent_id="agent_native_coder",
        role=AgentRole.CODER,
        attempt=attempt,
        lease_id=f"lease_native_{attempt}",
        assigned_at=NOW,
    )
    return QueueClaim(
        work_item=QueuedWorkItem(
            id=f"work_native_{attempt}",
            task_id=task.id,
            repository_id=assignment.repository_id,
            role=AgentRole.CODER,
            attempt=attempt,
            repository_scopes=(task.repository,),
            parent_work_item_id="work_native_1" if attempt == 2 else None,
            status=WorkItemStatus.LEASED,
            priority=500,
            risk=RiskTier.NORMAL,
            created_at=NOW,
            updated_at=NOW,
        ),
        assignment=assignment,
        lease=TaskLease(
            id=assignment.lease_id,
            assignment_id=assignment.id,
            task_id=task.id,
            agent_id=assignment.agent_id,
            acquired_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        ),
        model_selection=ModelSelection(
            policy_id="model_policy_native",
            policy_version="v1",
            provider="codex",
            model="gpt-6.1-sol",
            tier=BrainTier.STANDARD,
            reasons=(ModelRouteReason.DEFAULT,),
            selected_at=NOW,
        ),
        worker_id=f"worker_native_{attempt}",
        claimed_at=NOW,
    )


class Fixture:
    def __init__(
        self,
        root: Path,
        guard: Guard,
        *,
        coder_transient_limit: int = 5,
        denied_paths: tuple[str, ...] = (),
    ) -> None:
        repository = _create_fixture_repository(root)
        _git(repository, "config", "user.name", "Fixture")
        (repository / ".gitignore").write_text("ignored.tmp\n.pytest_cache/\n")
        _git(repository, "add", ".gitignore")
        _git(repository, "commit", "-m", "inventory ignore fixture")
        policy = DeliveryRetryPolicy(
            coder=TransientRetryPolicy(max_transient_failures=coder_transient_limit)
        )
        original = make_task()
        self.task = Task.model_validate(
            {
                **original.to_wire(),
                "id": "task_continuation_001",
                "repository": str(repository),
                "base_ref": _git(repository, "rev-parse", "HEAD"),
                "max_attempts": policy.execution_limit,
                "retry_policy": policy.to_wire(),
                "interruption_continuation_policy": InterruptionContinuationPolicy().to_wire(),
                "constraints": TaskConstraints(
                    allowed_paths=("src/**",),
                    denied_paths=denied_paths,
                    max_attempts=policy.execution_limit,
                ).to_wire(),
            }
        )
        self.repository = SqliteTaskRepository(root / "tasks.sqlite")
        self.repository.create(self.task)
        self.repository.record_attempt(self.task.id, 1)
        for status, reason in (
            (TaskStatus.PLANNING, "task_validated"),
            (TaskStatus.IMPLEMENTING, "plan_validated"),
        ):
            current = self.repository.get(self.task.id)
            self.repository.append_event(
                build_event(
                    current,
                    status,
                    event_id=f"evt_native_{status.value.lower()}",
                    reason=reason,
                    source_revision=self.task.base_ref,
                    artifact_ids=("art_plan_001",) if status is TaskStatus.IMPLEMENTING else (),
                    occurred_at=current.updated_at + timedelta(seconds=1),
                )
            )
        self.git = GitWorktreeManager(repository, root / "worktrees")
        self.worktree = self.git.create(
            WorktreeSpec(
                task_id=self.task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=self.task.base_ref,
            )
        )
        self.request = AgentRequest(
            run_id="run_native_first",
            task_id=self.task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=self.task.base_ref,
            context_manifest_id="ctx_" + "1" * 64,
            input_artifact_ids=("art_plan_001",),
            permissions=AgentPermissions(
                read_paths=("src/**",),
                write_paths=("src/**",),
                commands=("pytest",),
                network=NetworkAccess.NONE,
            ),
            output_schema="schemas/coder-output.schema.json",
            timeout_seconds=1800,
        )
        self.claim = claim(self.task, 1)
        self.accepted_output = False
        self.guard = guard
        self.scope = make_receipt(root).scope
        self.store_root = root / self.task.id
        self.store = FileContinuationStore.initialize(self.store_root, task_id=self.task.id)

    def service(self) -> NativeCoderContinuation:
        return NativeCoderContinuation(
            scope=self.scope,
            store=self.store,
            git_workspace=self.git,
            guard=self.guard,
            current_task=lambda: self.repository.get(self.task.id),
            current_revision=lambda: self.repository.current_revision(self.task.id),
            claim=lambda: self.claim,
            has_accepted_output=lambda: self.accepted_output,
            clock=lambda: NOW,
        )

    def stopped(self, *, local: bool = True) -> NativeProcessStop:
        # Synthetic typed fixture with a genuinely stopped test-owned session;
        # production provenance is exercised by the owned-runner integration.
        process = subprocess.Popen(
            (sys.executable, "-c", "raise SystemExit(7)"), start_new_session=True
        )
        returncode = process.wait(timeout=5)
        return NativeProcessStop.create(
            process_id=process.pid,
            group_id=process.pid,
            returncode=returncode,
            kind="local_execution_limit" if local else "failed",
            stopped_at=NOW - timedelta(seconds=1),
        )

    def result(self) -> AgentResult:
        return AgentResult(
            run_id=self.request.run_id,
            task_id=self.request.task_id,
            role=self.request.role,
            attempt=self.request.attempt,
            source_revision=self.request.source_revision,
            context_manifest_id=self.request.context_manifest_id,
            status=AgentRunStatus.FAILED,
            error=AgentFailure(
                code=AgentErrorCode.WORK_INTERRUPTED, message="草稿已保留。", transient=False
            ),
        )


@pytest.fixture
def coder_transient_limit() -> int:
    return 5


@pytest.fixture
def denied_paths() -> tuple[str, ...]:
    return ()


@pytest.fixture
def fixture(
    tmp_path: Path, coder_transient_limit: int, denied_paths: tuple[str, ...]
) -> Iterator[Fixture]:
    fd = os.open(tmp_path / "task.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    value = Fixture(
        tmp_path, Guard(fd), coder_transient_limit=coder_transient_limit, denied_paths=denied_paths
    )
    try:
        yield value
    finally:
        value.repository.close()
        os.close(fd)


def test_stopped_legal_draft_continues_same_task_branch_with_one_work_charge(
    fixture: Fixture,
) -> None:
    service = fixture.service()
    request, root = fixture.request, fixture.worktree.path
    assert service.prepare(request, root) is None
    before = service.started(request, root)
    assert before is not None
    (root / "src/app.py").write_text("VALUE = 2\n")
    assert (
        service.interrupted(
            request,
            root,
            before=before,
            cause="local_execution_limit",
            original_error_code=AgentErrorCode.TIMEOUT,
            process_stop=fixture.stopped(),
            output_present=False,
        )
        is InterruptionObservation.CAPTURED
    )
    original_events = fixture.repository.list_events(fixture.task.id)
    assert (
        service.next_attempt(
            fixture.repository.get(fixture.task.id), fixture.result(), fixture.repository
        )
        == 2
    )
    assert (
        service.next_attempt(
            fixture.repository.get(fixture.task.id), fixture.result(), fixture.repository
        )
        == 2
    )
    current = fixture.repository.get(fixture.task.id)
    assert current.work_attempt == 2
    assert current.status is TaskStatus.IMPLEMENTING
    assert fixture.repository.list_events(current.id) == original_events
    fixture.claim = claim(current, 2)
    replacement = request.model_copy(
        update={
            "attempt": 2,
            "run_id": "run_native_replacement",
            "context_manifest_id": "ctx_" + "2" * 64,
        }
    )
    reopened = fixture.service()
    prompt = reopened.prepare(replacement, root)
    assert prompt is not None and "VALUE = 2" in prompt
    admission = fixture.store.get_admission(current.id)
    assert admission.new_request == replacement
    assert admission.next_lease_id != fixture.store.get_receipt(request.run_id).claim_lease_id
    assert _git(root, "branch", "--show-current") == fixture.worktree.branch
    assert _git(root, "rev-parse", "HEAD") == fixture.task.base_ref
    assert reopened.prepare(replacement, root) == prompt
    with pytest.raises(ContinuationRejected):
        reopened.prepare(replacement.model_copy(update={"run_id": "run_native_duplicate"}), root)


def test_provider_interruption_accounts_transient_once_without_refunding_local_work(
    fixture: Fixture,
) -> None:
    service = fixture.service()
    root = fixture.worktree.path
    before = service.started(fixture.request, root)
    assert before is not None
    (root / "src/app.py").write_text("VALUE = 2\n")
    assert (
        service.interrupted(
            fixture.request,
            root,
            before=before,
            cause="provider_transient",
            original_error_code=AgentErrorCode.PROVIDER_UNAVAILABLE,
            process_stop=fixture.stopped(local=False),
            output_present=False,
        )
        is InterruptionObservation.CAPTURED
    )
    for _ in range(2):
        assert (
            service.next_attempt(
                fixture.repository.get(fixture.task.id), fixture.result(), fixture.repository
            )
            == 2
        )
    current = fixture.repository.get(fixture.task.id)
    assert current.work_attempt == 1
    assert current.transient_failures(AgentRole.CODER) == 1


@pytest.mark.parametrize("coder_transient_limit", [1, 2])
@pytest.mark.parametrize("crash_after_commit", [False, True])
def test_provider_failure_is_sealed_even_when_no_successor_is_available(
    fixture: Fixture,
    coder_transient_limit: int,
    crash_after_commit: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = fixture.service()
    root = fixture.worktree.path
    before = service.started(fixture.request, root)
    assert before is not None
    (root / "src/app.py").write_text("VALUE = 2\n")
    assert (
        service.interrupted(
            fixture.request,
            root,
            before=before,
            cause="provider_transient",
            original_error_code=AgentErrorCode.PROVIDER_UNAVAILABLE,
            process_stop=fixture.stopped(local=False),
            output_present=False,
        )
        is InterruptionObservation.CAPTURED
    )
    original_events = fixture.repository.list_events(fixture.task.id)
    original_record = fixture.repository.record_retry_failure

    def interrupted_commit(task_id: str, failure: DeliveryRetryFailure) -> None:
        original_record(task_id, failure)
        raise RuntimeError("fixture crash after committed retry fact")

    expected_attempt = None if coder_transient_limit == 1 else 2
    if crash_after_commit:
        monkeypatch.setattr(fixture.repository, "record_retry_failure", interrupted_commit)
        with pytest.raises(RuntimeError, match="crash after committed retry fact"):
            service.next_attempt(
                fixture.repository.get(fixture.task.id), fixture.result(), fixture.repository
            )
        monkeypatch.setattr(fixture.repository, "record_retry_failure", original_record)
        # Reopen both the Task store and continuation service after the sealed
        # fact, reproducing the crash window before queue publication.
        fixture.repository.close()
        fixture.repository = SqliteTaskRepository(fixture.store_root.parent / "tasks.sqlite")
        service = fixture.service()
    for _ in range(2):
        assert (
            service.next_attempt(
                fixture.repository.get(fixture.task.id), fixture.result(), fixture.repository
            )
            == expected_attempt
        )
    current = fixture.repository.get(fixture.task.id)
    assert current.attempts == (1 if expected_attempt is None else 2)
    assert current.work_attempt == 1
    assert current.retry_failures == (
        DeliveryRetryFailure(
            role=AgentRole.CODER,
            attempt=1,
            code="PROVIDER_UNAVAILABLE",
            run_id=fixture.request.run_id,
        ),
    )
    assert current.status is TaskStatus.IMPLEMENTING
    assert fixture.repository.list_events(current.id) == original_events
    assert fixture.store.receipt_for_task(current.id) is not None
    assert not (fixture.store_root / "admission.json").exists()
    assert (root / "src/app.py").read_text() == "VALUE = 2\n"
    if expected_attempt is None:
        fixture.claim = claim(current, 2)
        unreserved = fixture.request.model_copy(
            update={
                "attempt": 2,
                "run_id": "run_native_unreserved",
                "context_manifest_id": "ctx_" + "2" * 64,
            }
        )
        with pytest.raises(ContinuationRejected):
            service.prepare(unreserved, root)
        assert not (fixture.store_root / "admission.json").exists()


@pytest.mark.parametrize(
    "problem", ["missing_stop", "unknown_output", "accepted_output", "ignored"]
)
def test_uncertain_results_are_preserved_without_auto_admission(
    fixture: Fixture, problem: str
) -> None:
    service = fixture.service()
    root = fixture.worktree.path
    before = service.started(fixture.request, root)
    assert before is not None
    (root / "src/app.py").write_text("VALUE = 2\n")
    if problem == "ignored":
        (root / "ignored.tmp").write_text("ignored draft\n")
        fixture.request = fixture.request.model_copy(
            update={
                "permissions": fixture.request.permissions.model_copy(
                    update={"read_paths": ("**",), "write_paths": ("**",)}
                )
            }
        )
    fixture.accepted_output = problem == "accepted_output"
    assert (
        service.interrupted(
            fixture.request,
            root,
            before=before,
            cause="local_execution_limit",
            original_error_code=AgentErrorCode.TIMEOUT,
            process_stop=None if problem == "missing_stop" else fixture.stopped(),
            output_present=problem == "unknown_output",
        )
        is InterruptionObservation.PRESERVED
    )
    assert fixture.store.receipt_for_task(fixture.task.id) is None
    assert (root / "src/app.py").read_text() == "VALUE = 2\n"
    assert fixture.repository.get(fixture.task.id).attempts == 1


def test_true_write_violation_remains_policy_failure(fixture: Fixture) -> None:
    service = fixture.service()
    root = fixture.worktree.path
    before = service.started(fixture.request, root)
    assert before is not None
    (root / "README.md").write_text("unauthorized edit\n")
    with pytest.raises(WorkspacePolicyError):
        service.interrupted(
            fixture.request,
            root,
            before=before,
            cause="local_execution_limit",
            original_error_code=AgentErrorCode.TIMEOUT,
            process_stop=fixture.stopped(),
            output_present=False,
        )
    assert fixture.store.receipt_for_task(fixture.task.id) is None


@pytest.mark.parametrize("problem", ["draft_drift", "lease_alias", "permission_drift", "terminal"])
def test_replacement_rechecks_current_facts_before_consuming_admission(
    fixture: Fixture, problem: str
) -> None:
    service = fixture.service()
    root = fixture.worktree.path
    before = service.started(fixture.request, root)
    assert before is not None
    (root / "src/app.py").write_text("VALUE = 2\n")
    assert (
        service.interrupted(
            fixture.request,
            root,
            before=before,
            cause="local_execution_limit",
            original_error_code=AgentErrorCode.TIMEOUT,
            process_stop=fixture.stopped(),
            output_present=False,
        )
        is InterruptionObservation.CAPTURED
    )
    assert (
        service.next_attempt(
            fixture.repository.get(fixture.task.id), fixture.result(), fixture.repository
        )
        == 2
    )
    fixture.claim = claim(fixture.task, 2)
    replacement = fixture.request.model_copy(
        update={
            "attempt": 2,
            "run_id": "run_native_replacement",
            "context_manifest_id": "ctx_" + "2" * 64,
        }
    )
    if problem == "draft_drift":
        (root / "src/app.py").write_text("VALUE = 3\n")
    elif problem == "lease_alias":
        fixture.claim = claim(fixture.task, 1)
    elif problem == "permission_drift":
        replacement = replacement.model_copy(
            update={
                "permissions": replacement.permissions.model_copy(update={"write_paths": ("**",)})
            }
        )
    else:
        task = fixture.repository.get(fixture.task.id)
        fixture.repository.append_event(
            build_event(
                task,
                TaskStatus.BLOCKED,
                event_id="evt_native_terminal",
                reason="explicit_terminal",
                source_revision=task.base_ref,
                occurred_at=task.updated_at + timedelta(seconds=1),
            )
        )
    with pytest.raises(ContinuationRejected):
        fixture.service().prepare(replacement, root)
    assert not (fixture.store_root / "admission.json").exists()


@pytest.mark.parametrize(
    ("changed_path", "denied_paths", "allowed"),
    [
        ("src/app.py", (), True),
        ("ignored.tmp", (), False),
        (".pytest_cache/protected", (".pytest_cache/**",), False),
        (".trellis/ignored", (), False),
    ],
)
def test_finished_validates_complete_native_inventory_before_candidate(
    fixture: Fixture, changed_path: str, allowed: bool
) -> None:
    service = fixture.service()
    root = fixture.worktree.path
    before = service.started(fixture.request, root)
    assert before is not None
    destination = root / changed_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("native mutation\n")
    if allowed:
        service.finished(fixture.request, root, before=before)
    else:
        with pytest.raises(WorkspacePolicyError):
            service.finished(fixture.request, root, before=before)
    assert _git(root, "rev-parse", "HEAD") == fixture.task.base_ref
    assert destination.read_text() == "native mutation\n"
    assert fixture.store.receipt_for_task(fixture.task.id) is None


@pytest.mark.parametrize("problem", ["missing_before", "wrong_before", "native_commit"])
def test_finished_refuses_unverified_or_committed_native_output(
    fixture: Fixture, problem: str
) -> None:
    service = fixture.service()
    root = fixture.worktree.path
    before = service.started(fixture.request, root)
    assert before is not None
    (root / "src/app.py").write_text("VALUE = 2\n")
    if problem == "missing_before":
        before = None
    elif problem == "wrong_before":
        before = type(before)(files=())
    else:
        _git(root, "add", "src/app.py")
        _git(root, "commit", "-m", "forbidden native commit fixture")
    with pytest.raises(ContinuationRejected):
        service.finished(fixture.request, root, before=before)


def _seal_draft(fixture: Fixture, *, provider: bool = False) -> None:
    service = fixture.service()
    root = fixture.worktree.path
    before = service.started(fixture.request, root)
    assert before is not None
    (root / "src/app.py").write_text("VALUE = 2\n")
    assert (
        service.interrupted(
            fixture.request,
            root,
            before=before,
            cause="provider_transient" if provider else "local_execution_limit",
            original_error_code=(
                AgentErrorCode.PROVIDER_UNAVAILABLE if provider else AgentErrorCode.TIMEOUT
            ),
            process_stop=fixture.stopped(local=not provider),
            output_present=False,
        )
        is InterruptionObservation.CAPTURED
    )


def _reclaim(fixture: Fixture) -> None:
    original = fixture.claim
    lease_id = "lease_native_reclaimed"
    fixture.claim = QueueClaim.model_validate(
        {
            **original.to_wire(),
            "assignment": original.assignment.model_copy(update={"lease_id": lease_id}).to_wire(),
            "lease": original.lease.model_copy(update={"id": lease_id}).to_wire(),
            "worker_id": "worker_native_reclaimed",
        }
    )


@pytest.mark.parametrize("provider", [False, True])
@pytest.mark.parametrize("budget_committed", [False, True])
def test_reclaimed_original_work_item_replays_receipt_without_model_or_double_charge(
    fixture: Fixture, provider: bool, budget_committed: bool
) -> None:
    _seal_draft(fixture, provider=provider)
    if budget_committed:
        assert (
            fixture.service().next_attempt(
                fixture.repository.get(fixture.task.id), fixture.result(), fixture.repository
            )
            == 2
        )
    fixture.repository.close()
    fixture.repository = SqliteTaskRepository(fixture.store_root.parent / "tasks.sqlite")
    _reclaim(fixture)
    service = fixture.service()
    for _ in range(2):
        assert service.resume(fixture.repository.get(fixture.task.id), fixture.repository) == 2
    current = fixture.repository.get(fixture.task.id)
    receipt = fixture.store.receipt_for_task(current.id)
    assert receipt is not None
    assert receipt.original_work_item_id == fixture.claim.work_item.id
    assert receipt.claim_lease_id != fixture.claim.lease.id
    assert current.attempts == 2
    assert current.work_attempt == (1 if provider else 2)
    assert current.transient_failures(AgentRole.CODER) == int(provider)
    assert not (fixture.store_root / "admission.json").exists()
    assert (fixture.worktree.path / "src/app.py").read_text() == "VALUE = 2\n"


@pytest.mark.parametrize("problem", ["wrong_item", "accepted_output", "draft_drift", "no_lock"])
def test_reclaimed_receipt_refuses_drift_instead_of_repeating_original_coder(
    fixture: Fixture, problem: str
) -> None:
    _seal_draft(fixture)
    _reclaim(fixture)
    if problem == "wrong_item":
        fixture.claim = fixture.claim.model_copy(
            update={"work_item": fixture.claim.work_item.model_copy(update={"id": "work_foreign"})}
        )
    elif problem == "accepted_output":
        fixture.accepted_output = True
    elif problem == "draft_drift":
        (fixture.worktree.path / "src/app.py").write_text("VALUE = 3\n")
    else:
        fixture.guard.inherited_fds = ()
    with pytest.raises(ContinuationRejected):
        fixture.service().resume(fixture.repository.get(fixture.task.id), fixture.repository)
    assert fixture.repository.get(fixture.task.id).attempts == 1
    assert not (fixture.store_root / "admission.json").exists()


@pytest.mark.parametrize("coder_transient_limit", [1])
def test_reclaimed_exhausted_provider_receipt_seals_failure_and_blocks_invocation(
    fixture: Fixture,
) -> None:
    _seal_draft(fixture, provider=True)
    _reclaim(fixture)
    for _ in range(2):
        with pytest.raises(InterruptionBudgetExhausted, match="budget"):
            fixture.service().resume(fixture.repository.get(fixture.task.id), fixture.repository)
    current = fixture.repository.get(fixture.task.id)
    assert current.attempts == 1
    assert current.transient_failures(AgentRole.CODER) == 1
    assert not (fixture.store_root / "admission.json").exists()


def test_published_admission_cannot_be_rebound_after_unknown_invocation_crash(
    fixture: Fixture,
) -> None:
    _seal_draft(fixture)
    service = fixture.service()
    assert (
        service.next_attempt(
            fixture.repository.get(fixture.task.id), fixture.result(), fixture.repository
        )
        == 2
    )
    fixture.claim = claim(fixture.task, 2)
    replacement = fixture.request.model_copy(
        update={
            "attempt": 2,
            "run_id": "run_native_replacement",
            "context_manifest_id": "ctx_" + "2" * 64,
        }
    )
    assert service.prepare(replacement, fixture.worktree.path) is not None
    admission_bytes = (fixture.store_root / "admission.json").read_bytes()
    _reclaim(fixture)
    with pytest.raises(ContinuationRejected):
        fixture.service().prepare(replacement, fixture.worktree.path)
    assert (fixture.store_root / "admission.json").read_bytes() == admission_bytes
    assert fixture.repository.get(fixture.task.id).attempts == 2
