"""Exercise the MySQL transaction/fence seam offline; never open an operator database."""

import json
from pathlib import Path
from typing import Self

import pytest

from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure, DeliveryRetryPolicy
from ai_software_engineer.store import MySqlTaskRepository
from tests.orchestration.test_execution_retry_budget import budget_task


class TransactionConnection:
    def __init__(self, task_id: str, payload: str) -> None:
        self.task_id = task_id
        self.payload = self.pending = payload
        self.statements: list[str] = []
        self.commits = self.rollbacks = 0

    def begin(self) -> None:
        self.pending = self.payload

    def commit(self) -> None:
        self.payload = self.pending
        self.commits += 1

    def rollback(self) -> None:
        self.pending = self.payload
        self.rollbacks += 1

    def cursor(self) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def execute(self, sql: str, params: tuple[str, ...]) -> None:
        self.statements.append(sql)
        if sql.startswith("UPDATE"):
            self.pending = params[0]

    def fetchone(self) -> dict[str, str]:
        return {"id": self.task_id, "payload_json": self.pending}


@pytest.mark.parametrize("lost_at", [None, 1, 2])
def test_retry_fact_is_fenced_before_and_after_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lost_at: int | None,
) -> None:
    task = budget_task(tmp_path, DeliveryRetryPolicy()).model_copy(
        update={"status": TaskStatus.QA, "attempts": 1}
    )
    connection = TransactionConnection(task.id, json.dumps(task.to_wire()))
    monkeypatch.setattr(
        "ai_software_engineer.store.mysql_repository.open_mysql_connection", lambda _: connection
    )
    monkeypatch.setattr(MySqlTaskRepository, "_initialize_schema", lambda _: None)
    repository = MySqlTaskRepository("fixture-not-a-dsn")
    fences = []

    def fence(_cursor: object, task_id: str) -> None:
        fences.append(task_id)
        if len(fences) == lost_at:
            raise RuntimeError("fixture owner lost")

    repository.mutation_fence = fence
    failure = DeliveryRetryFailure(role=AgentRole.QA, attempt=1, code="TIMEOUT")
    if lost_at is not None:
        with pytest.raises(RuntimeError, match="owner lost"):
            repository.record_retry_failure(task.id, failure)
        assert json.loads(connection.payload) == task.to_wire()
        assert connection.rollbacks == 1 and connection.commits == 0
    else:
        repository.record_retry_failure(task.id, failure)
        assert fences == [task.id, task.id]
        assert any("FOR UPDATE" in sql for sql in connection.statements)
        saved = json.loads(connection.payload)
        assert saved["attempts"] == 2
        assert saved["retry_failures"] == [failure.to_wire()]
        repository.record_retry_failure(task.id, failure)
        assert json.loads(connection.payload) == saved
