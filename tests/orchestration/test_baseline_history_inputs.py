"""Runtime consumers honor all retired inputs while retaining exact verifier findings."""

from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain.artifact import Artifact
from ai_software_engineer.domain.enums import ArtifactKind, QaReportStatus, TaskStatus
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    ExecutionBaselineBinding,
)
from ai_software_engineer.orchestration import FileRunContextBuilder, RetryingOrchestrator
from ai_software_engineer.orchestration.retry import RetryClassification
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import (
    NOW,
    make_coder_progress_artifact,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
)
from tests.manager.test_terminal_candidate_reconstruction import _BaselineResolver, _binding
from tests.orchestration.test_retry import AttemptIdentityFactory, ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions, _task


def _history(first: ExecutionBaselineBinding) -> tuple[ExecutionBaselineBinding, ...]:
    first = ExecutionBaselineBinding.create(
        **{
            **first.model_dump(exclude={"binding_sha256"}),
            "continuation_mode": BaselineContinuationMode.PAUSE,
            "superseded_progress_artifact_id": "art_progress_001",
            "source_artifact_ids": (*first.source_artifact_ids, "art_progress_001"),
        }
    )
    second = ExecutionBaselineBinding.create(
        **{
            **first.model_dump(exclude={"binding_sha256"}),
            "sequence": 2,
            "previous_binding_sha256": first.binding_sha256,
            "prior_execution_base_ref": first.execution_base_ref,
            "prior_source_revision": first.execution_source_revision,
            "execution_base_ref": "e" * 40,
            "execution_source_revision": "e" * 40,
            "superseded_implementation_artifact_id": None,
            "superseded_progress_artifact_id": None,
        }
    )
    return first, second


def _runner(
    tmp_path: Path,
    artifacts: tuple[Artifact, ...],
    *,
    adapter: ScriptedAdapter | None = None,
) -> tuple[SqliteTaskRepository, FileArtifactStore, RetryingOrchestrator]:
    root = tmp_path / "repository"
    root.mkdir()
    task = _task(root).model_copy(
        update={
            "base_ref": "a" * 40,
            "branch_name": "ai/feature/history-input",
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
        }
    )
    history = _history(_binding(task))
    repository = SqliteTaskRepository(tmp_path / "task.sqlite")
    repository.create(task)
    store = FileArtifactStore(tmp_path / "artifacts")
    for artifact in artifacts:
        store.put(seal_artifact(artifact, validated_at=NOW))
    runner = RetryingOrchestrator(
        repository=repository,
        artifact_store=store,
        context_builder=FileRunContextBuilder(root),
        agent_adapter=adapter or ScriptedAdapter(),
        agent_definitions=_definitions(),
        identities=AttemptIdentityFactory(),
        clock=_clock,
        coder_execution_inputs=_BaselineResolver(history[-1], history=history),
    )
    return repository, store, runner


@pytest.mark.parametrize("new_progress", [False, True])
def test_current_input_excludes_retired_checkpoint_chain_before_ordering(
    tmp_path: Path, new_progress: bool
) -> None:
    ancestor = make_coder_progress_artifact().model_copy(
        update={"artifact_id": "art_progress_ancestor"}
    )
    retired = make_coder_progress_artifact().model_copy(update={"supersedes": ancestor.artifact_id})
    artifacts: tuple[Artifact, ...] = (
        make_plan_artifact(),
        make_implementation_artifact(),
        ancestor,
        retired,
    )
    current = make_coder_progress_artifact().model_copy(
        update={"artifact_id": "art_progress_current", "source_revision": "e" * 40}
    )
    if new_progress:
        # The binding is the authoritative retirement; new output does not
        # need an ordinary Artifact edge to every older superseded checkpoint.
        artifacts += (current,)
    repository, store, runner = _runner(tmp_path, artifacts)
    with repository:
        task = repository.get(retired.task_id)
        original_artifacts = store.list_for_task(task.id)
        source = runner._current_coder_input(task)
        assert source.source_revision == "e" * 40
        assert source.active_progress == (store.get(current.artifact_id) if new_progress else None)
        assert source.progress_supersedes == retired.artifact_id
        assert store.list_for_task(task.id) == original_artifacts
        assert repository.list_events(task.id) == ()


