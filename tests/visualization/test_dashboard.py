"""Dashboard data/rendering and HTML injection safety tests."""

import json

from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.projection import ProjectionSnapshot, TaskProjection
from ai_software_engineer.visualization import DashboardRenderer


def test_dashboard_exposes_four_read_only_views() -> None:
    snapshot = ProjectionSnapshot(
        tasks=(
            TaskProjection(
                task_id="task_dashboard_001",
                title="Task <untrusted>",
                status=TaskStatus.BLOCKED,
                attempts=2,
                state_revision=4,
            ),
        )
    )
    data = DashboardRenderer().build_data(snapshot)
    assert data["read_only"] is True
    assert {"task_board", "run_timeline", "agents", "human_inbox"} <= set(data)
    assert data["human_inbox"][0]["read_only"] is True  # type: ignore[index]


def test_dashboard_json_is_stable_and_html_escapes_embedded_data() -> None:
    snapshot = ProjectionSnapshot(
        tasks=(
            TaskProjection(
                task_id="task_dashboard_002",
                title="</script><script>alert(1)</script>",
                status=TaskStatus.DONE,
                attempts=1,
                state_revision=5,
            ),
        )
    )
    renderer = DashboardRenderer()
    payload = renderer.render_json(snapshot)
    assert json.loads(payload)["task_board"][0]["task_id"] == "task_dashboard_002"
    html = renderer.render_html(snapshot)
    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script\\u003e" in html
