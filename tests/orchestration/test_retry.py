"""T010 retry, routing and restart-recovery tests through public seams."""

from contextlib import suppress
from pathlib import Path

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.domain import (
    AgentRole,
    Artifact,
    ImplementationReportArtifact,
    QaReportStatus,
    Task,
    TaskStatus,
)
from ai_software_engineer.orchestration import (
    BlockedResult,
    FileRunContextBuilder,
    RetryDeliveryResult,
    RetryingOrchestrator,
    SerialOrchestrator,
    UnexpectedVerdict,
)
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import (
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
)
from tests.orchestration.test_runner import (
    FixedIdentityFactory,
    _clock,
    _definitions,
    _task,
)


class AttemptIdentityFactory(FixedIdentityFactory):
    """Identity fixture that gives every retry a distinct run identity."""

    def new_run_id(self, task_id: str, role: AgentRole, attempt: int) -> str:
        del task_id
        return f"run_{role.value}_{attempt:02d}"


class ScriptedAdapter:
    """Small deterministic adapter that materializes valid artifacts from each request."""

    def __init__(
        self,
        *,
        coder_timeouts: tuple[int, ...] = (),
        qa_failures: tuple[int, ...] = (),
    ) -> None:
        self.coder_timeouts = set(coder_timeouts)
        self.qa_failures = set(qa_failures)
        self.requests: list[AgentRequest] = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        if request.role is AgentRole.CODER and request.attempt in self.coder_timeouts:
            return AgentResult(
                run_id=request.run_id,
                task_id=request.task_id,
                role=request.role,
                attempt=request.attempt,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                status=AgentRunStatus.TIMED_OUT,
                error=AgentFailure(
                    code=AgentErrorCode.TIMEOUT,
                    message="simulated timeout",
                    transient=True,
                ),
            )
        artifact = self._artifact(request)
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=artifact,
        )

    def _artifact(self, request: AgentRequest) -> Artifact:
        if request.role is AgentRole.ORCHESTRATOR:
            return make_plan_artifact().model_copy(
                update={
                    "task_id": request.task_id,
                    "source_revision": request.source_revision,
                    "context_manifest_id": request.context_manifest_id,
                    "producer": make_plan_artifact().producer.model_copy(
                        update={"run_id": request.run_id}
                    ),
                }
            )
        if request.role is AgentRole.CODER:
            candidate = ("b" if request.attempt == 1 else "c") * 40
            previous = "art_impl_001" if len(request.input_artifact_ids) > 1 else None
            return make_implementation_artifact().model_copy(
                update={
                    "artifact_id": f"art_impl_{request.attempt:03d}",
                    "task_id": request.task_id,
                    "source_revision": candidate,
                    "context_manifest_id": request.context_manifest_id,
                    "parent_artifact_ids": request.input_artifact_ids,
                    "supersedes": previous,
                    "producer": make_implementation_artifact().producer.model_copy(
                        update={"run_id": request.run_id}
                    ),
                    "content": make_implementation_artifact().content.model_copy(
                        update={"commit_sha": candidate}
                    ),
                }
            )
        if request.role is AgentRole.QA:
            status = (
                QaReportStatus.FAIL if request.attempt in self.qa_failures else QaReportStatus.PASS
            )
            return make_qa_artifact().model_copy(
                update={
                    "artifact_id": f"art_qa_{request.attempt:03d}",
                    "task_id": request.task_id,
                    "source_revision": request.source_revision,
                    "context_manifest_id": request.context_manifest_id,
                    "parent_artifact_ids": (request.input_artifact_ids[1],),
                    "producer": make_qa_artifact().producer.model_copy(
                        update={"run_id": request.run_id}
                    ),
                    "content": make_qa_artifact().content.model_copy(update={"status": status}),
                }
            )
        return make_review_artifact().model_copy(
            update={
                "artifact_id": f"art_review_{request.attempt:03d}",
                "task_id": request.task_id,
                "source_revision": request.source_revision,
                "context_manifest_id": request.context_manifest_id,
                "parent_artifact_ids": (request.input_artifact_ids[2],),
                "producer": make_review_artifact().producer.model_copy(
                    update={"run_id": request.run_id}
                ),
            }
        )


