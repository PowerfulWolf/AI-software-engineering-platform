"""Regression for terminal Tasks retaining independent verifier occupancy."""

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from pymysql.connections import Connection

from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.project_manager.dispatch import VerificationReservation
from ai_software_engineer.project_manager.mysql_dispatch_authority import MySqlDispatchAuthority
from tests.project_manager.test_dispatch import RecordingDispatchStore, _facts, _service


@pytest.mark.parametrize("completed", [False, True])
def test_terminal_task_does_not_release_live_verification(tmp_path: Path, completed: bool) -> None:
    request, snapshot = _facts(tmp_path)
    dispatch = _service(RecordingDispatchStore(), snapshot, request).commit_dispatch(request)
    phases = []
    for index, phase in enumerate(dispatch.phases[1:]):
        assignment_id, lease_id = f"assignment_verifier_{index}", f"lease_verifier_{index}"
        phases.append(
            phase.model_copy(
                update={
                    "assignment": phase.assignment.model_copy(
                        update={
                            "id": assignment_id,
                            "lease_id": lease_id,
                            "task_id": "task_verification_fixture",
                        }
                    ),
                    "lease": phase.lease.model_copy(
                        update={
                            "id": lease_id,
                            "assignment_id": assignment_id,
                            "task_id": "task_verification_fixture",
                        }
                    ),
                }
            )
        )
    reservation = VerificationReservation(
        plan_sha256="a" * 64,
        project_id=dispatch.project_id,
        source_task_id=dispatch.task_id,
        task_id="task_verification_fixture",
        workforce_snapshot_sha256=snapshot.snapshot_sha256,
        phases=tuple(phases),
        committed_at=dispatch.committed_at,
    )
    cursor = MagicMock()
    cursor.fetchone.return_value = {
        "project_id": snapshot.project_id,
        "task_id": snapshot.task_id,
        "payload_json": snapshot.model_dump_json(),
        "snapshot_sha256": snapshot.snapshot_sha256,
    }
    cursor.fetchall.side_effect = [
        [
            {
                "id": dispatch.id,
                "project_id": dispatch.project_id,
                "task_id": dispatch.task_id,
                "payload_json": dispatch.model_dump_json(),
                "dispatch_sha256": dispatch.dispatch_sha256,
            }
        ],
        [
            {
                "id": dispatch.task_id,
                "payload_json": dispatch.task.model_copy(
                    update={"status": TaskStatus.FAILED}
                ).model_dump_json(),
            }
        ],
        [
            {
                "plan_sha256": reservation.plan_sha256,
                "payload_json": reservation.model_dump_json(),
                "completion_sha256": "b" * 64 if completed else None,
            }
        ],
    ]
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    authority = object.__new__(MySqlDispatchAuthority)
    actual = authority._current_snapshot(
        cast(Connection, connection), snapshot.project_id, snapshot.task_id
    )
    assert {lease.id for lease in actual.active_leases} == (
        set() if completed else {p.lease.id for p in reservation.phases}
    )
    assert {p.assignment.id for p in reservation.phases} <= {a.id for a in actual.assignments}
