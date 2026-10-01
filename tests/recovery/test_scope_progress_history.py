"""An earlier accepted progress can justify scope without replacing the failed Run."""

from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentFailure,
    AgentResult,
    AgentRunStatus,
    FileModelRouteAttemptStore,
    ModelRouteAttempt,
)
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import CoderProgressArtifact, Task, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.orchestration import FileRunContextBuilder
from ai_software_engineer.recovery.progress_source import accepted_scope_progress
from tests.agents.test_openai_compatible import _align, _coder_request
from tests.domain.factories import (
    NOW,
    make_agent,
    make_coder_progress_artifact,
    make_state_event,
    make_task,
)


def history(
    tmp_path: Path, *, attempt: int = 1, context_attempt: int | None = None
) -> tuple[Task, CoderProgressArtifact, StateEvent]:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    request = _coder_request().model_copy(
        update={"attempt": attempt, "run_id": f"run_scope_{attempt:02d}"}
    )
    task = make_task().model_copy(
        update={
            "repository": str(project),
            "base_ref": request.source_revision,
            "status": TaskStatus.BLOCKED,
            "attempts": 2,
        }
    )
    context = FileRunContextBuilder(project).build(
        task, make_agent(), attempt=context_attempt or attempt
    )
    FileContextStore(tmp_path / "contexts").put(context)
    request = request.model_copy(update={"context_manifest_id": context.context_id})
    template = make_coder_progress_artifact()
    artifact = _align(template, request).model_copy(
        update={
            "artifact_id": f"art_scope_{attempt:02d}",
            "parent_artifact_ids": (),
            "supersedes": None,
            "content": template.content.model_copy(update={"checkpoint_sequence": attempt}),
        }
    )
    assert isinstance(artifact, CoderProgressArtifact)
    artifact = seal_artifact(artifact, validated_at=NOW)
    assert isinstance(artifact, CoderProgressArtifact)
    FileArtifactStore(tmp_path / "artifacts").put(artifact)
    route = ModelRouteAttempt.create(
        request=request,
        route_index=1,
        provider="codex",
        model="offline",
        started_at=NOW,
        completed_at=NOW,
        fallback=False,
        result=AgentResult(
            run_id=request.run_id,
            task_id=task.id,
            role=request.role,
            attempt=attempt,
            source_revision=request.source_revision,
            context_manifest_id=context.context_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=artifact,
        ),
    )
    FileModelRouteAttemptStore(tmp_path / "runs/model-routes").append(route)
    event = make_state_event().model_copy(
        update={
            "task_id": task.id,
            "from_status": TaskStatus.IMPLEMENTING,
            "to_status": TaskStatus.CONTINUE_REQUIRED,
            "reason": "coder_requested_continuation",
            "attempt": attempt,
            "source_revision": request.source_revision,
            "artifact_ids": (artifact.artifact_id,),
        }
    )
    return task, artifact, event


def test_prior_progress_is_scope_evidence_after_later_execution(tmp_path: Path) -> None:
    task, artifact, event = history(tmp_path)
    blocked = event.model_copy(
        update={
            "from_status": TaskStatus.IMPLEMENTING,
            "to_status": TaskStatus.BLOCKED,
            "attempt": 2,
            "reason": "Coder timeout",
        }
    )
    assert accepted_scope_progress(tmp_path, task, (event, blocked), task.base_ref) == artifact
    assert accepted_scope_progress(tmp_path, task, (blocked,), task.base_ref) is None


@pytest.mark.parametrize("fault", ["task", "attempt", "artifact", "route", "context", "future"])
def test_scope_history_rejects_unbound_or_missing_facts(tmp_path: Path, fault: str) -> None:
    task, _, event = history(tmp_path, context_attempt=2 if fault == "context" else None)
    if fault in {"artifact", "route"}:
        root = tmp_path / ("artifacts" if fault == "artifact" else "runs/model-routes")
        next(root.rglob("*.json")).unlink()
    if fault == "task":
        task = task.model_copy(update={"id": "task_foreign"})
    if fault == "attempt":
        event = event.model_copy(update={"attempt": 2})
    if fault == "future":
        task = task.model_copy(update={"attempts": 0})
    with pytest.raises(ValueError):
        accepted_scope_progress(tmp_path, task, (event,), task.base_ref)


def test_older_input_revision_is_not_scope_evidence_for_newer_candidate(tmp_path: Path) -> None:
    task, _, event = history(tmp_path)
    assert accepted_scope_progress(tmp_path, task, (event,), "c" * 40) is None


def test_latest_acceptance_is_authoritative_even_when_broken(tmp_path: Path) -> None:
    task, first, first_event = history(tmp_path)
    _, latest, latest_event = history(tmp_path, attempt=2)
    assert first != latest
    assert (
        accepted_scope_progress(tmp_path, task, (first_event, latest_event), task.base_ref)
        == latest
    )
    (tmp_path / "artifacts" / f"{latest.artifact_id}.json").unlink()
    with pytest.raises(ValueError):
        accepted_scope_progress(tmp_path, task, (first_event, latest_event), task.base_ref)


@pytest.mark.parametrize("fault", [None, "gap", "not_fallback", "identity", "failed_final"])
def test_scope_progress_validates_complete_fallback_chain(
    tmp_path: Path, fault: str | None
) -> None:
    task, artifact, event = history(tmp_path)
    root = tmp_path / "runs/model-routes"
    store = FileModelRouteAttemptStore(root)
    original = store.list_for_run(artifact.producer.run_id)[0]
    (root / original.run_id / "01.json").unlink()
    request = _coder_request().model_copy(
        update={
            "run_id": original.run_id,
            "context_manifest_id": artifact.context_manifest_id,
        }
    )
    failure = original.result.model_copy(
        update={
            "status": AgentRunStatus.TIMED_OUT,
            "artifact": None,
            "error": AgentFailure(
                code=AgentErrorCode.TIMEOUT, message="offline timeout", transient=True
            ),
        }
    )
    first_result = original.result if fault == "not_fallback" else failure
    if fault == "identity":
        first_result = first_result.model_copy(update={"context_manifest_id": "ctx_" + "d" * 64})
    if fault != "gap":
        store.append(
            ModelRouteAttempt.create(
                request=request,
                route_index=1,
                provider="codex",
                model="first",
                started_at=NOW,
                completed_at=NOW,
                result=first_result,
                fallback=True,
            )
        )
    store.append(
        ModelRouteAttempt.create(
            request=request,
            route_index=2,
            provider="codex",
            model="fallback",
            started_at=NOW,
            completed_at=NOW,
            result=failure if fault == "failed_final" else original.result,
            fallback=False,
        )
    )
    if fault is None:
        assert accepted_scope_progress(tmp_path, task, (event,), task.base_ref) == artifact
    else:
        with pytest.raises(ValueError):
            accepted_scope_progress(tmp_path, task, (event,), task.base_ref)


@pytest.mark.parametrize("component", ["artifacts", "contexts", "routes"])
def test_scope_progress_rejects_symbolic_record_files(tmp_path: Path, component: str) -> None:
    task, _, event = history(tmp_path)
    root = tmp_path / ("runs/model-routes" if component == "routes" else component)
    record = next(root.rglob("*.json"))
    outside = tmp_path / "untrusted-copy.json"
    outside.write_bytes(record.read_bytes())
    record.unlink()
    record.symlink_to(outside)
    with pytest.raises(ValueError):
        accepted_scope_progress(tmp_path, task, (event,), task.base_ref)
