"""Bounded reading projections never replace exact operation authority."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from ai_software_engineer.web_console.core import ProjectConsole
from ai_software_engineer.web_console.models import (
    ConsoleCommandResult,
    ConsoleOperation,
    CreateProjectIntent,
)
from ai_software_engineer.web_console.store import (
    ConsoleOperationConflict,
    FileConsoleOperationStore,
)
from ai_software_engineer.web_console.summary_models import (
    OperationSummary,
    OperationSummaryCursor,
    OperationSummaryPage,
    OperationSummaryQuery,
    StaleOperationCursor,
)
from ai_software_engineer.web_console.transport import create_console_app
from tests.web_console.test_transport import _Reader

AT = datetime(2026, 10, 12, tzinfo=UTC)


def _submit(
    store: FileConsoleOperationStore, index: int, *, project: str = "project_alpha"
) -> ConsoleOperation:
    return store.submit(
        intent=CreateProjectIntent(name=f"Project {index}", project_id=project),
        idempotency_key=f"summary-test-{index:04d}",
        requested_at=AT + timedelta(seconds=index),
    )


def _history(tmp_path: Path, count: int = 12) -> FileConsoleOperationStore:
    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    for index in range(count):
        _submit(store, index)
        running = store.claim_next(at=AT + timedelta(seconds=count + index))
        assert running is not None
        store.succeed(
            running.operation_id,
            expected=running.operation_sha256,
            result=ConsoleCommandResult(
                project_id="project_alpha", stage="CREATED", next_action="查看项目"
            ),
            at=AT + timedelta(seconds=count * 2 + index),
        )
    return store


def test_full_history_pagination_and_active_outside_first_page(tmp_path: Path) -> None:
    store = _history(tmp_path, 17)
    oldest_active = _submit(store, -1)
    query = OperationSummaryQuery(page_size=3, project_id="project_alpha")
    page = store.summary_page(query)
    assert page.active_complete and page.active == (OperationSummary.from_operation(oldest_active),)
    assert oldest_active.operation_id not in [item.operation_id for item in page.items]
    collected = list(page.items)
    while page.next_cursor is not None:
        page = store.summary_page(query.model_copy(update={"cursor": page.next_cursor}))
        collected.extend(page.items)
    assert len(collected) == page.total_count == 18
    assert len({item.operation_id for item in collected}) == 18
    assert collected == sorted(
        collected, key=lambda item: (item.requested_at, item.operation_id), reverse=True
    )
    assert collected[-1].operation_id == oldest_active.operation_id


def test_warm_projection_rechecks_complete_bytes_without_retaining_full_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _history(tmp_path)
    reads = Mock(wraps=store._current)
    monkeypatch.setattr(store, "_current", reads)
    page = store.summary_page(OperationSummaryQuery())
    assert reads.call_count == 12
    reads.reset_mock()
    from ai_software_engineer.team_workspace import _read_regular
    from ai_software_engineer.web_console import store as store_module

    byte_reads = Mock(wraps=_read_regular)
    monkeypatch.setattr(store_module, "_read_regular", byte_reads)
    assert store.summary_page(OperationSummaryQuery()) == page
    assert byte_reads.call_count == 36, (
        "every warm read still checks all 12 three-version histories"
    )
    assert reads.call_count == 0
    assert len(store._summary_cache.entries) == 12
    assert store._summary_cache.retained_bytes < 2 * 1024 * 1024
    assert all(
        isinstance(entry.summary, OperationSummary)
        for entry in store._summary_cache.entries.values()
    )
    # Complete old GET has deliberately not been migrated to this cache.
    assert len(store.list_current()) == 12
    assert reads.call_count == 12


@pytest.mark.parametrize(
    "change", ["same_mtime", "missing_parent", "symlink", "oversize", "directory_symlink"]
)
def test_cache_never_hides_changed_history(tmp_path: Path, change: str) -> None:
    store = _history(tmp_path, 1)
    store.summary_page(OperationSummaryQuery())
    path = next(store.root.glob("operation_*/000001.json"))
    stat = path.stat()
    if change == "same_mtime":
        old = path.read_bytes()
        new = old.replace(b'"team_test"', b'"team_fail"')
        assert len(new) == len(old) and new != old
        path.write_bytes(new)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif change in {"missing_parent", "symlink"}:
        original = tmp_path / "saved.json"
        path.rename(original)
        if change == "symlink":
            path.symlink_to(original)
    elif change == "directory_symlink":
        directory = path.parent
        original = tmp_path / "saved-operation"
        directory.rename(original)
        directory.symlink_to(original, target_is_directory=True)
    else:
        with path.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises((ValueError, ConsoleOperationConflict)):
        store.summary_page(OperationSummaryQuery())


def test_cursor_is_bound_to_inventory_scope_and_page_size(tmp_path: Path) -> None:
    store = _history(tmp_path, 3)
    query = OperationSummaryQuery(page_size=1, project_id="project_alpha")
    page = store.summary_page(query)
    assert page.next_cursor
    for update in ({"project_id": "project_other"}, {"page_size": 2}):
        with pytest.raises(StaleOperationCursor):
            store.summary_page(query.model_copy(update={"cursor": page.next_cursor, **update}))
    _submit(store, 4)
    with pytest.raises(StaleOperationCursor):
        store.summary_page(query.model_copy(update={"cursor": page.next_cursor}))


def test_filters_are_exact_and_summaries_have_no_authority_payload(tmp_path: Path) -> None:
    store = _history(tmp_path, 3)
    _submit(store, 10, project="project_other")
    page = store.summary_page(OperationSummaryQuery(project_id="project_alpha"))
    assert page.total_count == 3 and not page.active
    wire = page.model_dump(mode="json")
    encoded = json.dumps(wire)
    assert "intent" not in wire["items"][0]
    for prohibited in (
        "execution_baseline_plan",
        "approved_plan_sha256",
        "patch",
        "technical_facts",
    ):
        assert prohibited not in encoded
    assert len(encoded.encode()) < 64 * 1024


def test_cache_entry_and_bytes_caps_only_increase_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _history(tmp_path, 8)
    monkeypatch.setattr(store._summary_cache, "maximum_entries", 3)
    monkeypatch.setattr(store._summary_cache, "maximum_bytes", 2048)
    first = store.summary_page(OperationSummaryQuery())
    second = store.summary_page(OperationSummaryQuery())
    assert first == second and first.total_count == 8
    assert len(store._summary_cache.entries) <= 3
    assert store._summary_cache.retained_bytes <= 2048


def test_active_limit_rejects_without_truncation(tmp_path: Path) -> None:
    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    for index in range(65):
        _submit(store, index)
    with pytest.raises(ConsoleOperationConflict):
        store.summary_page(OperationSummaryQuery())


def test_typed_summary_schemas_match_generated_contract() -> None:
    root = Path(__file__).parents[2] / "schemas"
    for name, model in (
        ("summary", OperationSummary),
        ("page", OperationSummaryPage),
        ("cursor", OperationSummaryCursor),
        ("query", OperationSummaryQuery),
    ):
        schema = json.loads((root / f"console-operation-{name}.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        schema.pop("$id")
        schema.pop("$schema")
        assert schema == model.model_json_schema()


def test_http_manifest_etag_invalid_queries_and_stale_cursor(tmp_path: Path) -> None:
    store = _history(tmp_path, 3)
    console = ProjectConsole(store=store, executor=Mock())
    client = TestClient(
        create_console_app(console, _Reader(), team_id="team_test"),
        base_url="http://127.0.0.1:8765",
    )
    assert client.get("/api/v1/console").json()["operation_summary_contract_version"] == "v0.1"
    assert client.post("/api/v1/operation-summaries").status_code == 405
    response = client.get("/api/v1/operation-summaries?page_size=1")
    assert response.status_code == 200
    tag = response.headers["etag"]
    unchanged = client.get(
        "/api/v1/operation-summaries?page_size=1", headers={"If-None-Match": tag}
    )
    assert unchanged.status_code == 304 and not unchanged.content
    assert sum(len(k) + len(v) for k, v in unchanged.headers.items()) < 1024
    cursor = response.json()["next_cursor"]
    for suffix in (
        "page_size=51",
        "page_size=0",
        "page_size=oops",
        "delivery_id=delivery_abc",
        "unknown=1",
        "page_size=1&page_size=2",
        "cursor=bad",
    ):
        assert client.get(f"/api/v1/operation-summaries?{suffix}").status_code == 400
    _submit(store, 4)
    stale = client.get("/api/v1/operation-summaries", params={"page_size": 1, "cursor": cursor})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "OPERATION_CURSOR_STALE"
    # ETag cannot mask broken complete history.
    path = next(store.root.glob("operation_*/000001.json"))
    before = path.stat()
    old = path.read_bytes()
    tampered = old.replace(b'"team_test"', b'"team_fail"')
    assert tampered != old and len(tampered) == len(old)
    path.write_bytes(tampered)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    invalid = client.get("/api/v1/operation-summaries?page_size=1", headers={"If-None-Match": tag})
    assert invalid.status_code == 503 and "team_fail" not in invalid.text


def test_large_complete_plan_is_available_only_from_exact_get(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import weakref

    from tests.manager.test_execution_baseline import setup
    from tests.web_console.test_operation_budget import _result, _running_store

    (tmp_path / "fixture").mkdir()
    fixture = setup(tmp_path / "fixture")
    (fixture.worktree.path / "src/app.py").write_text('# "\\full draft"\n' * 18_000)
    plan = fixture.service.propose(fixture.target)
    store, operation_id, running_sha = _running_store(tmp_path / "console")
    complete = store.succeed(
        operation_id,
        expected=running_sha,
        result=_result().model_copy(
            update={
                "delivery_id": "delivery_created",
                "checkpoint_sha256": "a" * 64,
                "execution_baseline_plan": plan,
            }
        ),
        at=AT + timedelta(seconds=2),
    )
    complete_wire = complete.model_dump_json()
    assert len(complete_wire.encode()) > 1_000_000
    refs: list[weakref.ReferenceType[ConsoleOperation]] = []
    original = store._current

    def read(operation_id: str) -> ConsoleOperation | None:
        value = original(operation_id)
        if value is not None:
            refs.append(weakref.ref(value))
        return value

    monkeypatch.setattr(store, "_current", read)
    page = store.summary_page(OperationSummaryQuery())
    item = page.items[0]
    assert item.baseline_plan_sha256 == plan.plan_sha256
    assert item.baseline_purpose == plan.purpose.value
    assert len(page.model_dump_json().encode()) < 4096
    assert all(ref() is None for ref in refs), "cache cannot keep complete result models alive"
    assert store.get(operation_id).model_dump_json() == complete_wire


@pytest.mark.parametrize("include_plan", [False, True])
@pytest.mark.parametrize("independent_result", [False, True])
def test_completed_binding_purpose_is_scoped_reading_metadata_without_rewriting_history(
    tmp_path: Path, include_plan: bool, independent_result: bool
) -> None:
    from ai_software_engineer.web_console.models import ExecuteExecutionBaselineIntent
    from tests.manager.test_execution_baseline import authorize, setup

    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    fixture = setup(fixture_root)
    plan = fixture.service.propose(fixture.target)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    project_id = binding.scope.project_id
    store.submit(
        intent=ExecuteExecutionBaselineIntent(
            project_id=project_id,
            delivery_id="delivery_parent",
            expected_checkpoint_sha256="a" * 64,
            task_id=binding.task_id,
            expected_plan_sha256=plan.plan_sha256,
            reference="exact isolated source binding",
        ),
        idempotency_key="binding-summary",
        requested_at=AT,
    )
    running = store.claim_next(at=AT + timedelta(seconds=1))
    assert running is not None
    completed = store.succeed(
        running.operation_id,
        expected=running.operation_sha256,
        result=ConsoleCommandResult(
            project_id=project_id,
            delivery_id="delivery_independent" if independent_result else "delivery_parent",
            checkpoint_sha256="b" * 64,
            stage="EXECUTION_BASELINE_UPDATED",
            next_action="查看当前已保存的基线",
            execution_baseline_plan=plan if include_plan else None,
            execution_baseline_binding=binding,
        ),
        at=AT + timedelta(seconds=2),
    )
    history = {path: path.read_bytes() for path in store.root.glob("operation_*/*.json")}
    query = OperationSummaryQuery(project_id=project_id, delivery_id="delivery_parent")
    item = store.summary_page(query).items[0]
    assert item.baseline_purpose == (None if independent_result else binding.purpose.value)
    assert item.has_baseline_binding is not independent_result
    assert item.baseline_plan_sha256 == (
        plan.plan_sha256 if include_plan and not independent_result else None
    )
    assert store.summary_page(query).items == (item,), "warm summary keeps the same scoped purpose"
    assert store.get(completed.operation_id) == completed
    assert {path: path.read_bytes() for path in history} == history
    wire = item.to_wire()
    assert "execution_baseline_binding" not in wire and "execution_baseline_plan" not in wire


def test_cache_actual_512_entry_cap_and_full_overflow_pagination(tmp_path: Path) -> None:
    # Write valid terminal histories directly to the isolated fixture to avoid
    # O(n²) submit/claim admission scans while generating the boundary dataset.
    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    for index in range(520):
        queued = ConsoleOperation.queued(
            team_id="team_test",
            idempotency_key=f"capacity-{index:04d}",
            intent=CreateProjectIntent(name="Capacity", project_id="project_alpha"),
            requested_at=AT + timedelta(seconds=index),
        )
        running = queued.transition(
            queued.status.RUNNING, updated_at=AT + timedelta(seconds=index + 1)
        )
        terminal = running.transition(
            running.status.SUCCEEDED,
            updated_at=AT + timedelta(seconds=index + 2),
            result=ConsoleCommandResult(
                project_id="project_alpha", stage="CREATED", next_action="查看"
            ),
        )
        directory = store.root / queued.operation_id
        directory.mkdir()
        for operation in (queued, running, terminal):
            (directory / f"{operation.sequence:06d}.json").write_text(operation.model_dump_json())
    page = store.summary_page(OperationSummaryQuery(page_size=50))
    assert len(store._summary_cache.entries) == 512
    assert store._summary_cache.retained_bytes <= 2 * 1024 * 1024
    collected = list(page.items)
    while page.next_cursor:
        page = store.summary_page(OperationSummaryQuery(page_size=50, cursor=page.next_cursor))
        collected.extend(page.items)
    assert len(collected) == len({item.operation_id for item in collected}) == 520


def test_equal_timestamps_sort_ids_and_delivery_scope_uses_created_result(tmp_path: Path) -> None:
    from ai_software_engineer.web_console.models import CreateRequirementIntent

    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    for index in range(3):
        store.submit(
            intent=CreateRequirementIntent(
                project_id="project_alpha", name="Requirement", repository_roots=(str(tmp_path),)
            ),
            idempotency_key=f"same-time-{index}",
            requested_at=AT,
        )
        running = store.claim_next(at=AT)
        assert running is not None
        store.succeed(
            running.operation_id,
            expected=running.operation_sha256,
            at=AT,
            result=ConsoleCommandResult(
                project_id="project_alpha",
                delivery_id=f"delivery_created_{index}",
                checkpoint_sha256="a" * 64,
                stage="PRODUCT",
                next_action="核对需求",
            ),
        )
    page = store.summary_page(OperationSummaryQuery())
    assert [item.operation_id for item in page.items] == sorted(
        (item.operation_id for item in page.items), reverse=True
    )
    specific = store.summary_page(
        OperationSummaryQuery(project_id="project_alpha", delivery_id="delivery_created_1")
    )
    assert specific.total_count == 1
    assert specific.items[0].delivery_id == "delivery_created_1"
    assert specific.items[0].result_checkpoint_sha256 == "a" * 64


def test_failed_or_changed_replay_never_registers_the_failed_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _history(tmp_path, 1)
    original = store._summary_directory_digest
    calls = [0]

    def drift(directory: Path) -> str:
        calls[0] += 1
        result = original(directory)
        return "a" * 64 if calls[0] == 2 else result

    monkeypatch.setattr(store, "_summary_directory_digest", drift)
    with pytest.raises(ConsoleOperationConflict, match="during summary replay"):
        store.summary_page(OperationSummaryQuery())
    assert not store._summary_cache.entries and store._summary_cache.retained_bytes == 0
    monkeypatch.setattr(store, "_summary_directory_digest", original)
    assert store.summary_page(OperationSummaryQuery()).total_count == 1


def test_get_and_claim_cannot_use_reading_projection_as_authority(tmp_path: Path) -> None:
    store = _history(tmp_path, 1)
    store.summary_page(OperationSummaryQuery())
    path = next(store.root.glob("operation_*/000001.json"))
    path.write_bytes(path.read_bytes().replace(b'"team_test"', b'"team_fail"'))
    with pytest.raises((ValueError, ConsoleOperationConflict)):
        store.list_current()
    with pytest.raises((ValueError, ConsoleOperationConflict)):
        store.claim_next(at=AT + timedelta(seconds=10))


def test_foreign_team_and_conflicting_result_scope_fail_before_filter(tmp_path: Path) -> None:
    other = FileConsoleOperationStore(tmp_path / "operations", team_id="team_other")
    _submit(other, 1, project="project_other")
    reader = FileConsoleOperationStore(other.root, team_id="team_test")
    with pytest.raises(ConsoleOperationConflict):
        reader.summary_page(OperationSummaryQuery(project_id="project_alpha"))
    store = FileConsoleOperationStore(tmp_path / "conflicting", team_id="team_test")
    _submit(store, 1)
    running = store.claim_next(at=AT + timedelta(seconds=2))
    assert running is not None
    store.succeed(
        running.operation_id,
        expected=running.operation_sha256,
        at=AT + timedelta(seconds=3),
        result=ConsoleCommandResult(
            project_id="project_other", stage="CREATED", next_action="查看"
        ),
    )
    with pytest.raises(ValueError, match="scope differs"):
        store.summary_page(OperationSummaryQuery(project_id="project_alpha"))


def test_new_valid_operation_from_other_store_is_visible_and_bad_new_file_refused(
    tmp_path: Path,
) -> None:
    store = _history(tmp_path, 1)
    old = store.summary_page(OperationSummaryQuery())
    other = FileConsoleOperationStore(store.root, team_id=store.team_id)
    added = _submit(other, 5)
    latest = store.summary_page(OperationSummaryQuery())
    assert latest.inventory_sha256 != old.inventory_sha256
    assert latest.items[0].operation_id == added.operation_id
    assert latest.active == (OperationSummary.from_operation(added),)
    path = store.root / added.operation_id / "999999.json"
    path.write_text("{}")
    with pytest.raises((ValueError, ConsoleOperationConflict)):
        store.summary_page(OperationSummaryQuery())


def test_cursor_schema_validates_actual_wire_and_changed_completion_is_stale(
    tmp_path: Path,
) -> None:
    store = _history(tmp_path, 3)
    queued = _submit(store, 5)
    page = store.summary_page(OperationSummaryQuery(page_size=1))
    assert page.next_cursor
    root = Path(__file__).parents[2] / "schemas"
    for name, payload in (
        ("summary", page.items[0].model_dump(mode="json")),
        ("page", page.model_dump(mode="json")),
        ("cursor", OperationSummaryCursor.decode(page.next_cursor).model_dump(mode="json")),
    ):
        Draft202012Validator(
            json.loads((root / f"console-operation-{name}.schema.json").read_text())
        ).validate(payload)
    running = store.claim_next(at=AT + timedelta(seconds=8))
    assert running is not None and running.operation_id == queued.operation_id
    store.succeed(
        running.operation_id,
        expected=running.operation_sha256,
        at=AT + timedelta(seconds=9),
        result=ConsoleCommandResult(
            project_id="project_alpha", stage="CREATED", next_action="查看"
        ),
    )
    with pytest.raises(StaleOperationCursor):
        store.summary_page(OperationSummaryQuery(page_size=1, cursor=page.next_cursor))


def test_actual_delete_producer_roundtrips_summary_http_and_complete_bytes(tmp_path: Path) -> None:
    from ai_software_engineer.web_console.models import DeleteRequirementIntent
    from tests.web_console.test_manager import DELIVERY_ID, PROJECT_ID, _adapter

    adapter, _, entry = _adapter(tmp_path)
    intent = DeleteRequirementIntent(
        project_id=PROJECT_ID,
        delivery_id=DELIVERY_ID,
        expected_checkpoint_sha256=entry.checkpoint.checkpoint_sha256,
    )
    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    store.submit(intent=intent, idempotency_key="actual-delete-summary", requested_at=AT)
    running = store.claim_next(at=AT + timedelta(seconds=1))
    assert running is not None
    completed = store.succeed(
        running.operation_id,
        expected=running.operation_sha256,
        result=adapter.execute(intent),
        at=AT + timedelta(seconds=2),
    )
    assert completed.result is not None and completed.result.delivery_id is None
    before = {path: path.read_bytes() for path in store.root.glob("operation_*/*.json")}
    console = ProjectConsole(store=store, executor=Mock())
    client = TestClient(
        create_console_app(console, _Reader(), team_id="team_test"),
        base_url="http://127.0.0.1:8765",
    )
    response = client.get(
        "/api/v1/operation-summaries", params={"project_id": PROJECT_ID, "delivery_id": DELIVERY_ID}
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["delivery_id"] == DELIVERY_ID
    assert item["result_scope_relation"] == "NO_RESOURCE"
    assert item["result_delivery_id"] is None and item["result_stage"] is None
    assert item["next_step"] is None
    assert (
        client.get(
            "/api/v1/operation-summaries",
            params={"project_id": PROJECT_ID, "delivery_id": DELIVERY_ID},
            headers={"If-None-Match": response.headers["etag"]},
        ).status_code
        == 304
    )
    full = client.get(f"/api/v1/operations/{completed.operation_id}")
    assert full.json() == completed.to_wire()
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("result_delivery", ["delivery_native_independent", None])
def test_independent_same_project_result_is_not_current_requirement_semantics(
    tmp_path: Path, result_delivery: str | None
) -> None:
    from ai_software_engineer.web_console.models import (
        ConsoleApprovalRequest,
        ContinueDeliveryIntent,
    )

    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    intent = ContinueDeliveryIntent(
        project_id="project_alpha",
        delivery_id="delivery_parent",
        expected_checkpoint_sha256="a" * 64,
    )
    store.submit(intent=intent, idempotency_key="independent-result", requested_at=AT)
    running = store.claim_next(at=AT + timedelta(seconds=1))
    assert running is not None
    result = ConsoleCommandResult(
        project_id="project_alpha",
        delivery_id=result_delivery,
        checkpoint_sha256="b" * 64 if result_delivery else None,
        stage="BLOCKED",
        next_action="独立结果的下一步",
        diagnostic="独立结果的原因",
        approval=ConsoleApprovalRequest(
            kind="coder_recovery", title="独立结果审批", plan_sha256="c" * 64, facts=("结果现场",)
        )
        if result_delivery
        else None,
    )
    completed = store.succeed(
        running.operation_id,
        expected=running.operation_sha256,
        result=result,
        at=AT + timedelta(seconds=2),
    )
    page = store.summary_page(
        OperationSummaryQuery(project_id="project_alpha", delivery_id="delivery_parent")
    )
    assert page.total_count == 1
    item = page.items[0].model_dump(mode="json")
    assert item["result_scope_relation"] == "UNVERIFIED_RESOURCE"
    assert item["result_project_id"] == "project_alpha"
    assert item["result_delivery_id"] == result_delivery
    for name in (
        "result_stage",
        "result_checkpoint_sha256",
        "approval_kind",
        "approval_plan_sha256",
        "baseline_plan_sha256",
        "baseline_purpose",
        "task_id",
        "work_item_id",
        "summary",
        "next_step",
    ):
        assert item[name] is None, name
    assert item["has_baseline_binding"] is False
    assert item["intent_checkpoint_sha256"] == "a" * 64
    assert not store.summary_page(
        OperationSummaryQuery(project_id="project_alpha", delivery_id="delivery_native_independent")
    ).items
    assert store.get(completed.operation_id) == completed


def test_create_project_may_obtain_new_project_identity_only_from_its_result(
    tmp_path: Path,
) -> None:
    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    store.submit(
        intent=CreateProjectIntent(name="New identity"),
        idempotency_key="created-identity",
        requested_at=AT,
    )
    running = store.claim_next(at=AT + timedelta(seconds=1))
    assert running is not None
    store.succeed(
        running.operation_id,
        expected=running.operation_sha256,
        result=ConsoleCommandResult(
            project_id="project_created", stage="CREATED", next_action="查看新项目"
        ),
        at=AT + timedelta(seconds=2),
    )
    page = store.summary_page(OperationSummaryQuery(project_id="project_created"))
    assert page.total_count == 1
    assert page.items[0].result_scope_relation == "CREATED_RESOURCE"
    assert page.items[0].project_id == page.items[0].result_project_id == "project_created"
    assert page.items[0].result_stage == "CREATED"


def test_real_update_producer_snapshot_and_shipped_summary_refresh_select_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess
    from typing import cast

    from ai_software_engineer.config import ProductionConfig
    from ai_software_engineer.multi_directory.service import CreateRequirement
    from ai_software_engineer.team_view.reader import ProductionTeamReader
    from ai_software_engineer.web_console import ManagerConsoleAdapter
    from ai_software_engineer.web_console.manager import TeamConsoleHost
    from ai_software_engineer.web_console.models import UpdateRequirementIntent
    from tests.manager.test_requirement_retirement import _service
    from tests.web_console.test_requirement_deletion_entry import _Host

    service, root = _service(tmp_path, monkeypatch)
    original = service.create(
        CreateRequirement(name="Original draft", repository_roots=(str(root),))
    ).checkpoint
    config = ProductionConfig(
        platform_root=service.team.manifest.platform_root,
        team_id=service.team.manifest.team_id,
        team_name=service.team.manifest.name,
        default_project_id=service.project.manifest.project_id,
        default_project_name=service.project.manifest.name,
        model_routes=ProductionConfig.default().model_routes,
    )
    reader = ProductionTeamReader(config, {})
    store = FileConsoleOperationStore(tmp_path / "operations", team_id=config.team_id)
    adapter = ManagerConsoleAdapter(cast(TeamConsoleHost, _Host(service)))
    console = ProjectConsole(store=store, executor=adapter)
    intent = UpdateRequirementIntent(
        project_id=original.project_id,
        delivery_id=original.delivery_id,
        expected_checkpoint_sha256=original.checkpoint_sha256,
        name="Edited draft",
        repository_roots=(str(root),),
    )
    with TestClient(
        create_console_app(console, reader, team_id=config.team_id),
        base_url="http://127.0.0.1:8765",
    ) as client:
        before = client.get("/api/v1/team", params={"project_id": original.project_id}).json()
        assert [item["id"] for item in before["requests"]] == [original.delivery_id]
        store.submit(intent=intent, idempotency_key="actual-update-summary", requested_at=AT)
        running = store.claim_next(at=AT + timedelta(seconds=1))
        assert running is not None
        completed = store.succeed(
            running.operation_id,
            expected=running.operation_sha256,
            result=adapter.execute(intent),
            at=AT + timedelta(seconds=2),
        )
        assert completed.result is not None and completed.result.delivery_id
        after = client.get("/api/v1/team", params={"project_id": original.project_id}).json()
        assert [item["id"] for item in after["requests"]] == [completed.result.delivery_id]
        summaries = client.get(
            "/api/v1/operation-summaries", params={"project_id": original.project_id}
        )
        assert summaries.status_code == 200, summaries.text
        delivery_summaries = client.get(
            "/api/v1/operation-summaries",
            params={"project_id": original.project_id, "delivery_id": original.delivery_id},
        )
        assert delivery_summaries.status_code == 200, delivery_summaries.text
        item = delivery_summaries.json()["items"][0]
        assert item["result_scope_relation"] == "UNVERIFIED_RESOURCE"
        assert item["result_stage"] is None and item["approval_kind"] is None
        fixture = {
            "before": before,
            "after": after,
            "after_summary": client.get(
                "/api/v1/team-summary", params={"project_id": original.project_id}
            ).json(),
            "original": before["requests"][0],
            "replacement": after["requests"][0],
            "operation": client.get(f"/api/v1/operations/{completed.operation_id}").json(),
            "project_page": summaries.json(),
            "delivery_page": delivery_summaries.json(),
            "manifest": client.get("/api/v1/console").json(),
        }
    fixture_path = tmp_path / "actual-edit-navigation.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    result = subprocess.run(
        ["node", "tests/team_view/fixtures/operation-edit-navigation.cjs", str(fixture_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert store.get(completed.operation_id) == completed
    assert service.journal.current(original.delivery_id) == original