def test_current_input_does_not_discard_unretired_source_mismatch(tmp_path: Path) -> None:
    progress = make_coder_progress_artifact().model_copy(
        update={"artifact_id": "art_progress_unknown", "source_revision": "c" * 40}
    )
    repository, store, runner = _runner(tmp_path, (make_plan_artifact(), progress))
    with repository:
        with pytest.raises(ValueError, match="执行版本不一致"):
            runner._current_coder_input(repository.get(progress.task_id))
        assert store.get(progress.artifact_id).source_revision == "c" * 40
        assert repository.list_events(progress.task_id) == ()


@pytest.mark.parametrize("new_candidate", [False, True])
def test_retry_blocked_result_does_not_resurrect_ancestor_retired_candidate(
    tmp_path: Path, new_candidate: bool
) -> None:
    artifacts: tuple[Artifact, ...] = (make_plan_artifact(), make_implementation_artifact())
    if new_candidate:
        implementation = make_implementation_artifact()
        artifacts += (
            implementation.model_copy(
                update={
                    "artifact_id": "art_impl_current",
                    "source_revision": "f" * 40,
                    "content": implementation.content.model_copy(update={"commit_sha": "f" * 40}),
                }
            ),
        )
    repository, store, runner = _runner(tmp_path, artifacts)
    with repository:
        task = repository.get("task_domain_001")
        result = runner._blocked(
            task,
            RetryClassification.BUDGET_EXHAUSTED,
            "fixture budget exhausted",
            task.attempts,
            (),
            (),
            source_revision="e" * 40,
        )
        assert result.candidate_revision == ("f" * 40 if new_candidate else None)
        assert store.get("art_impl_001") is not None


class _RequestCaptured(RuntimeError):
    pass


class _CaptureRequestAdapter(ScriptedAdapter):
    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        raise _RequestCaptured


def test_coder_progress_supersedes_latest_retired_checkpoint_from_entire_history(
    tmp_path: Path,
) -> None:
    adapter = _CaptureRequestAdapter()
    plan = make_plan_artifact()
    progress = make_coder_progress_artifact()
    repository, store, runner = _runner(tmp_path, (plan, progress), adapter=adapter)
    with repository:
        task = repository.get(plan.task_id)
        persisted_plan = store.get(plan.artifact_id)
        assert type(persisted_plan) is type(plan)
        with pytest.raises(_RequestCaptured):
            runner._run_coder_with_retries(task, plan, None, None, None, None, set(), [], [])
        request = adapter.requests[0]
        assert request.source_revision == "e" * 40
        assert request.continuation_checkpoint_id is None
        assert request.expected_supersedes_by_kind is not None
        assert (
            request.expected_supersedes_by_kind[ArtifactKind.CODER_PROGRESS] == progress.artifact_id
        )
        assert progress.artifact_id not in request.input_artifact_ids
        assert repository.get(task.id).attempts == task.attempts
        assert repository.list_events(task.id) == ()


def test_resume_keeps_exact_qa_feedback_without_reusing_retired_candidate_source(
    tmp_path: Path,
) -> None:
    adapter = _CaptureRequestAdapter()
    implementation = make_implementation_artifact()
    qa = make_qa_artifact()
    qa = qa.model_copy(
        update={"content": qa.content.model_copy(update={"status": QaReportStatus.FAIL})}
    )
    repository, store, runner = _runner(
        tmp_path, (make_plan_artifact(), implementation, qa), adapter=adapter
    )
    with repository:
        task = repository.get(implementation.task_id)
        with pytest.raises(_RequestCaptured):
            runner.run_task(task.id)
        request = adapter.requests[0]
        assert request.source_revision == "e" * 40
        assert qa.artifact_id in request.input_artifact_ids
        assert request.expected_supersedes_by_kind is not None
        assert (
            request.expected_supersedes_by_kind[ArtifactKind.IMPLEMENTATION_REPORT]
            == implementation.artifact_id
        )
        assert store.get(qa.artifact_id).source_revision == implementation.source_revision
        assert repository.get(task.id).attempts == task.attempts
        assert repository.list_events(task.id) == ()
