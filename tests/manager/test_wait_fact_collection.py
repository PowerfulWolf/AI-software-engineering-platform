"""Idle wait collection recovers sealed facts without a role invocation or approval."""

import json
import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from ai_software_engineer.agents.codex_cli import CodexCliAgentAdapter
from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, ModelRouteAttempt
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.domain.delivery_resolution import DeliveryWaitHandling, HandleDeliveryWait
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ContinuationScope,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.models import QueueClaim
from ai_software_engineer.work_queue.ports import QueueCorruption, QueueError, QueueNotFound
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.domain.factories import make_coder_progress_artifact
from tests.manager.test_delivery_wait import WaitQueue, seal_start, service
from tests.orchestration.test_native_continuation import NOW, Fixture, Guard
from tests.orchestration.test_native_continuation_v2 import V2Fixture


@pytest.fixture
def native(tmp_path: Path) -> Iterator[Fixture]:
    descriptor = os.open(tmp_path / "original.lock", os.O_RDWR | os.O_CREAT, 0o600)
    value = Fixture(tmp_path, Guard(descriptor))
    try:
        yield value
    finally:
        value.repository.close()
        os.close(descriptor)


def collector(
    native: Fixture,
    queue: WaitQueue,
    root: Path,
    *,
    expected_scope: ContinuationScope | None = None,
) -> DeliveryWaitFactCollector:
    return DeliveryWaitFactCollector(
        sidecar_state=root,
        route_root=root / "model-routes",
        scope=EngineeringScope(
            team_id=native.scope.team_id,
            project_id=native.scope.project_id,
            repository_id=native.scope.repository_id,
            repository_root=native.task.repository,
        ),
        expected_continuation_scope=expected_scope or native.scope,
        git=native.git,
        queue=queue,
    )


def result(native: Fixture, success: bool) -> AgentResult:
    if not success:
        return native.result()
    template = make_coder_progress_artifact()
    artifact = template.model_copy(
        update={
            "task_id": native.request.task_id,
            "source_revision": native.request.source_revision,
            "context_manifest_id": native.request.context_manifest_id,
            "producer": template.producer.model_copy(update={"run_id": native.request.run_id}),
        }
    )
    return AgentResult(
        **native.request.model_dump(
            include={
                "run_id",
                "task_id",
                "role",
                "attempt",
                "source_revision",
                "context_manifest_id",
            }
        ),
        status=AgentRunStatus.SUCCEEDED,
        artifact=artifact,
    )


def route(
    native: Fixture,
    root: Path,
    *,
    fallback: bool = False,
    success: bool = False,
    request: AgentRequest | None = None,
    index: int = 1,
    outcome: AgentResult | None = None,
) -> ModelRouteAttempt:
    attempt = ModelRouteAttempt.create(
        request=request or native.request,
        route_index=index,
        provider="codex",
        model="fixture-model",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=index),
        result=outcome or result(native, success),
        fallback=fallback,
    )
    return FileModelRouteAttemptStore(root / "model-routes").append(attempt)


@pytest.mark.parametrize("success", [False, True])
def test_final_route_recovers_the_original_result_once_without_model_calls(
    native: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, success: bool
) -> None:
    queue = WaitQueue(native)
    start = seal_start(native, queue, tmp_path)
    sealed = route(native, tmp_path, success=success)
    before_task = native.repository.get(native.task.id)
    before_events = native.repository.list_events(native.task.id)
    before_routes = {p: p.read_bytes() for p in (tmp_path / "model-routes").rglob("*.json")}

    def forbidden_call(self: CodexCliAgentAdapter, request: AgentRequest) -> AgentResult:
        raise AssertionError("fact collection must never invoke a model")

    monkeypatch.setattr(CodexCliAgentAdapter, "run", forbidden_call)
    entry = collector(native, queue, tmp_path)
    guard = WorkerExecutionGuard()
    assert guard.lease is None
    native.guard.live = False
    with guard.task_scope(tmp_path / "idle-locks", native.task.id):
        for _ in range(2):
            entry.collect(before_task, queue.bound, guard)
    outcomes = KnowledgeRecordStore(tmp_path / "invocations").list(
        "invocation-outcomes", DeliveryInvocationOutcome
    )
    assert len(outcomes) == 1
    outcome = outcomes[0]
    outcome.validate_integrity()
    assert outcome.start == start and outcome.result == sealed.result
    assert native.repository.get(native.task.id) == before_task
    assert native.repository.list_events(native.task.id) == before_events
    assert queue.consumed == [] and queue.accepted_artifacts == ()
    assert before_routes == {p: p.read_bytes() for p in (tmp_path / "model-routes").rglob("*.json")}


