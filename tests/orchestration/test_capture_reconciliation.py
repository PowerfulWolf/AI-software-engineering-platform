"""Historical capture reconciliation preserves real Git facts, never new execution authority."""

import fcntl
import os
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import AgentErrorCode, AgentRequest
from ai_software_engineer.git import GitWorkspaceError, WorkspacePolicyError
from ai_software_engineer.git.mutation import WorkspaceMutationInventory, capture_mutation_inventory
from ai_software_engineer.orchestration import capture_reconciliation
from ai_software_engineer.orchestration.capture_reconciliation import reconcile_capture
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.git.test_worktree import _git
from tests.orchestration.test_native_continuation import NOW, Fixture, Guard
from tests.orchestration.test_native_continuation_v2 import V2Fixture


@pytest.fixture(params=["v1", "v2"])
def native(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Fixture]:
    descriptor = os.open(tmp_path / "original.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    value = (
        Fixture(tmp_path, Guard(descriptor))
        if request.param == "v1"
        else V2Fixture(tmp_path, Guard(descriptor))
    )
    try:
        yield value
    finally:
        value.repository.close()
        os.close(descriptor)


def observations(
    native: Fixture, *, changed: bool = True, unknown: bool = False, output: bool = False
) -> tuple[ExecutionCaptureStart, ExecutionCaptureStop]:
    service = native.service()
    assert service.started(native.request, native.worktree.path) is not None
    if changed:
        (native.worktree.path / "src/app.py").write_text("VALUE = 2\n")
    original_stop = native.stopped()
    stopped = NativeProcessStop.create(
        **original_stop.model_dump(exclude={"stopped_at", "stop_sha256"}),
        stopped_at=NOW + timedelta(seconds=1),
    )
    service.record_native_stop(
        native.request,
        native.worktree.path,
        process_stop=stopped,
        output_present=output,
        cause=None if unknown else "local_execution_limit",
        original_error_code=None if unknown else AgentErrorCode.TIMEOUT,
    )
    return native.store.capture_start(native.request.run_id), native.store.capture_stop(
        native.request.run_id
    )


def reconcile(
    native: Fixture,
    start: ExecutionCaptureStart,
    stop: ExecutionCaptureStop,
    guard: WorkerExecutionGuard,
    *,
    accepted: bool = False,
) -> ExecutionInterruptionReceipt:
    def validate_inputs(request: AgentRequest) -> None:
        if request != native.request:
            raise ContinuationRejected("original request no longer matches its sealed inputs")

    return reconcile_capture(
        start=start,
        stop=stop,
        task=native.repository.get(native.task.id),
        task_revision=native.repository.current_revision(native.task.id),
        historical_claim=native.claim,
        store=native.store,
        git=native.git,
        task_lock=guard,
        validate_inputs=validate_inputs,
        has_output=lambda request: accepted,
        clock=lambda: NOW + timedelta(seconds=2),
    )


def test_durable_start_and_real_stop_complete_a_receipt_with_no_active_original_claim(
    native: Fixture, tmp_path: Path
) -> None:
    start, stop = observations(native)
    before_task = native.repository.get(native.task.id)
    before_events = native.repository.list_events(native.task.id)
    start_bytes = {p.name: p.read_bytes() for p in native.store_root.iterdir()}
    native.guard.live = False
    guard = WorkerExecutionGuard()
    assert guard.lease is None
    with guard.task_scope(tmp_path / "idle-locks", native.task.id):
        receipt = reconcile(native, start, stop, guard)
        first_bytes = {p.name: p.read_bytes() for p in native.store_root.iterdir()}
        assert reconcile(native, start, stop, guard) == receipt
    receipt.validate_integrity()
    assert receipt.request == native.request
    assert receipt.original_work_item_id == native.claim.work_item.id
    assert receipt.claim_lease_id == native.claim.lease.id
    assert receipt.inventory_before == start.inventory_before
    assert receipt.inventory_after == capture_mutation_inventory(native.worktree.path)
    assert receipt.capture.to_capture().changed_paths == ("src/app.py",)
    assert "VALUE = 2" in receipt.capture.patch
    assert first_bytes == {p.name: p.read_bytes() for p in native.store_root.iterdir()}
    assert all(
        (native.store_root / name).read_bytes() == data for name, data in start_bytes.items()
    )
    assert native.repository.get(native.task.id) == before_task
    assert native.repository.list_events(native.task.id) == before_events
    assert native.store.admissions_for_task(native.task.id) == ()
    assert _git(native.worktree.path, "rev-parse", "HEAD") == native.request.source_revision


