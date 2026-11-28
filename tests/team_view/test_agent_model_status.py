"""Agent views expose configured model order and the latest recorded role call."""

from datetime import UTC, datetime
from types import SimpleNamespace

from ai_software_engineer.domain.enums import AgentRole, TeamRole
from ai_software_engineer.team_view.models import RunView
from ai_software_engineer.team_view.reader import _last_model_call


def _run(run_id: str, role: AgentRole, minute: int, **fields: object) -> RunView:
    values: dict[str, object] = {
        "run_id": run_id,
        "role": role,
        "provider": "claude",
        "model": "claude-opus-5-5",
        "route_index": 1,
        "outcome": "SUCCEEDED",
        "duration_ms": 1,
        "completed_at": datetime(2026, 11, 28, 5, minute, tzinfo=UTC),
        "source_uri": f"model-route://{run_id}/1",
        "sha256": "a" * 64,
    }
    values.update(fields)
    return RunView.model_validate(values)


def test_latest_call_of_the_agents_own_roles_is_reported() -> None:
    profile = SimpleNamespace(eligible_roles=(TeamRole.REVIEWER,))
    tasks = [
        SimpleNamespace(
            id="task_a",
            runs=(
                _run(
                    "run_1", AgentRole.REVIEWER, 1, outcome="FAILED", error_code="QUOTA_EXHAUSTED"
                ),
                _run("run_2", AgentRole.CODER, 9),
            ),
        ),
        SimpleNamespace(
            id="task_b",
            runs=(
                _run(
                    "run_3",
                    AgentRole.REVIEWER,
                    5,
                    outcome="FAILED",
                    error_code="QUOTA_EXHAUSTED",
                ),
            ),
        ),
    ]
    call = _last_model_call(profile, tasks)  # type: ignore[arg-type]
    assert call is not None
    assert (call.task_id, call.error_code, call.role) == (
        "task_b",
        "QUOTA_EXHAUSTED",
        AgentRole.REVIEWER,
    )
    assert _last_model_call(SimpleNamespace(eligible_roles=(TeamRole.QA,)), tasks) is None  # type: ignore[arg-type]
