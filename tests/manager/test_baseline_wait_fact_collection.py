"""Explicit source preparation seals a real stopped draft without restarting it."""

import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.codex_cli import CodexCliAgentAdapter
from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.execution_baseline import BaselinePurpose
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_production import (
    BaselineProposeCommand,
    ProductionBaselineFactCollector,
)
from ai_software_engineer.manager.dispatch import DispatchCommitRecord
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_delivery_wait import WaitQueue, seal_start
from tests.manager.test_wait_fact_collection import route
from tests.orchestration.test_native_continuation import NOW, Guard
from tests.orchestration.test_native_continuation_v2 import V2Fixture


class IdleQueue(WaitQueue):
    entered = False
    entries = 0

    @contextmanager
    def idle_task_scope(self, task_id: str) -> Iterator[DictCursor]:
        assert task_id == self.item.task_id
        assert not self.entered, "proposal must reuse its idle fence"
        self.entered = True
        self.entries += 1
        try:
            yield cast(DictCursor, object())
        finally:
            self.entered = False


@dataclass
class Prepared:
    native: V2Fixture
    queue: IdleQueue
    collector: ProductionBaselineFactCollector
    command: BaselineProposeCommand
    store: FileContinuationStore
    store_root: Path

    def collect(self, command: BaselineProposeCommand | None = None) -> None:
        self.collector.bind_proposal(command or self.command)
        with self.collector.execution_scope():
            self.collector._collect_proposal_facts(
                self.native.repository.get(self.native.task.id),
                self.native.repository.current_revision(self.native.task.id),
                self.queue.bound,
                self.native.request.source_revision,
                self.command.target_base_ref,
            )


@pytest.fixture
def prepared(
    tmp_path: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Prepared]:
    descriptor = os.open(tmp_path / "original.lock", os.O_RDWR | os.O_CREAT, 0o600)
    native = V2Fixture(tmp_path, Guard(descriptor))
    try:
        problem = getattr(request, "param", None)

        def forbidden_model(self: CodexCliAgentAdapter, request: AgentRequest) -> AgentResult:
            raise AssertionError("source preparation must never call a model")

        monkeypatch.setattr(CodexCliAgentAdapter, "run", forbidden_model)
        queue = IdleQueue(native)
        native.claim = queue.original
        seal_start(native, queue, tmp_path)
        continuation = native.service()
        assert continuation.started(native.request, native.worktree.path) is not None
        (native.worktree.path / "src/app.py").write_text("VALUE = 2\n")
        stopped = native.stopped()
        continuation.record_native_stop(
            native.request,
            native.worktree.path,
            process_stop=NativeProcessStop.create(
                **stopped.model_dump(exclude={"stopped_at", "stop_sha256"}),
                stopped_at=NOW + timedelta(seconds=1),
            ),
            output_present=problem == "output_present",
            cause=None if problem == "unknown_cause" else "local_execution_limit",
            original_error_code=None if problem == "unknown_cause" else AgentErrorCode.TIMEOUT,
        )
        root = tmp_path / "continuations" / native.task.id
        root.parent.mkdir(mode=0o700)
        store = FileContinuationStore.initialize(root, task_id=native.task.id)
        store.put_capture_start(native.store.capture_start(native.request.run_id))
        if problem != "missing_stop":
            store.put_capture_stop(native.store.capture_stop(native.request.run_id))
        native.guard.live = False
        task = native.repository.get(native.task.id)
        # This focused seam uses a prevalidated allocation identity; the public
        # Host regression independently covers dispatch/admission/schema checks.
        collector = ProductionBaselineFactCollector.__new__(ProductionBaselineFactCollector)
        collector.allocation = DispatchCommitRecord.model_construct(
            task=task, task_id=task.id, dispatch_sha256=native.scope.dispatch_sha256
        )
        collector.scope = EngineeringScope(
            team_id=native.scope.team_id,
            project_id=native.scope.project_id,
            repository_id=native.scope.repository_id,
            repository_root=native.task.repository,
        )
        collector.requirement_id = native.scope.requirement_id
        collector.state = tmp_path
        collector.route_root = tmp_path / "model-routes"
        collector.queue = cast(MySqlRoleQueue, queue)
        collector.git = native.git
        collector.guard = WorkerExecutionGuard()
        collector.locks_root = tmp_path / "idle-locks"
        collector._scope_held = False
        collector._idle_cursor = None
        collector._proposal_command = None
        collector.purpose = BaselinePurpose.SOURCE_REBIND
        if problem == "foreign_scope":
            collector.scope = collector.scope.model_copy(update={"project_id": "project_foreign"})
        if problem == "foreign_claim":
            queue.original = queue.original.model_copy(update={"worker_id": "worker_foreign"})
        command = BaselineProposeCommand(
            delivery_id=native.scope.requirement_id,
            task_id=task.id,
            expected_task_intent_sha256=task_intent_sha256(task),
            expected_task_revision=native.repository.current_revision(task.id),
            expected_work_item_id=queue.item.id,
            expected_source_revision=native.request.source_revision,
            target_base_ref=native.task.base_ref,
        )
        yield Prepared(native, queue, collector, command, store, root)
    finally:
        native.repository.close()
        os.close(descriptor)


