"""A provider outage must not spend the Coder correction allowance."""

from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.domain import AgentRole, Task, TaskStatus
from ai_software_engineer.domain.retry_policy import (
    DeliveryRetryFailure,
    DeliveryRetryPolicy,
    TransientRetryPolicy,
)
from ai_software_engineer.orchestration import FileRunContextBuilder, RetryingOrchestrator
from ai_software_engineer.orchestration.steps import BoundedRunControl, RoleRunPending
from ai_software_engineer.store import SqliteTaskRepository, StoreError
from tests.orchestration.test_retry import AttemptIdentityFactory, ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions, _task


def budget_task(root: Path, policy: DeliveryRetryPolicy) -> Task:
    root.mkdir(exist_ok=True)
    original = _task(root)
    assert original.constraints is not None
    return original.model_copy(
        update={
            "retry_policy": policy,
            "max_attempts": policy.execution_limit,
            "constraints": original.constraints.model_copy(
                update={"max_attempts": policy.execution_limit}
            ),
        }
    )


class TemporaryFailureAdapter(ScriptedAdapter):
    def __init__(self, role: AgentRole, *, forever: bool = False) -> None:
        super().__init__(qa_failures=(2,))
        self.failed_role, self.forever = role, forever

    def run(self, request: AgentRequest) -> AgentResult:
        if request.role is self.failed_role and (self.forever or request.attempt == 1):
            self.requests.append(request)
            return AgentResult(
                run_id=request.run_id,
                task_id=request.task_id,
                role=request.role,
                attempt=request.attempt,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                status=AgentRunStatus.TIMED_OUT,
                error=AgentFailure(
                    code=AgentErrorCode.TIMEOUT, message="fixture outage", transient=True
                ),
            )
        result = super().run(request)
        if result.artifact is not None and request.role is AgentRole.CODER:
            candidate = f"{request.attempt:040x}"
            result = result.model_copy(
                update={
                    "artifact": result.artifact.model_copy(
                        update={
                            "source_revision": candidate,
                            "content": result.artifact.content.model_copy(
                                update={"commit_sha": candidate}
                            ),
                        }
                    )
                }
            )
        if result.artifact is not None and request.expected_supersedes_by_kind is not None:
            return result.model_copy(
                update={
                    "artifact": result.artifact.model_copy(
                        update={
                            "supersedes": request.expected_supersedes_by_kind[result.artifact.kind]
                        }
                    )
                }
            )
        return result


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_transient_does_not_spend_work_budget(tmp_path: Path, role: AgentRole) -> None:
    policy = DeliveryRetryPolicy(max_work_attempts=2)
    task = budget_task(tmp_path / "project", policy)
    adapter = TemporaryFailureAdapter(role)
    repository = SqliteTaskRepository(tmp_path / "state.sqlite")
    repository.create(task)
    runner = RetryingOrchestrator(
        repository=repository,
        artifact_store=FileArtifactStore(tmp_path / "artifacts"),
        context_builder=FileRunContextBuilder(Path(task.repository)),
        agent_adapter=adapter,
        agent_definitions=_definitions(),
        identities=AttemptIdentityFactory(),
        clock=_clock,
    )
    result = runner.run_task(task.id)
    assert result.task.status is TaskStatus.DONE
    assert result.task.transient_failures(role) == 1
    assert result.task.work_attempt <= 2


def test_retry_fact_is_atomic_idempotent_and_survives_restart(tmp_path: Path) -> None:
    policy = DeliveryRetryPolicy()
    task = budget_task(tmp_path, policy).model_copy(update={"status": TaskStatus.QA, "attempts": 1})
    path = tmp_path / "retry.sqlite"
    repository = SqliteTaskRepository(path)
    repository.create(task)
    failure = DeliveryRetryFailure(
        role=AgentRole.QA, attempt=1, code="TIMEOUT", run_id="run_qa_failed"
    )
    repository.record_retry_failure(task.id, failure)
    repository.record_retry_failure(task.id, failure)
    repository.close()
    reopened = SqliteTaskRepository(path)
    current = reopened.get(task.id)
    assert current.attempts == 2
    assert current.work_attempt == 1
    assert current.retry_failures == (failure,)
    with pytest.raises(StoreError, match="conflict"):
        reopened.record_retry_failure(task.id, failure.model_copy(update={"code": "RATE_LIMITED"}))
    assert reopened.get(task.id) == current
    reopened.close()


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_exhausted_failure_survives_crash_before_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: AgentRole,
) -> None:
    policy = DeliveryRetryPolicy.model_validate({role.value: {"max_transient_failures": 1}})
    task = budget_task(tmp_path / "project", policy)
    adapter = TemporaryFailureAdapter(role, forever=True)
    path = tmp_path / "state.sqlite"
    repository = SqliteTaskRepository(path)
    repository.create(task)
    record = repository.record_retry_failure

    def crash_after_commit(task_id: str, failure: DeliveryRetryFailure) -> None:
        record(task_id, failure)
        raise RuntimeError("fixture crash after durable failure")

    monkeypatch.setattr(repository, "record_retry_failure", crash_after_commit)
    artifacts = FileArtifactStore(tmp_path / "artifacts")

    def runner(store: SqliteTaskRepository) -> RetryingOrchestrator:
        return RetryingOrchestrator(
            repository=store,
            artifact_store=artifacts,
            context_builder=FileRunContextBuilder(Path(task.repository)),
            agent_adapter=adapter,
            agent_definitions=_definitions(),
            identities=AttemptIdentityFactory(),
            clock=_clock,
        )

    with pytest.raises(RuntimeError, match="fixture crash"):
        runner(repository).run_task(task.id)
    count = len(adapter.requests)
    repository.close()
    with SqliteTaskRepository(path) as reopened:
        result = runner(reopened).run_task(task.id)
        assert result.task.status is TaskStatus.BLOCKED
        assert result.task.transient_failures(role) == 1
        assert result.task.attempts == 1
        assert len(adapter.requests) == count, "restart cannot grant a free invocation"