def test_fallback_only_routes_cannot_fabricate_a_final_result(
    native: Fixture, tmp_path: Path
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    route(native, tmp_path, fallback=True)
    guard = WorkerExecutionGuard()
    with guard.task_scope(tmp_path / "idle-locks", native.task.id):
        collector(native, queue, tmp_path).collect(
            native.repository.get(native.task.id), queue.bound, guard
        )
    assert (
        KnowledgeRecordStore(tmp_path / "invocations").list(
            "invocation-outcomes", DeliveryInvocationOutcome
        )
        == ()
    )
    assert queue.consumed == []


def test_complete_fallback_chain_uses_only_its_final_result(
    native: Fixture, tmp_path: Path
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    route(native, tmp_path, fallback=True)
    final = route(native, tmp_path, success=True, index=2)
    guard = WorkerExecutionGuard()
    with guard.task_scope(tmp_path / "idle-locks", native.task.id):
        collector(native, queue, tmp_path).collect(
            native.repository.get(native.task.id), queue.bound, guard
        )
    outcome = KnowledgeRecordStore(tmp_path / "invocations").get(
        "invocation-outcomes", queue.item.id, DeliveryInvocationOutcome
    )
    assert outcome.result == final.result


@pytest.mark.parametrize("drift", ["permissions", "inputs", "source", "sequence", "claim"])
def test_current_wait_or_complete_original_request_drift_is_rejected(
    native: Fixture, tmp_path: Path, drift: str
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    request = native.request
    if drift == "permissions":
        request = request.model_copy(
            update={"permissions": request.permissions.model_copy(update={"write_paths": ()})}
        )
    elif drift == "inputs":
        request = request.model_copy(update={"input_artifact_ids": ("art_other_plan",)})
    elif drift == "source":
        queue.bound = queue.bound.model_copy(
            update={"boundary": replace(queue.bound.boundary, source_revision="f" * 40)}
        )
    elif drift == "sequence":
        queue.item = queue.item.model_copy(update={"checkpoint_sequence": 999})
    else:
        queue.original = queue.original.model_copy(
            update={"work_item": queue.original.work_item.model_copy(update={"attempt": 2})}
        )
    route(native, tmp_path, request=request)
    guard = WorkerExecutionGuard()
    with (
        guard.task_scope(tmp_path / "idle-locks", native.task.id),
        pytest.raises(ContinuationRejected),
    ):
        collector(native, queue, tmp_path).collect(
            native.repository.get(native.task.id), queue.bound, guard
        )
    assert (
        KnowledgeRecordStore(tmp_path / "invocations").list(
            "invocation-outcomes", DeliveryInvocationOutcome
        )
        == ()
    )
    assert queue.consumed == []


def test_old_missing_capture_ledger_remains_waiting_without_new_records(
    native: Fixture, tmp_path: Path
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    entry = collector(native, queue, tmp_path)
    before = native.repository.get(native.task.id)
    guard = WorkerExecutionGuard()
    with guard.task_scope(tmp_path / "idle-locks", native.task.id):
        entry.collect(before, queue.bound, guard)
    assert not (tmp_path / "continuations").exists()
    assert (
        KnowledgeRecordStore(tmp_path / "invocations").list(
            "invocation-outcomes", DeliveryInvocationOutcome
        )
        == ()
    )
    assert native.repository.get(native.task.id) == before and queue.consumed == []


@pytest.mark.parametrize("field", ["requirement_id", "dispatch_sha256"])
def test_capture_scope_must_match_current_requirement_and_dispatch(
    native: Fixture, tmp_path: Path, field: str
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    continuation = native.service()
    assert continuation.started(native.request, native.worktree.path) is not None
    (native.worktree.path / "src/app.py").write_text("VALUE = 2\n")
    original_stop = native.stopped()
    stop = NativeProcessStop.create(
        **original_stop.model_dump(exclude={"stopped_at", "stop_sha256"}),
        stopped_at=NOW + timedelta(seconds=1),
    )
    continuation.record_native_stop(
        native.request,
        native.worktree.path,
        process_stop=stop,
        output_present=False,
        cause="local_execution_limit",
        original_error_code=AgentErrorCode.TIMEOUT,
    )
    capture_root = tmp_path / "continuations" / native.task.id
    capture_root.parent.mkdir(mode=0o700)
    capture_store = FileContinuationStore.initialize(capture_root, task_id=native.task.id)
    capture_store.put_capture_start(native.store.capture_start(native.request.run_id))
    capture_store.put_capture_stop(native.store.capture_stop(native.request.run_id))
    expected = native.scope.model_copy(
        update={field: "delivery_foreign_scope" if field == "requirement_id" else "f" * 64}
    )
    guard = WorkerExecutionGuard()
    with (
        guard.task_scope(tmp_path / "idle-locks", native.task.id),
        pytest.raises(ContinuationRejected, match="当前项目与原调用"),
    ):
        collector(native, queue, tmp_path, expected_scope=expected).collect(
            native.repository.get(native.task.id), queue.bound, guard
        )
    with (
        guard.task_scope(tmp_path / "idle-locks", native.task.id),
        pytest.raises(ContinuationRejected, match="当前项目与原调用"),
    ):
        collector(native, queue, tmp_path, expected_scope=expected).observe_stop(
            native.repository.get(native.task.id), queue.bound, guard
        )
    assert capture_store.receipts_for_task(native.task.id) == ()
    assert queue.consumed == []
    assert (native.worktree.path / "src/app.py").read_text() == "VALUE = 2\n"


@pytest.mark.parametrize(
    "problem", ["claim", "lease", "worker", "task", "process_group", "no_lock", "heartbeat"]
)
def test_stop_observation_rechecks_exact_authority_and_current_process_state(
    native: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    queue = WaitQueue(native)
    native.claim = queue.original
    seal_start(native, queue, tmp_path)
    continuation = native.service()
    assert continuation.started(native.request, native.worktree.path) is not None
    original_stop = native.stopped()
    continuation.record_native_stop(
        native.request,
        native.worktree.path,
        process_stop=NativeProcessStop.create(
            **original_stop.model_dump(exclude={"stopped_at", "stop_sha256"}),
            stopped_at=NOW + timedelta(seconds=1),
        ),
        output_present=False,
        cause="local_execution_limit",
        original_error_code=AgentErrorCode.TIMEOUT,
    )
    root = tmp_path / "continuations" / native.task.id
    root.parent.mkdir(mode=0o700)
    store = FileContinuationStore.initialize(root, task_id=native.task.id)
    store.put_capture_start(native.store.capture_start(native.request.run_id))
    store.put_capture_stop(native.store.capture_stop(native.request.run_id))
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    task = native.repository.get(native.task.id)
    if problem == "claim":
        queue.original = queue.original.model_copy(
            update={
                "model_selection": queue.original.model_selection.model_copy(
                    update={"model": "other"}
                )
            }
        )
    elif problem == "lease":
        queue.original = queue.original.model_copy(
            update={
                "lease": queue.original.lease.model_copy(
                    update={"acquired_at": NOW - timedelta(seconds=1)}
                )
            }
        )
    elif problem == "worker":
        queue.original = queue.original.model_copy(update={"worker_id": "worker_other"})
    elif problem == "heartbeat":
        queue.original = queue.original.model_copy(
            update={
                "lease": queue.original.lease.model_copy(
                    update={"expires_at": NOW + timedelta(hours=2)}
                )
            }
        )
    elif problem == "task":
        task = task.model_copy(update={"attempts": 2})
    elif problem == "process_group":
        monkeypatch.setattr(
            "ai_software_engineer.orchestration.continuation.os.killpg", lambda *_: None
        )
    entry = collector(native, queue, tmp_path)
    guard = WorkerExecutionGuard()
    if problem == "no_lock":
        with pytest.raises(ContinuationRejected):
            entry.observe_stop(task, queue.bound, guard)
    elif problem == "heartbeat":
        with guard.task_scope(tmp_path / "idle-locks", task.id):
            assert entry.observe_stop(task, queue.bound, guard) == store.capture_stop(
                native.request.run_id
            )
    else:
        with (
            guard.task_scope(tmp_path / "idle-locks", task.id),
            pytest.raises(ContinuationRejected),
        ):
            entry.observe_stop(task, queue.bound, guard)
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}
    assert store.receipts_for_task(task.id) == ()
    assert queue.consumed == []


def test_collector_requires_the_idle_task_lock_before_reading_or_publishing(
    native: Fixture, tmp_path: Path
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    route(native, tmp_path)
    with pytest.raises(ContinuationRejected, match="独占任务锁"):
        collector(native, queue, tmp_path).collect(
            native.repository.get(native.task.id), queue.bound, WorkerExecutionGuard()
        )


@pytest.mark.parametrize("field", ["source_revision", "attempt", "context_manifest_id"])
def test_route_result_cannot_change_original_source_attempt_or_context(
    native: Fixture, tmp_path: Path, field: str
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    changed = {"source_revision": "f" * 40, "attempt": 2, "context_manifest_id": "ctx_" + "f" * 64}
    route(native, tmp_path, outcome=native.result().model_copy(update={field: changed[field]}))
    guard = WorkerExecutionGuard()
    with (
        guard.task_scope(tmp_path / "idle-locks", native.task.id),
        pytest.raises(ContinuationRejected, match="完整校验"),
    ):
        collector(native, queue, tmp_path).collect(
            native.repository.get(native.task.id), queue.bound, guard
        )
    assert (
        KnowledgeRecordStore(tmp_path / "invocations").list(
            "invocation-outcomes", DeliveryInvocationOutcome
        )
        == ()
    )


class MissingClaimQueue(WaitQueue):
    def __init__(self, native: Fixture, error: type[QueueError]) -> None:
        super().__init__(native)
        self.error = error

    def original_claim(self, lease_id: str) -> QueueClaim:
        raise self.error("original historical claim unavailable")


@pytest.mark.parametrize("error", [QueueNotFound, QueueCorruption])
def test_missing_original_authority_returns_a_platform_handling_report_without_resolution(
    native: Fixture, tmp_path: Path, error: type[QueueError]
) -> None:
    queue = MissingClaimQueue(native, error)
    seal_start(native, queue, tmp_path)
    entry = service(native, queue, tmp_path)
    entry.fact_collector = collector(native, queue, tmp_path).collect
    before = native.repository.get(native.task.id)
    handling = entry.handle(HandleDeliveryWait.model_validate(queue.command().to_wire()))
    assert handling.status == "PLATFORM_ATTENTION" and handling.resolution is None
    assert "校验失败" in handling.summary
    assert native.repository.get(native.task.id) == before and queue.consumed == []
    assert (
        KnowledgeRecordStore(tmp_path / "invocations").list(
            "invocation-outcomes", DeliveryInvocationOutcome
        )
        == ()
    )


def test_collector_completes_the_durable_capture_ledger_and_replays_without_a_live_worker(
    native: Fixture, tmp_path: Path
) -> None:
    queue = WaitQueue(native)
    native.claim = queue.original
    seal_start(native, queue, tmp_path)
    continuation = native.service()
    assert continuation.started(native.request, native.worktree.path) is not None
    (native.worktree.path / "src/app.py").write_text("VALUE = 2\n")
    original_stop = native.stopped()
    continuation.record_native_stop(
        native.request,
        native.worktree.path,
        process_stop=NativeProcessStop.create(
            **original_stop.model_dump(exclude={"stopped_at", "stop_sha256"}),
            stopped_at=NOW + timedelta(seconds=1),
        ),
        output_present=False,
        cause="local_execution_limit",
        original_error_code=AgentErrorCode.TIMEOUT,
    )
    store_root = tmp_path / "continuations" / native.task.id
    store_root.parent.mkdir(mode=0o700)
    store = FileContinuationStore.initialize(store_root, task_id=native.task.id)
    store.put_capture_start(native.store.capture_start(native.request.run_id))
    store.put_capture_stop(native.store.capture_stop(native.request.run_id))
    original = {p.name: p.read_bytes() for p in store_root.iterdir()}
    native.guard.live = False
    before = native.repository.get(native.task.id)
    guard = WorkerExecutionGuard()
    entry = collector(native, queue, tmp_path)
    with guard.task_scope(tmp_path / "idle-locks", native.task.id):
        entry.collect(before, queue.bound, guard)
        receipt = store.get_receipt(native.request.run_id)
        entry.collect(before, queue.bound, guard)
    assert store.get_receipt(native.request.run_id) == receipt
    assert receipt.capture.to_capture().changed_paths == ("src/app.py",)
    assert all((store_root / name).read_bytes() == body for name, body in original.items())
    assert native.repository.get(native.task.id) == before and queue.consumed == []


def test_rejected_full_source_capture_preserves_verified_stop_and_explains_the_real_wait(
    tmp_path: Path,
) -> None:
    descriptor = os.open(tmp_path / "original.lock", os.O_RDWR | os.O_CREAT, 0o600)
    native = V2Fixture(tmp_path, Guard(descriptor))
    try:
        queue = WaitQueue(native)
        native.claim = queue.original
        seal_start(native, queue, tmp_path)
        continuation = native.service()
        assert continuation.started(native.request, native.worktree.path) is not None
        # Legitimately rejected source: never copy this body into a report or receipt.
        sensitive = "password = 'fixture-private-value'\n"
        (native.worktree.path / "src/new.py").write_text(sensitive)
        original_stop = native.stopped()
        continuation.record_native_stop(
            native.request,
            native.worktree.path,
            process_stop=NativeProcessStop.create(
                **original_stop.model_dump(exclude={"stopped_at", "stop_sha256"}),
                stopped_at=NOW + timedelta(seconds=1),
            ),
            output_present=False,
            cause="local_execution_limit",
            original_error_code=AgentErrorCode.TIMEOUT,
        )
        store_root = tmp_path / "continuations" / native.task.id
        store_root.parent.mkdir(mode=0o700)
        store = FileContinuationStore.initialize(store_root, task_id=native.task.id)
        store.put_capture_start(native.store.capture_start(native.request.run_id))
        stop = store.put_capture_stop(native.store.capture_stop(native.request.run_id))
        original = {p.name: p.read_bytes() for p in store_root.iterdir()}
        native.guard.live = False
        before_task = native.repository.get(native.task.id)
        before_events = native.repository.list_events(native.task.id)
        entry = service(native, queue, tmp_path)
        facts = collector(native, queue, tmp_path)
        entry.fact_collector = facts.collect
        entry.stop_observer = facts.observe_stop
        command = HandleDeliveryWait.model_validate(queue.command().to_wire())
        handling = entry.handle(command)
        assert handling.status == "PLATFORM_ATTENTION" and handling.resolution is None
        assert handling.collection_failed
        assert handling.to_wire().get("collection_failure") == "WORKSPACE_CAPTURE_REJECTED"
        assert handling.investigation.process_stop_sha256 == stop.process_stop.stop_sha256
        assert handling.investigation.retry_cause == "local_execution_limit"
        assert handling.investigation.missing == ("OUTCOME_UNKNOWN", "CHECKPOINT_UNAVAILABLE")
        assert handling.investigation.permitted_resolutions == ()
        assert "本地执行时限" in handling.summary and "封存" in handling.summary
        assert "平台修复后重新处理" in handling.user_action
        assert "fixture-private-value" not in str(handling.to_wire())
        assert "src/new.py" not in str(handling.to_wire())
        for schema_name in ("engineering-wait-resolution", "console-operation"):
            schema = json.loads(Path(f"schemas/{schema_name}.schema.json").read_text())
            validator = Draft202012Validator(
                {"$defs": schema["$defs"], "$ref": "#/$defs/DeliveryWaitHandling"}
            )
            validator.validate(handling.to_wire())
            for invalid in (
                {**handling.to_wire(), "collection_failed": False},
                {**handling.to_wire(), "collection_failure": "unknown_internal_exception"},
                {
                    **handling.to_wire(),
                    "investigation": {
                        **handling.investigation.to_wire(),
                        "process_stop_sha256": None,
                    },
                },
                {
                    **handling.to_wire(),
                    "investigation": {
                        **handling.investigation.to_wire(),
                        "missing": ["OUTCOME_UNKNOWN"],
                    },
                },
            ):
                with pytest.raises(ValidationError):
                    DeliveryWaitHandling.model_validate(invalid)
                with pytest.raises(SchemaValidationError):
                    validator.validate(invalid)
        assert store.receipts_for_task(native.task.id) == ()
        inspected = entry.inspect(queue.command())
        assert inspected.process_stop_sha256 == stop.process_stop.stop_sha256
        assert inspected.missing == ("OUTCOME_UNKNOWN", "CHECKPOINT_UNAVAILABLE")
        assert inspected.permitted_resolutions == ()
        assert entry.handle(command) == handling
        assert original == {p.name: p.read_bytes() for p in store_root.iterdir()}
        assert native.repository.get(native.task.id) == before_task
        assert native.repository.list_events(native.task.id) == before_events
        assert queue.consumed == []
        assert (native.worktree.path / "src/new.py").read_text() == sensitive
    finally:
        native.repository.close()
        os.close(descriptor)