def test_proposal_seals_the_real_receipt_once_without_queue_budget_or_git_mutation(
    prepared: Prepared,
) -> None:
    f = prepared
    before_task = f.native.repository.get(f.native.task.id)
    events = f.native.repository.list_events(f.native.task.id)
    item = f.queue.item
    inventory = capture_mutation_inventory(f.native.worktree.path)
    original = {p: p.read_bytes() for p in f.store_root.iterdir()}
    f.collect()
    receipt = f.store.get_receipt(f.native.request.run_id)
    assert receipt.request == f.native.request
    assert receipt.capture.to_capture().changed_paths == ("src/app.py",)
    f.collect()
    assert f.store.receipts_for_task(f.native.task.id) == (receipt,)
    assert f.queue.entries == 2 and not f.queue.entered
    assert f.native.repository.get(f.native.task.id) == before_task
    assert f.native.repository.list_events(f.native.task.id) == events
    assert f.queue.item == item and not f.queue.consumed
    assert capture_mutation_inventory(f.native.worktree.path) == inventory
    assert all(p.read_bytes() == body for p, body in original.items())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_id", "task_foreign"),
        ("expected_task_intent_sha256", "f" * 64),
        ("expected_task_revision", 999),
        ("expected_work_item_id", "work_foreign"),
        ("expected_source_revision", "f" * 40),
        ("delivery_id", "delivery_foreign"),
    ],
)
def test_stale_proposal_is_rejected_before_any_original_fact_is_published(
    prepared: Prepared, field: str, value: str | int
) -> None:
    f = prepared
    before = {p: p.read_bytes() for p in f.store_root.iterdir()}
    with pytest.raises(ValueError, match="事实已变化"):
        f.collect(f.command.model_copy(update={field: value}))
    assert {p: p.read_bytes() for p in f.store_root.iterdir()} == before
    assert not f.queue.consumed


@pytest.mark.parametrize("classification", ["EXECUTION_BASELINE_PAUSED", "ENVIRONMENT_UNAVAILABLE"])
def test_paused_and_preflight_waits_do_not_reinterpret_the_old_start(
    prepared: Prepared, classification: str
) -> None:
    f = prepared
    assert f.queue.item.wait_disposition is not None
    values = {**f.queue.item.wait_disposition.facts.to_wire(), "classification": classification}
    if classification == "EXECUTION_BASELINE_PAUSED":
        values["execution_baseline_sha256"] = "a" * 64
    disposition = decide_delivery_disposition(DeliveryFailureFacts.model_validate(values))
    f.queue.item = f.queue.item.model_copy(
        update={"wait_disposition": disposition, "wait_reason": disposition.reason}
    )
    f.collect()
    assert f.store.receipts_for_task(f.native.task.id) == ()


def test_capture_rejection_keeps_the_original_stop_and_source(prepared: Prepared) -> None:
    f = prepared
    (f.native.worktree.path / "src/app.py").write_text("password = 'fixture-private-value'\n")
    before = {p: p.read_bytes() for p in f.store_root.iterdir()}
    with pytest.raises(ContinuationRejected, match="封存"):
        f.collect()
    assert {p: p.read_bytes() for p in f.store_root.iterdir()} == before
    assert f.store.receipts_for_task(f.native.task.id) == ()
    assert not f.queue.consumed


def test_proposal_requires_the_existing_real_task_lock_and_idle_fence(prepared: Prepared) -> None:
    f = prepared
    f.collector.bind_proposal(f.command)
    with pytest.raises(ValueError, match="屏障"):
        f.collector._collect_proposal_facts(
            f.native.repository.get(f.native.task.id),
            f.native.repository.current_revision(f.native.task.id),
            f.queue.bound,
            f.native.request.source_revision,
            f.command.target_base_ref,
        )
    assert f.store.receipts_for_task(f.native.task.id) == ()


@pytest.mark.parametrize(
    "prepared",
    ["missing_stop", "unknown_cause", "output_present", "foreign_scope", "foreign_claim"],
    indirect=True,
)
def test_unusable_original_facts_never_create_a_receipt(prepared: Prepared) -> None:
    f = prepared
    before = {p: p.read_bytes() for p in f.store_root.iterdir()}
    with suppress(ContinuationRejected):
        f.collect()
    assert f.store.receipts_for_task(f.native.task.id) == ()
    assert {p: p.read_bytes() for p in f.store_root.iterdir()} == before
    assert not f.queue.consumed


def test_recovered_success_remains_success_and_cannot_become_a_baseline_retry(
    prepared: Prepared,
) -> None:
    f = prepared
    route(f.native, f.collector.state, success=True)
    f.collect()
    (outcome,) = KnowledgeRecordStore(f.collector.state / "invocations").list(
        "invocation-outcomes", DeliveryInvocationOutcome
    )
    assert outcome.result.status is AgentRunStatus.SUCCEEDED
    assert f.store.receipts_for_task(f.native.task.id) == ()
    with pytest.raises(ValueError, match="成功结果"):
        f.collector._reservation(f.native.repository.get(f.native.task.id), f.queue.item, ())
    assert not f.queue.consumed
