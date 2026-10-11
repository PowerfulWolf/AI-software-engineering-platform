"""Fresh full consumption reads share pure scans, never durable authority or bytes."""

from __future__ import annotations

import gc
import hashlib
import json
import weakref
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer import redaction
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue import baseline
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, record_digest
from ai_software_engineer.work_queue.ports import QueueCorruption
from tests.manager.test_baseline_source_inspection_scope import LARGE_SOURCE, parsed_sources
from tests.manager.test_execution_baseline import authorize, setup


@dataclass
class ConsumptionRows:
    rows: tuple[dict[str, object], ...]
    queries: list[tuple[str, tuple[str]]] = field(default_factory=list)
    closed: int = 0
    error: Exception | None = None

    def cursor(self, kind: type[DictCursor]) -> ConsumptionRows:
        assert kind is DictCursor
        return self

    def __enter__(self) -> ConsumptionRows:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def close(self) -> None:
        self.closed += 1

    def execute(self, query: str, parameters: tuple[str]) -> None:
        self.queries.append((query, parameters))
        if self.error is not None:
            raise self.error

    def fetchall(self) -> tuple[dict[str, object], ...]:
        return self.rows


def consumption_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[MySqlRoleQueue, ConsumptionRows, BaselineQueueConsumption]:
    fixture = setup(tmp_path)
    (fixture.worktree.path / "src/app.py").write_text(LARGE_SOURCE)
    plan = fixture.service.propose(fixture.target)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    record = BaselineQueueConsumption(
        task_id=binding.task_id,
        work_item_id=plan.facts.work_item_id,
        next_work_item_id=plan.facts.work_item_id,
        prior_step_sha256="1" * 64,
        plan=plan,
        binding=binding,
    )
    rows = ConsumptionRows(
        (
            {
                "id": binding.binding_sha256,
                "task_id": record.task_id,
                "payload_json": json.dumps(record.to_wire(), ensure_ascii=False),
                "sha256": record_digest(record),
            },
        )
    )
    queue = MySqlRoleQueue.__new__(MySqlRoleQueue)
    queue._dsn = "isolated-reader-fixture"
    monkeypatch.setattr(baseline, "open_mysql_connection", lambda dsn: rows)
    return queue, rows, record


def test_full_consumption_read_scans_once_and_next_read_rechecks_exact_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, rows, record = consumption_reader(tmp_path, monkeypatch)
    original_row = dict(rows.rows[0])
    with parsed_sources(monkeypatch) as calls:
        first = baseline.consumptions(queue, record.task_id)
        assert len(first) == 1
        assert first[0].to_wire() == record.to_wire()
        assert record_digest(first[0]) == original_row["sha256"]
        assert calls[LARGE_SOURCE] == 1
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
        released = weakref.ref(first[0].plan.complete_capture)
        del first
        gc.collect()
        assert released() is None

        second = baseline.consumptions(queue, record.task_id)
        assert second == (record,)
        assert calls[LARGE_SOURCE] == 2, "a later read must not reuse previous checks"
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    assert rows.rows[0] == original_row
    assert rows.closed == 2
    assert len(rows.queries) == 2
    assert all(parameters == (record.task_id,) for _, parameters in rows.queries)


@pytest.mark.parametrize("change", ["secret", "path", "plan", "identity", "digest"])
def test_repeat_read_rejects_changed_body_path_plan_identity_and_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    queue, rows, record = consumption_reader(tmp_path, monkeypatch)
    changed = LARGE_SOURCE + 'password="actual-private-value"\n'
    with parsed_sources(monkeypatch) as calls:
        assert baseline.consumptions(queue, record.task_id) == (record,)
        assert calls[LARGE_SOURCE] == 1
        payload = json.loads(str(rows.rows[0]["payload_json"]))
        mutation = payload["plan"]["dirty_capture"]["mutations"][0]
        if change == "secret":
            mutation["after"].update(
                text=changed,
                sha256=hashlib.sha256(changed.encode()).hexdigest(),
                size=len(changed.encode()),
            )
        elif change == "path":
            mutation["path"] = "src/app.env"
        elif change == "plan":
            payload["plan"]["plan_sha256"] = "e" * 64
        row = dict(rows.rows[0])
        row.update(payload_json=json.dumps(payload, ensure_ascii=False), sha256=digest(payload))
        if change == "identity":
            row["id"] = "e" * 64
        elif change == "digest":
            row["sha256"] = "e" * 64
        rows.rows = (row,)
        with pytest.raises(QueueCorruption):
            baseline.consumptions(queue, record.task_id)
        if change == "secret":
            assert calls[changed] > 0, "new secret text cannot borrow an old clean result"
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    assert len(rows.queries) == 2
    assert rows.closed == 2


def test_failed_query_releases_read_scope_and_next_read_remains_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, rows, record = consumption_reader(tmp_path, monkeypatch)
    rows.error = RuntimeError("isolated query failure")
    with pytest.raises(RuntimeError, match="isolated query failure"):
        baseline.consumptions(queue, record.task_id)
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    rows.error = None
    with parsed_sources(monkeypatch) as calls:
        assert baseline.consumptions(queue, record.task_id) == (record,)
        assert calls[LARGE_SOURCE] == 1
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None
    assert len(rows.queries) == 2
    assert rows.closed == 2