def _runner(
    tmp_path: Path, adapter: ScriptedAdapter, *, max_attempts: int = 3
) -> tuple[Task, SqliteTaskRepository, RetryingOrchestrator]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    task = _task(project_root).model_copy(
        update={"max_attempts": max_attempts, "constraints": _task(project_root).constraints}
    )
    if max_attempts != 3:
        task = task.model_copy(
            update={
                "constraints": task.constraints.model_copy(update={"max_attempts": max_attempts})
                if task.constraints is not None
                else None
            }
        )
    repository = SqliteTaskRepository(tmp_path / "state.sqlite3")
    repository.create(task)
    return (
        task,
        repository,
        RetryingOrchestrator(
            repository=repository,
            artifact_store=FileArtifactStore(tmp_path / "artifacts"),
            context_builder=FileRunContextBuilder(project_root),
            agent_adapter=adapter,
            agent_definitions=_definitions(),
            identities=AttemptIdentityFactory(),
            clock=_clock,
        ),
    )


def test_transient_coder_timeout_retries_and_completes(tmp_path: Path) -> None:
    task, repository, runner = _runner(tmp_path, ScriptedAdapter(coder_timeouts=(1,)))
    try:
        result = runner.run_task(task.id)
        assert isinstance(result, RetryDeliveryResult)
        assert result.task.status is TaskStatus.DONE
        assert result.task.attempts == 2
        assert result.candidate_revision == "c" * 40
        assert result.artifact_ids == (
            "art_plan_001",
            "art_impl_002",
            "art_qa_002",
            "art_review_002",
        )
        assert tuple(event.attempt for event in repository.list_events(task.id)) == (1, 1, 2, 2, 2)
    finally:
        repository.close()


def test_qa_finding_routes_a_new_coder_with_superseding_lineage(tmp_path: Path) -> None:
    task, repository, runner = _runner(tmp_path, ScriptedAdapter(qa_failures=(1,)))
    try:
        result = runner.run_task(task.id)
        assert result.task.status is TaskStatus.DONE
        assert result.task.attempts == 2
        assert result.artifact_ids[1] == "art_impl_002"
        persisted = runner._artifact_store.list_for_task(task.id)
        retry_impl = next(item for item in persisted if item.artifact_id == "art_impl_002")
        assert isinstance(retry_impl, ImplementationReportArtifact)
        assert retry_impl.supersedes == "art_impl_001"
        assert retry_impl.parent_artifact_ids == ("art_plan_001", "art_qa_001")
        assert tuple(event.to_status for event in repository.list_events(task.id)) == (
            TaskStatus.PLANNING,
            TaskStatus.IMPLEMENTING,
            TaskStatus.QA,
            TaskStatus.IMPLEMENTING,
            TaskStatus.QA,
            TaskStatus.REVIEW,
            TaskStatus.DONE,
        )
    finally:
        repository.close()


def test_attempt_budget_exhaustion_returns_durable_blocked_result(tmp_path: Path) -> None:
    task, repository, runner = _runner(tmp_path, ScriptedAdapter(qa_failures=(1,)), max_attempts=1)
    try:
        result = runner.run_task(task.id)
        assert isinstance(result, BlockedResult)
        assert result.classification.value == "QA_FINDING"
        assert result.task.status is TaskStatus.BLOCKED
        assert repository.list_events(task.id)[-1].to_status is TaskStatus.BLOCKED
        assert repository.list_events(task.id)[-1].artifact_ids == ("art_qa_001",)
    finally:
        repository.close()


def test_restart_recovers_t009_qa_checkpoint_and_continues(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    task = _task(project_root)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    first_repository = SqliteTaskRepository(tmp_path / "state.sqlite3")
    first = SerialOrchestrator(
        repository=first_repository,
        artifact_store=artifacts,
        context_builder=FileRunContextBuilder(project_root),
        agent_adapter=ScriptedAdapter(qa_failures=(1,)),
        agent_definitions=_definitions(),
        identities=AttemptIdentityFactory(),
        clock=_clock,
    )
    try:
        first_repository.create(task)
        with suppress(UnexpectedVerdict):
            first.run_task(task.id)
    finally:
        first_repository.close()

    with SqliteTaskRepository(tmp_path / "state.sqlite3") as repository:
        adapter = ScriptedAdapter()
        runner = RetryingOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=FileRunContextBuilder(project_root),
            agent_adapter=adapter,
            agent_definitions=_definitions(),
            identities=AttemptIdentityFactory(),
            clock=_clock,
        )
        result = runner.run_task(task.id)
        assert result.task.status is TaskStatus.DONE
        assert result.task.attempts == 2
        assert adapter.requests[0].role is AgentRole.CODER
        assert adapter.requests[0].attempt == 2
