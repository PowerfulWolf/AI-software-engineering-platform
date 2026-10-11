"""Fine execution facts are read only for the fresh live RUNNING claim."""

from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.team_view import queue_reader
from ai_software_engineer.work_queue.execution_store import RoleQueueAdmission, record_digest
from tests.team_view.test_knowledge_preparation_phase import NOW, Fixture, fixture


class Cursor:
    def __init__(self, view: Fixture, status: WorkItemStatus, *, live: bool) -> None:
        self.view, self.status, self.live = view, status, live
        self.rows: list[dict[str, object]] = []

    def execute(self, query: str, values: object = None) -> None:
        assert query.startswith("SELECT ")
        item = self.view.item.model_copy(
            update={
                "status": self.status,
                "wait_reason": "waiting" if self.status is WorkItemStatus.WAITING_HUMAN else None,
            }
        )
        if "information_schema.TABLES" in query:
            self.rows = [{"TABLE_NAME": "work_queue_admissions"}]
        elif "FROM work_queue_admissions " in query:
            admission = RoleQueueAdmission(
                task_id=item.task_id,
                repository_id=item.repository_id,
                allocation_sha256="a" * 64,
                legacy_artifacts=(),
            )
            self.rows = [
                {
                    "id": item.task_id,
                    "task_id": item.task_id,
                    "payload_json": admission.model_dump_json(),
                    "sha256": record_digest(admission),
                }
            ]
        elif "FROM work_queue_items " in query:
            self.rows = [
                {"id": item.id, "task_id": item.task_id, "payload_json": item.model_dump_json()}
            ]
        elif "FROM work_queue_claims " in query:
            lease = self.view.claim.lease
            if not self.live:
                lease = lease.model_copy(update={"expires_at": NOW + timedelta(seconds=1)})
            self.rows = [
                {
                    "lease_id": lease.id,
                    "assignment_json": self.view.claim.assignment.model_dump_json(),
                    "lease_json": lease.model_dump_json(),
                    "state": "ACTIVE",
                    "last_heartbeat_at": NOW.isoformat(),
                    "expires_at": lease.expires_at.isoformat(),
                }
            ]
        else:
            raise AssertionError(query)

    def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


@pytest.mark.parametrize(
    ("status", "live", "expected"),
    [
        (WorkItemStatus.RUNNING, True, "KNOWLEDGE_PREPARATION"),
        (WorkItemStatus.RUNNING, False, None),
        (WorkItemStatus.LEASED, True, None),
        (WorkItemStatus.WAITING_HUMAN, True, None),
    ],
)
def test_only_current_live_running_claim_reads_fine_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: WorkItemStatus,
    live: bool,
    expected: str | None,
) -> None:
    view = fixture(tmp_path)
    view.intent()
    calls: list[object] = []

    def current_source(*args: object, **kwargs: object) -> str:
        calls.append(kwargs["lease"])
        return view.scope.source_revision

    monkeypatch.setattr(queue_reader, "read_claim_source", current_source)
    (projected,) = queue_reader.read_role_queue(
        cast(DictCursor, Cursor(view, status, live=live)),
        task_id=view.item.task_id,
        repository_id=view.item.repository_id,
        allocation_sha256="a" * 64,
        now=NOW + timedelta(seconds=2),
        execution_scope=view.scope,
    )
    assert projected.execution_phase == expected
    assert len(calls) == (1 if expected else 0)
