"""The native SQL source gate validates rebinding without rewriting old events."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import StateEvent, TaskStatus
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.delivery_checkpoint import ProjectDeliveryCheckpoint
from ai_software_engineer.recovery import native
from ai_software_engineer.recovery.baseline_source import RecoveryBaselineEpoch
from ai_software_engineer.recovery.models import RecoveryScope
from tests.domain.factories import NOW, make_state_event
from tests.manager.test_dispatch import RecordingDispatchStore, _facts, _service
from tests.manager.test_terminal_candidate_reconstruction import _binding


@pytest.mark.parametrize("wrong_source", [False, True])
def test_native_sql_gate_accepts_only_the_exact_terminal_epoch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrong_source: bool
) -> None:
    request, workforce = _facts(tmp_path)
    dispatch = _service(RecordingDispatchStore(), workforce, request).commit_dispatch(request)
    dispatch = dispatch.model_copy(
        update={"task": dispatch.task.model_copy(update={"branch_name": "ai/feature/epoch"})}
    )
    dispatch = dispatch.model_copy(
        update={
            "dispatch_sha256": digest(
                dispatch.model_dump(mode="json", exclude={"dispatch_sha256"}, exclude_none=True)
            )
        }
    )
    task = dispatch.task.model_copy(update={"status": TaskStatus.BLOCKED, "attempts": 2})
    wire = _binding(task).to_wire()
    wire.pop("binding_sha256")
    binding = ExecutionBaselineBinding.create(**{**wire, "prior_task_revision": 2})
    events: list[StateEvent] = []
    for number, (before, after) in enumerate(
        (
            (TaskStatus.NEW, TaskStatus.PLANNING),
            (TaskStatus.PLANNING, TaskStatus.IMPLEMENTING),
            (TaskStatus.IMPLEMENTING, TaskStatus.BLOCKED),
        ),
        1,
    ):
        events.append(
            make_state_event(
                event_id=f"evt_sql_epoch_{number}", from_status=before, to_status=after
            ).model_copy(
                update={
                    "task_id": task.id,
                    "attempt": 1 if number < 3 else 2,
                    "source_revision": task.base_ref if number < 3 or wrong_source else "d" * 40,
                    "occurred_at": NOW + timedelta(seconds=number),
                }
            )
        )
    checkpoint = ProjectDeliveryCheckpoint.model_construct(
        delivery_id="delivery_epoch",
        repository_id=dispatch.repository_id,
        repository_root=task.repository,
        dispatch_commit_id=dispatch.id,
        dispatch_commit_sha256=dispatch.dispatch_sha256,
        task_id=task.id,
        task_revision=3,
        task_status=TaskStatus.BLOCKED,
    )
    cursor, connection = MagicMock(), MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [
        {
            "id": dispatch.id,
            "repository_id": dispatch.repository_id,
            "task_id": task.id,
            "dispatch_sha256": dispatch.dispatch_sha256,
            "payload_json": dispatch.model_dump_json(),
        },
        {"revision": 3, "status": task.status.value, "payload_json": task.model_dump_json()},
    ]
    cursor.fetchall.return_value = [
        {"revision": number, "event_id": event.event_id, "payload_json": event.model_dump_json()}
        for number, event in enumerate(events, 1)
    ]
    monkeypatch.setattr(native, "open_mysql_connection", lambda _: connection)
    sidecar = tmp_path / "sidecar"
    observations: list[tuple[Path, str, RecoveryScope]] = []

    def epochs(
        root: Path, _: object, scope: RecoveryScope, *, project_id: str
    ) -> tuple[RecoveryBaselineEpoch, ...]:
        observations.append((root, project_id, scope))
        return (RecoveryBaselineEpoch(binding, 2),)

    monkeypatch.setattr(native, "read_recovery_baseline_epochs", epochs)
    reader = native.NativeRecoverySourceReader(
        ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            model_routes=(
                ProviderRouteConfig(
                    provider="codex", model="offline", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        ),
        {"ASE_MYSQL_DSN": "mysql://offline@localhost/isolated"},
    )
    if wrong_source:
        with pytest.raises(ValueError, match="source revision mismatch"):
            reader._sql(checkpoint, (checkpoint,), sidecar=sidecar, project_id="project_exact")
    else:
        observed = reader._sql(
            checkpoint, (checkpoint,), sidecar=sidecar, project_id="project_exact"
        )
        assert observed == (task, 3, dispatch, dispatch, tuple(events))
    assert observations[0][:2] == (sidecar, "project_exact")
    assert observations[0][2].repository_root == task.repository
    queries = [call.args[0] for call in cursor.execute.call_args_list]
    assert "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY" in queries
    assert all(
        query.startswith(("SELECT", "SET TRANSACTION", "START TRANSACTION")) for query in queries
    )
    connection.rollback.assert_called_once_with()
    connection.close.assert_called_once_with()