def test_unknown_or_nontransient_failure_is_not_refunded(tmp_path: Path) -> None:
    class NonTransient(TemporaryFailureAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            result = super().run(request)
            if result.error is not None:
                return result.model_copy(
                    update={"error": result.error.model_copy(update={"transient": False})}
                )
            return result

    task = budget_task(tmp_path / "project", DeliveryRetryPolicy())
    with SqliteTaskRepository(tmp_path / "state.sqlite") as repository:
        repository.create(task)
        result = RetryingOrchestrator(
            repository=repository,
            artifact_store=FileArtifactStore(tmp_path / "artifacts"),
            context_builder=FileRunContextBuilder(Path(task.repository)),
            agent_adapter=NonTransient(AgentRole.CODER),
            agent_definitions=_definitions(),
            identities=AttemptIdentityFactory(),
            clock=_clock,
        ).run_task(task.id)
        assert result.task.status is TaskStatus.BLOCKED
        assert result.task.attempts == 1
        assert result.task.retry_failures is None


def test_maximum_policy_and_legacy_wire_compatibility(tmp_path: Path) -> None:
    limit = TransientRetryPolicy(max_transient_failures=100)
    policy = DeliveryRetryPolicy(max_work_attempts=100, coder=limit, qa=limit, reviewer=limit)
    task = budget_task(tmp_path, policy)
    assert Task.model_validate(task.to_wire()).max_attempts == 400
    legacy = _task(tmp_path).to_wire()
    assert "retry_policy" not in legacy and "retry_failures" not in legacy
    assert Task.model_validate(legacy).to_wire() == legacy


def test_separated_retry_requires_a_fresh_role_permit(tmp_path: Path) -> None:
    task = budget_task(tmp_path / "project", DeliveryRetryPolicy())
    adapter = TemporaryFailureAdapter(AgentRole.CODER)
    with SqliteTaskRepository(tmp_path / "state.sqlite") as repository:
        repository.create(task)
        runner = RetryingOrchestrator(
            repository=repository,
            artifact_store=FileArtifactStore(tmp_path / "artifacts"),
            context_builder=FileRunContextBuilder(Path(task.repository)),
            agent_adapter=adapter,
            agent_definitions=_definitions(),
            identities=AttemptIdentityFactory(),
            clock=_clock,
        )
        runner.execution_control = BoundedRunControl(repository)
        with pytest.raises(RoleRunPending) as first:
            runner.run_task(task.id)
        runner.execution_control = BoundedRunControl(repository, permit=first.value.boundary)
        with pytest.raises(RoleRunPending) as second:
            runner.run_task(task.id)
        assert second.value.boundary.attempt == 2
        assert second.value.boundary.role is AgentRole.CODER
        assert repository.get(task.id).work_attempt == 1
        assert sum(r.role is AgentRole.CODER for r in adapter.requests) == 1


@pytest.mark.parametrize("code", [AgentErrorCode.TIMEOUT, AgentErrorCode.INVALID_OUTPUT])
def test_knowledge_error_has_typed_budget_and_no_fabricated_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: AgentErrorCode,
) -> None:
    from ai_software_engineer.agents import StructuredModelError
    from ai_software_engineer.orchestration import BlockedResult, RetryClassification

    task = budget_task(tmp_path / "project", DeliveryRetryPolicy())
    adapter = TemporaryFailureAdapter(AgentRole.QA)
    builder = FileRunContextBuilder(Path(task.repository))
    build = builder.build
    failed = False

    def build_or_fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal failed
        if args[1].role is AgentRole.CODER and not failed:
            failed = True
            raise StructuredModelError(code, "fixture knowledge failure", transient=True)
        return build(*args, **kwargs)

    monkeypatch.setattr(builder, "build", build_or_fail)
    with SqliteTaskRepository(tmp_path / "state.sqlite") as repository:
        repository.create(task)
        result = RetryingOrchestrator(
            repository=repository,
            artifact_store=FileArtifactStore(tmp_path / "artifacts"),
            context_builder=builder,
            agent_adapter=adapter,
            agent_definitions=_definitions(),
            identities=AttemptIdentityFactory(),
            clock=_clock,
        ).run_task(task.id)
        if code is AgentErrorCode.TIMEOUT:
            assert result.task.status is TaskStatus.DONE
            assert result.task.retry_failures is not None
            assert result.task.retry_failures[0].run_id is None
        else:
            assert isinstance(result, BlockedResult)
            assert result.task.status is TaskStatus.BLOCKED
            assert result.classification is RetryClassification.INVALID_OUTPUT
            assert result.task.retry_failures is None
