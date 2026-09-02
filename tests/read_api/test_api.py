"""GET-only routing, pagination, filtering, and mutation refusal tests."""

from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.projection import ProjectionSnapshot, TaskProjection
from ai_software_engineer.read_api import ReadOnlyProjectionApi


def _api() -> ReadOnlyProjectionApi:
    return ReadOnlyProjectionApi(
        snapshot=ProjectionSnapshot(
            tasks=(
                TaskProjection(
                    task_id="task_read_api_001",
                    project_id="project_read_api_001",
                    title="Read model",
                    status=TaskStatus.DONE,
                    attempts=1,
                    state_revision=5,
                ),
            )
        )
    )


def test_api_lists_and_gets_tasks_with_stable_wire_payload() -> None:
    api = _api()
    listed = api.handle("GET", "/api/v1/tasks", {"status": "DONE"})
    assert listed.status_code == 200
    assert listed.payload["total"] == 1
    assert api.get_task("task_read_api_001").status_code == 200
    assert api.get_task("task_missing").status_code == 404


def test_api_is_get_only_and_rejects_invalid_paging() -> None:
    api = _api()
    assert api.handle("POST", "/api/v1/tasks").status_code == 405
    assert api.handle("GET", "/api/v1/tasks", {"page_size": "0"}).status_code == 400
    assert api.handle("GET", "/api/v1/mutate").status_code == 404
