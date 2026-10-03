"""Read-side execution history keeps every immutable delivery round."""

from datetime import UTC, datetime

from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.projection.models import ProjectionEventKind, TimelineEntry
from ai_software_engineer.team_view.models import ScopeView, TaskView
from ai_software_engineer.team_view.reader import _merge_task_history


def _entry(task_id: str, number: int, summary: str) -> TimelineEntry:
    return TimelineEntry(
        id=f"evt_history_{task_id}_{number}",
        kind=ProjectionEventKind.STATE,
        occurred_at=datetime(2026, 10, 3, 1, number, tzinfo=UTC),
        task_id=task_id,
        role=AgentRole.CODER,
        summary=summary,
        source_uri=f"state://{task_id}/{number}",
        details={"reason": "qa_failed_route_to_coder"},
    )


def _task(task_id: str, entries: tuple[TimelineEntry, ...]) -> TaskView:
    return TaskView(
        id=f"delivery_{task_id}",
        project_id="project_history",
        request_id="delivery_multi_history",
        task_id=task_id,
        title="history",
        scope=ScopeView(root="/repo", selected_paths=(".",)),
        status="IMPLEMENTING",
        checkpoint_stage="DELIVERING",
        terminal=False,
        last_activity=entries[-1].occurred_at,
        next_action="继续",
        timeline=entries,
    )


def test_merge_task_history_is_complete_and_marks_current_task_separately() -> None:
    historical = _task(
        "task_old_round",
        tuple(_entry("task_old_round", number, f"历史 {number}") for number in range(1, 10)),
    )
    current = _task(
        "task_current_round",
        tuple(_entry("task_current_round", number, f"当前 {number}") for number in range(10, 13)),
    )
    merged = _merge_task_history(current, (historical,))

    assert len(merged.execution_history) == 12
    assert {entry.task_id for entry in merged.execution_history} == {
        "task_old_round",
        "task_current_round",
    }
    assert merged.history_task_ids == ("task_current_round", "task_old_round")
    assert len(merged.timeline) == 3
