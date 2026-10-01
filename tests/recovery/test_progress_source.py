"""Stopped-worker gate rejects active execution before source reuse."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import ai_software_engineer.recovery.progress_source as module
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from tests.domain.factories import make_task


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
