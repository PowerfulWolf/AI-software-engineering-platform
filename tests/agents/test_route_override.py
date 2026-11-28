"""Task-scoped human model route decisions are append-only and digest-protected."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.agents.route_override import (
    FileModelRouteOverrideStore,
    ModelRouteOverride,
    ModelRouteOverrideError,
)
from ai_software_engineer.domain.enums import AgentRole


def _record(sequence: int, model: str = "codex/gpt-6.2-sol") -> ModelRouteOverride:
    return ModelRouteOverride.create(
        task_id="task_quota",
        role=AgentRole.REVIEWER,
        sequence=sequence,
        provider="codex",
        model=model,
        route_kind="responses",
        reason="claude/claude-opus-5-5 quota exhausted in run_x",
        approval_reference="web-console-operation:operation_1",
        approved_at=datetime(2026, 11, 28, tzinfo=UTC),
    )


def test_latest_decision_wins_and_history_is_kept(tmp_path: Path) -> None:
    store = FileModelRouteOverrideStore(tmp_path)
    assert store.current("task_quota", AgentRole.REVIEWER) is None
    store.append(_record(1))
    second = store.append(_record(2, model="claude-opus-5-5"))
    assert store.current("task_quota", AgentRole.REVIEWER) == second
    assert len(store.list("task_quota", AgentRole.REVIEWER)) == 2
    assert store.current("task_quota", AgentRole.QA) is None


def test_stale_or_tampered_decisions_are_rejected(tmp_path: Path) -> None:
    store = FileModelRouteOverrideStore(tmp_path)
    store.append(_record(1))
    with pytest.raises(ModelRouteOverrideError):
        store.append(_record(1))
    with pytest.raises(ModelRouteOverrideError):
        store.append(_record(3))
    tampered = _record(2).model_copy(update={"model": "other"})
    with pytest.raises(ModelRouteOverrideError):
        store.append(tampered)


def test_override_only_reorders_configured_routes() -> None:
    from dataclasses import dataclass
    from enum import Enum

    from ai_software_engineer.agents.route_override import apply_route_override

    class Kind(Enum):
        CLI = "claude_cli"
        RESPONSES = "responses"

    @dataclass(frozen=True)
    class Route:
        provider: str
        model: str
        kind: Kind

    primary = Route("claude", "claude-opus-5-5", Kind.CLI)
    backup = Route("codex", "codex/gpt-6.2-sol", Kind.RESPONSES)
    assert apply_route_override((primary, backup), None) == (primary, backup)
    assert apply_route_override((primary, backup), _record(1)) == (backup, primary)
    with pytest.raises(ModelRouteOverrideError):
        apply_route_override((primary,), _record(1))