@pytest.mark.parametrize(
    "problem", ["unknown_cause", "output_observed", "output_accepted", "no_lock"]
)
def test_unknown_cause_existing_output_or_missing_lock_cannot_create_a_receipt(
    native: Fixture, tmp_path: Path, problem: str
) -> None:
    start, stop = observations(
        native, unknown=problem == "unknown_cause", output=problem == "output_observed"
    )
    guard = WorkerExecutionGuard()
    if problem == "no_lock":
        with pytest.raises(ContinuationRejected):
            reconcile(native, start, stop, guard)
    else:
        with (
            guard.task_scope(tmp_path / "idle-locks", native.task.id),
            pytest.raises(ContinuationRejected),
        ):
            reconcile(native, start, stop, guard, accepted=problem == "output_accepted")
    assert native.store.receipts_for_task(native.task.id) == ()
    assert (native.worktree.path / "src/app.py").read_text() == "VALUE = 2\n"


@pytest.mark.parametrize("problem", ["permission", "head", "source", "claim"])
def test_permissions_head_source_and_original_claim_drift_refuse_capture(
    native: Fixture, tmp_path: Path, problem: str
) -> None:
    start, stop = observations(native)
    if problem == "permission":
        (native.worktree.path / "not-authorized.txt").write_text("must remain preserved\n")
    elif problem == "head":
        _git(native.worktree.path, "add", "src/app.py")
        _git(native.worktree.path, "commit", "-m", "fixture unauthorized head movement")
    elif problem == "source":
        native.request = native.request.model_copy(update={"source_revision": "f" * 40})
    else:
        native.claim = native.claim.model_copy(
            update={
                "model_selection": native.claim.model_selection.model_copy(
                    update={"model": "different"}
                )
            }
        )
    guard = WorkerExecutionGuard()
    with (
        guard.task_scope(tmp_path / "idle-locks", native.task.id),
        pytest.raises((ContinuationRejected, GitWorkspaceError, WorkspacePolicyError)),
    ):
        reconcile(native, start, stop, guard)
    assert native.store.receipts_for_task(native.task.id) == ()


def test_worktree_change_at_the_final_recheck_preserves_draft_without_a_receipt(
    native: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, stop = observations(native)
    checks = 0

    def race(root: Path) -> WorkspaceMutationInventory:
        nonlocal checks
        checks += 1
        if checks == 2:
            (native.worktree.path / "src/app.py").write_text("VALUE = 3\n")
        return capture_mutation_inventory(root)

    monkeypatch.setattr(capture_reconciliation, "capture_mutation_inventory", race)
    guard = WorkerExecutionGuard()
    with (
        guard.task_scope(tmp_path / "idle-locks", native.task.id),
        pytest.raises(ContinuationRejected, match="现场已变化"),
    ):
        reconcile(native, start, stop, guard)
    assert checks == 2
    assert native.store.receipts_for_task(native.task.id) == ()
    assert (native.worktree.path / "src/app.py").read_text() == "VALUE = 3\n"


@pytest.mark.parametrize("cache", [False, True])
def test_v2_complete_clean_or_cache_only_observation_keeps_exact_accounting(
    native: Fixture, tmp_path: Path, cache: bool
) -> None:
    start, stop = observations(native, changed=False)
    if cache:
        (native.worktree.path / ".pytest_cache").mkdir()
        (native.worktree.path / ".pytest_cache" / "state").write_text("cache only\n")
    before = native.repository.get(native.task.id)
    guard = WorkerExecutionGuard()
    with guard.task_scope(tmp_path / "idle-locks", native.task.id):
        if native.task.interruption_continuation_policy is not None and (
            native.task.interruption_continuation_policy.schema_version == "v1"
        ):
            with pytest.raises(ContinuationRejected):
                reconcile(native, start, stop, guard)
            assert native.store.receipts_for_task(native.task.id) == ()
        else:
            receipt = reconcile(native, start, stop, guard)
            assert receipt.capture.to_capture().changed_paths == ()
            assert receipt.mutation_paths == ((".pytest_cache/state",) if cache else ())
            assert receipt.cause == "local_execution_limit"
            assert receipt.process_stop == stop.process_stop
            assert native.store.admissions_for_task(native.task.id) == ()
    assert native.repository.get(native.task.id) == before
    assert _git(native.worktree.path, "rev-parse", "HEAD") == native.request.source_revision
