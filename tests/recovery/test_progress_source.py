"""Stopped-worker gate rejects active execution before source reuse."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import ai_software_engineer.recovery.progress_source as module
from ai_software_engineer.agents import ModelRouteAttempt
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole, StateEvent, Task, TaskStatus
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
)
from tests.domain.factories import make_task

_LOCAL_KNOWLEDGE_LIMIT = "TRANSIENT_INFRA: coder knowledge preparation reached local time limit"


def _prior_progress_history(
    reason: str = _LOCAL_KNOWLEDGE_LIMIT,
) -> tuple[ModelRouteAttempt, Task, ProjectDeliveryCheckpoint, tuple[StateEvent, ...]]:
    from ai_software_engineer.agents import AgentResult, AgentRunStatus
    from ai_software_engineer.domain.artifact import CoderProgressArtifact
    from tests.agents.test_openai_compatible import _align, _coder_request
    from tests.domain.factories import NOW, make_coder_progress_artifact, make_state_event

    request = _coder_request()
    progress = _align(make_coder_progress_artifact(), request)
    assert isinstance(progress, CoderProgressArtifact)
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
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=progress,
        ),
    )
    task = make_task().model_copy(
        update={"status": TaskStatus.BLOCKED, "attempts": 2, "base_ref": request.source_revision}
    )
    transitions = (
        (TaskStatus.IMPLEMENTING, TaskStatus.CONTINUE_REQUIRED, "coder_requested_continuation", 1),
        (TaskStatus.CONTINUE_REQUIRED, TaskStatus.QUEUED, "coder_continuation_queued", 1),
        (TaskStatus.QUEUED, TaskStatus.IMPLEMENTING, "coder_continuation_resumed", 2),
        (TaskStatus.IMPLEMENTING, TaskStatus.BLOCKED, reason, 2),
    )
    events = tuple(
        StateEvent.model_validate(
            {
                **make_state_event().to_wire(),
                "event_id": f"evt_knowledge_progress_{index}",
                "task_id": task.id,
                "from_status": from_status,
                "to_status": to_status,
                "reason": event_reason,
                "attempt": attempt,
                "source_revision": request.source_revision,
                "artifact_ids": (progress.artifact_id,),
            }
        )
        for index, (from_status, to_status, event_reason, attempt) in enumerate(transitions)
    )
    checkpoint = ProjectDeliveryCheckpoint.create(
        delivery_id="delivery_knowledge_progress",
        sequence=1,
        repository_id="repository_knowledge_progress",
        repository_root=task.repository,
        stage=DeliveryStage.BLOCKED,
        stage_attempts=DeliveryStageAttempts(),
        next_action=DeliveryNextAction.REQUEST_HUMAN,
        failure_code=DeliveryFailureCode.TRANSIENT_PROVIDER_FAILURE,
        failure_summary=reason.split(": ", 1)[1],
        checkpointed_at=NOW,
    )
    return route, task, checkpoint, events


@pytest.mark.parametrize(
    "reason",
    (
        _LOCAL_KNOWLEDGE_LIMIT,
        "TRANSIENT_INFRA: coder knowledge preparation failed: TIMEOUT",
        "TRANSIENT_INFRA: coder knowledge preparation failed: AUTHENTICATION_ERROR",
    ),
)
def test_prior_accepted_progress_survives_exact_next_attempt_knowledge_failure(reason: str) -> None:
    assert module.is_prior_progress_source(*_prior_progress_history(reason))


@pytest.mark.parametrize(
    "reason",
    (
        _LOCAL_KNOWLEDGE_LIMIT + " (assumed)",
        "TRANSIENT_INFRA: qa knowledge preparation reached local time limit",
        "TRANSIENT_INFRA: coder provider failed: TIMEOUT",
        "TRANSIENT_INFRA: coder knowledge preparation failed: PROVIDER_ERROR",
        "BUDGET_EXHAUSTED: coder knowledge preparation reached local time limit",
    ),
)
def test_prior_progress_does_not_accept_similar_or_unrelated_failure_reasons(reason: str) -> None:
    assert not module.is_prior_progress_source(*_prior_progress_history(reason))


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize(
    "changed",
    (
        {"task_id": "task_unrelated"},
        {"source_revision": "c" * 40},
        {"attempt": 3},
        {"from_status": TaskStatus.NEW},
        {"to_status": TaskStatus.FAILED},
        {"reason": "unrelated"},
        {"artifact_ids": ()},
    ),
)
def test_local_knowledge_failure_keeps_exact_four_event_tail(
    index: int, changed: dict[str, object]
) -> None:
    route, task, checkpoint, events = _prior_progress_history()
    altered = list(events)
    altered[index] = altered[index].model_copy(update=changed)
    assert not module.is_prior_progress_source(route, task, checkpoint, tuple(altered))


@pytest.mark.parametrize(
    "changed",
    (
        "nonadjacent_attempt",
        "different_task",
        "different_progress_task",
        "different_role",
        "different_run",
        "different_context",
        "different_source",
        "different_sequence",
        "unsuccessful_route",
        "candidate_exists",
        "different_summary",
        "missing_event",
        "extra_event",
        "earlier_candidate",
    ),
)
def test_local_knowledge_failure_keeps_progress_and_candidate_identity_gates(changed: str) -> None:
    from ai_software_engineer.agents.fallback import RouteAttemptOutcome
    from ai_software_engineer.domain.artifact import CoderProgressArtifact

    route, task, checkpoint, events = _prior_progress_history()
    progress = route.result.artifact
    assert isinstance(progress, CoderProgressArtifact)
    if changed == "nonadjacent_attempt":
        task = task.model_copy(update={"attempts": 3})
    elif changed == "different_task":
        route = route.model_copy(update={"task_id": "task_unrelated"})
    elif changed == "different_progress_task":
        progress = progress.model_copy(update={"task_id": "task_unrelated"})
    elif changed == "different_role":
        route = route.model_copy(update={"role": AgentRole.QA})
    elif changed == "different_run":
        progress = progress.model_copy(
            update={"producer": progress.producer.model_copy(update={"run_id": "run_unrelated"})}
        )
    elif changed == "different_context":
        progress = progress.model_copy(update={"context_manifest_id": "ctx_unrelated"})
    elif changed == "different_source":
        progress = progress.model_copy(update={"source_revision": "c" * 40})
    elif changed == "different_sequence":
        progress = progress.model_copy(
            update={"content": progress.content.model_copy(update={"checkpoint_sequence": 2})}
        )
    elif changed == "unsuccessful_route":
        route = route.model_copy(update={"outcome": RouteAttemptOutcome.FALLBACK})
    elif changed == "candidate_exists":
        checkpoint = checkpoint.model_copy(update={"candidate_revision": "d" * 40})
    elif changed == "different_summary":
        checkpoint = checkpoint.model_copy(update={"failure_summary": "unrelated"})
    elif changed == "missing_event":
        events = events[1:]
    elif changed == "extra_event":
        events = (*events, events[-1])
    elif changed == "earlier_candidate":
        events = (events[0].model_copy(update={"reason": "candidate_ready"}), *events)
    route = route.model_copy(
        update={"result": route.result.model_copy(update={"artifact": progress})}
    )
    assert not module.is_prior_progress_source(route, task, checkpoint, events)


@pytest.mark.parametrize(
    ("reason", "reaches_consultation_proof"),
    (
        (_LOCAL_KNOWLEDGE_LIMIT, True),
        ("TRANSIENT_INFRA: coder knowledge preparation failed: TIMEOUT", True),
        ("TRANSIENT_INFRA: coder knowledge preparation failed: AUTHENTICATION_ERROR", True),
        (_LOCAL_KNOWLEDGE_LIMIT + " (assumed)", False),
        ("TRANSIENT_INFRA: coder provider failed: TIMEOUT", False),
    ),
)
def test_candidate_knowledge_reason_still_requires_independent_consultation_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    reaches_consultation_proof: bool,
) -> None:
    import ai_software_engineer.recovery.candidate_preflight as preflight
    from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
    from ai_software_engineer.domain.enums import QaReportStatus
    from ai_software_engineer.recovery.models import RecoveryRejected
    from ai_software_engineer.recovery.verification_snapshot import CandidateRuntimeSnapshot
    from tests.domain.factories import (
        NOW,
        make_implementation_artifact,
        make_plan_artifact,
        make_qa_artifact,
    )

    _, task, checkpoint, events = _prior_progress_history(reason)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    implementation = make_implementation_artifact()
    qa = make_qa_artifact()
    qa = qa.model_copy(
        update={"content": qa.content.model_copy(update={"status": QaReportStatus.FAIL})}
    )
    for artifact in (make_plan_artifact(), implementation, qa):
        artifacts.put(seal_artifact(artifact, validated_at=NOW))
    accepted = events[0].model_copy(
        update={
            "to_status": TaskStatus.QA,
            "reason": "candidate_ready",
            "artifact_ids": (implementation.artifact_id,),
        }
    )
    feedback = events[2].model_copy(
        update={"from_status": TaskStatus.QA, "artifact_ids": (qa.artifact_id,)}
    )
    blocked = events[-1].model_copy(
        update={"artifact_ids": (implementation.artifact_id, qa.artifact_id)}
    )
    runtime = CandidateRuntimeSnapshot(
        task=task,
        revision=3,
        dispatch=MagicMock(),
        planner_dispatch=MagicMock(),
        events=(accepted, feedback, blocked),
    )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    proof_gate = MagicMock(side_effect=RecoveryRejected("unfinished consultation proof required"))
    monkeypatch.setattr(preflight, "_require_unfinished_coder_consultation", proof_gate)
    with pytest.raises(
        RecoveryRejected,
        match="unfinished consultation proof required"
        if reaches_consultation_proof
        else "newer interrupted Coder work",
    ):
        preflight.require_unchanged_pre_provider_candidate(
            config, {}, tmp_path, checkpoint, runtime, implementation
        )
    assert proof_gate.call_count == int(reaches_consultation_proof)


@pytest.mark.parametrize("active", ["claim", "work_item", None])
def test_stopped_progress_checks_both_worker_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: str | None
) -> None:
    sidecar = tmp_path / "sidecar"
    (sidecar / "runs/model-routes").mkdir(parents=True)
    cursor, connection = MagicMock(), MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = (
        [{"lease_id": "active"}]
        if active == "claim"
        else [None, {"id": "running"}]
        if active == "work_item"
        else [None, None]
    )
    monkeypatch.setattr(module, "open_mysql_connection", lambda _: connection)
    monkeypatch.setattr(ProductionConfig, "require_mysql_dsn", lambda *_: "offline")
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    # No route entries are needed: this probe targets the real SQL execution gate.
    route = MagicMock()
    if active is None:
        module.require_stopped_progress(config, {}, sidecar, make_task(), route)
    else:
        with pytest.raises(ValueError, match="active"):
            module.require_stopped_progress(config, {}, sidecar, make_task(), route)
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    "changed",
    [
        {},
        {"to_status": "BLOCKED"},
        {"attempt": 2},
        {"source_revision": "c" * 40},
        {"reason": "unrelated"},
        {"artifact_ids": ("art_progress_001", "art_extra_001")},
        {"task_id": "task_unrelated"},
    ],
)
def test_progress_acceptance_requires_exact_continuation_event(changed: dict[str, object]) -> None:
    from ai_software_engineer.agents import AgentResult, AgentRunStatus, ModelRouteAttempt
    from ai_software_engineer.domain import TaskStatus
    from tests.agents.test_openai_compatible import _align, _coder_request
    from tests.domain.factories import NOW, make_coder_progress_artifact, make_state_event

    request = _coder_request()
    artifact = _align(make_coder_progress_artifact(), request)
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
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=artifact,
        ),
    )
    event = make_state_event().model_validate(
        {
            **make_state_event().to_wire(),
            "task_id": request.task_id,
            "from_status": TaskStatus.IMPLEMENTING,
            "to_status": TaskStatus.CONTINUE_REQUIRED,
            "reason": "coder_requested_continuation",
            "attempt": request.attempt,
            "source_revision": request.source_revision,
            "artifact_ids": (artifact.artifact_id,),
            **changed,
        }
    )
    assert module.has_accepted_progress(route, (event,)) is (not changed)
