"""Deletion cannot strand a partial Operation chain across restart."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.web_console.models import ConsoleCommandResult, DeleteRequirementIntent
from ai_software_engineer.web_console.store import (
    ConsoleOperationNotFound,
    FileConsoleOperationStore,
)
from ai_software_engineer.web_console.summary_models import OperationSummaryQuery
from tests.web_console.test_core import _create_intent


def test_delete_cleanup_interruption_is_readable_and_restartable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_software_engineer.multi_directory.purge as purge
    from ai_software_engineer.multi_directory.purge import RequirementPurger
    from ai_software_engineer.multi_directory.service import CreateRequirement
    from tests.manager.test_requirement_retirement import _service

    service, repository_root = _service(tmp_path / "platform", monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="unrelated preview", repository_roots=(str(repository_root),))
    ).checkpoint
    root = service.team.directory("work-items") / "console-operations"
    store = FileConsoleOperationStore(root, team_id=service.team.manifest.team_id)
    at = datetime(2026, 10, 13, tzinfo=UTC)
    queued = store.submit(
        intent=DeleteRequirementIntent(
            project_id="project_test",
            delivery_id="delivery_multi_" + "a" * 40,
            expected_checkpoint_sha256="1" * 64,
        ),
        idempotency_key="delete-interruption",
        requested_at=at,
    )
    running = store.claim_next(at=at)
    assert running is not None
    original = purge._unlink_sealed
    count = 0

    def fail_second(base: Path, item: purge.PurgeFile) -> None:
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("simulated process stop")
        original(base, item)

    monkeypatch.setattr(purge, "_unlink_sealed", fail_second)
    with pytest.raises(OSError, match="simulated"):
        store.succeed(
            running.operation_id,
            expected=running.operation_sha256,
            result=ConsoleCommandResult(
                project_id="project_test",
                stage="REQUIREMENT_DELETED",
                next_action="需求数据已删除。",
            ),
            at=at,
        )
    pending_root = root.parent / "console-deletion-pending"
    before = {path: path.read_bytes() for path in pending_root.glob("*.json")}
    import json

    from jsonschema import Draft202012Validator

    schema = json.loads(Path("schemas/console-deletion-cleanup.schema.json").read_text())
    for payload in before.values():
        Draft202012Validator(schema).validate(json.loads(payload))
    RequirementPurger(service.project).prepare(checkpoint, {}, native_ids={}, persist=False)
    assert {path: path.read_bytes() for path in pending_root.glob("*.json")} == before
    assert (root / queued.operation_id).exists()
    readonly = FileConsoleOperationStore(
        root, team_id=service.team.manifest.team_id, read_only=True
    )
    assert readonly.get(queued.operation_id) == running
    assert readonly.summary_page(OperationSummaryQuery()).total_count == 1
    monkeypatch.setattr(purge, "_unlink_sealed", original)
    restarted = FileConsoleOperationStore(root, team_id=service.team.manifest.team_id)
    assert restarted.interrupt_running(at=at) == ()
    assert restarted.summary_page(OperationSummaryQuery()).total_count == 0
    with pytest.raises(ConsoleOperationNotFound):
        restarted.get(queued.operation_id)
    other = restarted.submit(
        intent=_create_intent(tmp_path), idempotency_key="unrelated-create", requested_at=at
    )
    claimed = restarted.claim_next(at=at)
    assert claimed is not None and claimed.operation_id == other.operation_id
    assert not tuple((root.parent / "console-deletion-pending").glob("*.json"))


def test_parent_and_native_terminal_cleanup_restarts_without_global_chain_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_software_engineer.multi_directory.purge as purge
    from ai_software_engineer.web_console.models import ProductReplyIntent

    root = tmp_path / "console-operations"
    store = FileConsoleOperationStore(root, team_id="team_test")
    at = datetime(2026, 10, 13, tzinfo=UTC)
    ids = set()
    for index in range(2):
        queued = store.submit(
            intent=ProductReplyIntent(
                project_id="project_test",
                delivery_id="delivery_multi_" + str(index) * 40,
                expected_checkpoint_sha256="a" * 64,
                message="owned operation",
            ),
            idempotency_key="history-" + str(index),
            requested_at=at,
        )
        running = store.claim_next(at=at)
        assert running is not None
        store.fail(
            running.operation_id,
            expected=running.operation_sha256,
            error_code="FIXTURE",
            error_summary="stopped",
            at=at,
        )
        ids.add(queued.operation_id)
    original = purge._unlink_sealed
    calls = 0

    def fail_second(base: Path, item: purge.PurgeFile) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("terminal cleanup stop")
        original(base, item)

    monkeypatch.setattr(purge, "_unlink_sealed", fail_second)
    with store._locked(), pytest.raises(OSError, match="terminal cleanup"):
        store.remove_terminal_operations(ids)
    assert (
        len(FileConsoleOperationStore(root, team_id="team_test", read_only=True).list_current())
        == 2
    )
    monkeypatch.setattr(purge, "_unlink_sealed", original)
    restarted = FileConsoleOperationStore(root, team_id="team_test")
    assert restarted.interrupt_running(at=at) == ()
    with restarted._locked():
        restarted.remove_terminal_operations(ids)
    assert restarted.list_current() == ()
