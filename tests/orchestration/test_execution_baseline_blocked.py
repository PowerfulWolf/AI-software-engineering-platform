"""An execution input is never advertised as an accepted candidate after exhaustion."""

from pathlib import Path

import pytest

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.orchestration import FileRunContextBuilder, RetryingOrchestrator
from ai_software_engineer.orchestration.retry import RetryClassification
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import NOW, make_implementation_artifact, make_plan_artifact
from tests.git.test_worktree import _git
from tests.manager.test_execution_baseline import authorize, setup
from tests.orchestration.test_retry import AttemptIdentityFactory, ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions


@pytest.mark.parametrize("accepted", ["none", "superseded", "new"])
def test_baseline_input_is_distinct_from_accepted_candidate_in_terminal_handoff(
    tmp_path: Path,
    accepted: str,
) -> None:
    fixture = setup(tmp_path)
    plan = fixture.service.propose(fixture.target)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    task = fixture.collector.facts.task
    assert binding.execution_source_revision != task.base_ref
    artifacts = FileArtifactStore(tmp_path / "blocked-artifacts")
    artifacts.put(
        seal_artifact(
            make_plan_artifact().model_copy(
                update={"task_id": task.id, "source_revision": task.base_ref}
            ),
            validated_at=NOW,
        )
    )
    candidate = None
    if accepted != "none":
        if accepted == "new":
            _git(fixture.worktree.path, "add", "src/app.py")
            _git(fixture.worktree.path, "commit", "-m", "complete retained candidate after rebind")
            candidate = _git(fixture.worktree.path, "rev-parse", "HEAD")
        report = make_implementation_artifact()
        source = candidate if candidate is not None else fixture.worktree.head_revision
        artifacts.put(
            seal_artifact(
                report.model_copy(
                    update={
                        "artifact_id": "art_impl_current" if accepted == "new" else "art_impl_old",
                        "task_id": task.id,
                        "source_revision": source,
                        "content": report.content.model_copy(update={"commit_sha": source}),
                    }
                ),
                validated_at=NOW,
            )
        )
    with SqliteTaskRepository(tmp_path / "blocked.sqlite") as repository:
        repository.create(task)
        runner = RetryingOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=FileRunContextBuilder(fixture.repository),
            agent_adapter=ScriptedAdapter(),
            agent_definitions=_definitions(),
            identities=AttemptIdentityFactory(),
            clock=_clock,
            coder_execution_inputs=StoredCoderExecutionInputResolver(fixture.service.store),
        )
        result = runner._blocked(
            task,
            RetryClassification.BUDGET_EXHAUSTED,
            "fixture work allowance exhausted",
            task.attempts,
            (),
            (),
            source_revision=binding.execution_source_revision,
        )
        assert result.candidate_revision == candidate
        assert result.task.base_ref == task.base_ref
        assert (
            repository.list_events(task.id)[-1].source_revision == binding.execution_source_revision
        )
