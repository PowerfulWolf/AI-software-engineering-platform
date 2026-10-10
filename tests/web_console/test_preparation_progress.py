"""Bounded recovery preparation observations have no execution authority."""

import asyncio
import fcntl
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole, Task
from ai_software_engineer.git import GitWorktreeManager, WorktreeRef
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.manager.preparation import PrepareProjectResult, PrepareProjectStatus
from ai_software_engineer.manager.production_backend import ProductionProjectDeliveryBackend
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.entry import NativeRecoveryEntry
from ai_software_engineer.recovery.preparation_progress import (
    AuthorizationEvidence,
    AuthorizationRecorded,
    PreparationProgressScope,
    PreparationProgressView,
    PreparationRecord,
    observe_recovery_preparation,
    preparation_scope,
    record_authorization,
    record_dispatch_committed,
    record_execution_claimed,
    record_seed_verified,
    record_task_sealed,
    seal_preparation_record,
)
from ai_software_engineer.recovery.records import RecoverySeedRecord
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.runtime import RuntimeSession
from ai_software_engineer.store import MySqlTaskRepository, TaskNotFound
from ai_software_engineer.web_console.core import ProjectConsole
from ai_software_engineer.web_console.models import (
    ConsoleCommandResult,
    ConsoleIntent,
    ConsoleOperation,
    ConsoleOperationStatus,
    ContinueDeliveryIntent,
)
from ai_software_engineer.web_console.preparation_store import (
    FilePreparationProgressStore,
    InMemoryPreparationProgressStore,
    PreparationProgressError,
    open_preparation_progress_store,
)
from ai_software_engineer.web_console.store import FileConsoleOperationStore
from ai_software_engineer.web_console.transport import create_console_app
from ai_software_engineer.work_queue.dispatcher import (
    DispatcherLoop,
    DispatcherTickResult,
    DispatcherTickStatus,
)
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
)
from ai_software_engineer.work_queue.ports import DeliveryQueuePending
from ai_software_engineer.work_queue.worker import (
    AcceptedArtifactStore,
    QueuedDeliverySupervisor,
    WorkerExecutionGuard,
    WorkerLease,
)
from tests.domain.factories import make_task
from tests.manager.test_dispatch import _agents, _policy
from tests.orchestration.test_runner import _definitions
from tests.recovery.test_authorization import approval
from tests.recovery.test_preparation_inspection_scope import (
    OfflineAuthority,
    PreparationFixture,
    SeedManager,
    preparation_fixture,
    seed_fixture,
)
from tests.web_console.test_core import _Executor, _reply_intent
from tests.web_console.test_transport import _HeldSnapshotReader, _Reader
from tests.work_queue.test_dispatcher import MemoryQueue, agent, dispatcher, item

NOW = datetime(2026, 10, 10, tzinfo=UTC)


def scope() -> PreparationProgressScope:
    return PreparationProgressScope(
        operation_id="operation_" + "a" * 32,
        team_id="team_test",
        project_id="project_test",
        delivery_id="delivery_multi_" + "a" * 40,
        expected_checkpoint_sha256="b" * 64,
        approved_plan_sha256="c" * 64,
    )


def record() -> AuthorizationRecorded:
    return seal_preparation_record(
        AuthorizationRecorded(
            scope=scope(),
            observed_at=NOW,
            evidence=AuthorizationEvidence(authorization_sha256="d" * 64),
            record_sha256="0" * 64,
        )
    )


def test_record_contract_and_schema_reject_extra_authority_and_digest_drift() -> None:
    value = PreparationProgressView(scope=scope(), records=(record(),))
    schema_path = Path(__file__).parents[2] / "schemas/recovery-preparation-progress.schema.json"
    schema = json.loads(schema_path.read_text())
    assert schema == {
        **PreparationProgressView.model_json_schema(),
        "$id": schema["$id"],
        "$schema": schema["$schema"],
    }
    Draft202012Validator(schema).validate(value.to_wire())
    changed = record().to_wire()
    changed["record_sha256"] = "e" * 64
    with pytest.raises(ValueError):
        AuthorizationRecorded.model_validate(changed).validate_integrity()
    secret = record().to_wire()
    secret["owner_token"] = "private-token"
    with pytest.raises(ValidationError):
        AuthorizationRecorded.model_validate(secret)
    wrong = value.to_wire()
    wrong["scope"] = scope().model_copy(update={"project_id": "project_other"}).to_wire()
    with pytest.raises(ValidationError):
        PreparationProgressView.model_validate(wrong)


@pytest.mark.parametrize("file_store", [False, True])
def test_store_is_immutable_bounded_idempotent_and_exactly_scoped(
    tmp_path: Path, file_store: bool
) -> None:
    store = (
        FilePreparationProgressStore(tmp_path / "progress")
        if file_store
        else InMemoryPreparationProgressStore()
    )
    assert store.read(scope()).records == ()
    store.append(record())
    store.append(record())
    assert store.read(scope()).records == (record(),)
    if file_store:
        assert FilePreparationProgressStore(tmp_path / "progress").read(scope()).records == (
            record(),
        )
    with pytest.raises(PreparationProgressError):
        store.read(scope().model_copy(update={"project_id": "project_other"}))
    changed = seal_preparation_record(
        record().model_copy(
            update={"evidence": AuthorizationEvidence(authorization_sha256="e" * 64)}
        )
    )
    with pytest.raises(PreparationProgressError):
        store.append(changed)
    assert store.read(scope()).records == (record(),)


def test_file_store_rejects_tampered_symlink_and_oversized_records(tmp_path: Path) -> None:
    root = tmp_path / "progress"
    store = FilePreparationProgressStore(root)
    store.append(record())
    path = root / scope().operation_id / "AUTHORIZATION_RECORDED.json"
    original = path.read_bytes()
    path.write_text(original.decode().replace("d" * 64, "e" * 64))
    with pytest.raises(PreparationProgressError):
        store.read(scope())
    path.write_bytes(b" " * 9000)
    with pytest.raises(PreparationProgressError):
        store.read(scope())
    path.unlink()
    other = tmp_path / "other.json"
    other.write_bytes(original)
    path.symlink_to(other)
    with pytest.raises(PreparationProgressError):
        store.read(scope())
    assert other.read_bytes() == original


def test_empty_legacy_read_does_not_create_progress_files(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    store = FilePreparationProgressStore(root, read_only=True)
    assert store.read(scope()).records == ()
    assert not root.exists()


def test_progress_lock_is_nonblocking_and_separate_from_operation_lock(tmp_path: Path) -> None:
    root = tmp_path / "progress"
    store = FilePreparationProgressStore(root)
    store.append(record())
    descriptor = os.open(root / "preparation.lock", os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(PreparationProgressError):
            store.read(scope())
    finally:
        os.close(descriptor)
    operation_lock = tmp_path / "console.lock"
    descriptor = os.open(operation_lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert store.read(scope()).records == (record(),)
    finally:
        os.close(descriptor)


def operation_for(fixture: PreparationFixture) -> ConsoleOperation:
    source = fixture.plan.source
    return ConsoleOperation.queued(
        team_id=source.scope.team_id,
        idempotency_key="exact-preparation-test",
        requested_at=NOW,
        intent=ContinueDeliveryIntent(
            project_id="project_test",
            delivery_id=source.parent_delivery_id or source.scope.delivery_id,
            expected_checkpoint_sha256=source.parent_checkpoint_sha256 or source.checkpoint_sha256,
            approved_plan_sha256=fixture.plan.plan_sha256,
        ),
    )


@pytest.mark.parametrize("fail_seal", [False, True])
def test_real_approve_only_observes_successful_returned_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_seal: bool
) -> None:
    fixture = preparation_fixture(tmp_path, monkeypatch)
    entry = NativeRecoveryEntry(
        ProductionConfig.default().model_copy(update={"platform_root": str(tmp_path / "platform")}),
        {},
        cast(ProductionProjectDeliveryBackend, object()),
    )
    monkeypatch.setattr(entry, "open_plan", lambda path: (fixture.store, fixture.plan))
    monkeypatch.setattr(
        entry,
        "_services",
        lambda store, plan, confirmed: (
            fixture.builder._authorization,
            fixture.builder,
            fixture.sealing,
        ),
    )
    if fail_seal:

        def fail(_: str) -> None:
            raise ValueError("private sealing failure")

        monkeypatch.setattr(fixture.sealing, "seal", fail)
    store = InMemoryPreparationProgressStore()
    operation = operation_for(fixture)
    with observe_recovery_preparation(operation, store.append, clock=lambda: NOW):
        if fail_seal:
            with pytest.raises(ValueError, match="private sealing"):
                entry.approve(
                    tmp_path / "plan.json",
                    confirmed_plan=fixture.plan.plan_sha256,
                    reference=approval(fixture.plan).approval_reference,
                )
        else:
            entry.approve(
                tmp_path / "plan.json",
                confirmed_plan=fixture.plan.plan_sha256,
                reference=approval(fixture.plan).approval_reference,
            )
    bound = preparation_scope(operation)
    assert bound is not None
    assert [r.kind for r in store.read(bound).records] == (
        ["AUTHORIZATION_RECORDED"] if fail_seal else ["AUTHORIZATION_RECORDED", "TASK_SEALED"]
    )


def test_typed_milestones_require_exact_returned_dispatch_seed_and_actual_first_coder_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = preparation_fixture(tmp_path, monkeypatch)
    operation = operation_for(fixture)
    store = InMemoryPreparationProgressStore()
    with observe_recovery_preparation(operation, store.append, clock=lambda: NOW):
        record_authorization(
            fixture.plan, fixture.store.get_authorization(fixture.plan.plan_sha256)
        )
        sealed = fixture.sealing.seal(fixture.plan.plan_sha256)
        record_task_sealed(fixture.plan, sealed)
        seed, target, _ = seed_fixture(fixture)
        dispatch = seed.dispatch
        record_dispatch_committed(fixture.plan, dispatch)
        receipt = seed.seed(target)
        record_seed_verified(fixture.plan, receipt, dispatch.task_id)
        # Preallocated RecoveryDispatchRecord.phases are not a real QueueClaim.
        bound = preparation_scope(operation)
        assert bound is not None
        assert len(store.read(bound).records) == 4
        queued = item(task_id=dispatch.task_id)
        tick = dispatcher(MemoryQueue((queued,)), agent("coder")).tick(now=NOW)
        assert tick.claim is not None
        boundary = RoleRunBoundary(dispatch.task_id, AgentRole.CODER, 1, 0, dispatch.task.base_ref)
        record_execution_claimed(tick.claim, boundary, "0" * 64)
        record_execution_claimed(
            tick.claim,
            RoleRunBoundary("task_other_001", AgentRole.CODER, 1, 0, dispatch.task.base_ref),
            dispatch.dispatch_sha256,
        )
        assert len(store.read(bound).records) == 4
        record_execution_claimed(tick.claim, boundary, dispatch.dispatch_sha256)
    assert [r.kind for r in store.read(bound).records] == [
        "AUTHORIZATION_RECORDED",
        "TASK_SEALED",
        "DISPATCH_COMMITTED",
        "SEED_VERIFIED",
        "EXECUTION_CLAIMED",
    ]
    # The ContextVar is reset; an observation cannot leak into another operation.
    missing = InMemoryPreparationProgressStore()
    record_execution_claimed(tick.claim, boundary, dispatch.dispatch_sha256)
    assert missing.read(bound).records == ()


def test_observation_setup_build_and_sink_failures_cannot_fail_or_repeat_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fixture = preparation_fixture(tmp_path, monkeypatch)
    operation = operation_for(fixture)
    authorization = fixture.store.get_authorization(fixture.plan.plan_sha256)

    def fail_sink(_: object) -> None:
        raise RuntimeError("private provider prose and owner token")

    with observe_recovery_preparation(operation, fail_sink, clock=lambda: NOW):
        record_authorization(fixture.plan, authorization)
    assert "PREPARATION_OBSERVATION_STORE_FAILED" in caplog.text
    assert "private provider" not in caplog.text

    def fail_clock() -> datetime:
        raise RuntimeError("private clock failure")

    with observe_recovery_preparation(operation, fail_sink, clock=fail_clock):
        record_authorization(fixture.plan, authorization)
    assert "PREPARATION_OBSERVATION_BUILD_FAILED" in caplog.text

    def fail_scope(_: object) -> None:
        raise RuntimeError("private setup failure")

    monkeypatch.setattr(
        "ai_software_engineer.recovery.preparation_progress.preparation_scope", fail_scope
    )
    with observe_recovery_preparation(operation, fail_sink):
        record_authorization(fixture.plan, authorization)
    assert "PREPARATION_OBSERVATION_SETUP_FAILED" in caplog.text
    assert "private setup" not in caplog.text


def _console(
    tmp_path: Path,
) -> tuple[ProjectConsole, FilePreparationProgressStore, ConsoleOperation]:
    operation_store = FileConsoleOperationStore(tmp_path / "operations", team_id=scope().team_id)
    progress = FilePreparationProgressStore(tmp_path / "progress")
    console = ProjectConsole(
        store=operation_store, executor=_Executor(), preparation_store=progress
    )
    submitted = console.submit(
        ContinueDeliveryIntent(
            project_id=scope().project_id,
            delivery_id=scope().delivery_id,
            expected_checkpoint_sha256=scope().expected_checkpoint_sha256,
            approved_plan_sha256=scope().approved_plan_sha256,
        ),
        idempotency_key="exact-http-preparation-test",
    )
    return console, progress, submitted


def test_progress_http_is_get_only_and_does_not_change_operation_history(tmp_path: Path) -> None:
    console, progress, submitted = _console(tmp_path)
    bound = preparation_scope(submitted)
    assert bound is not None
    before = {p: p.read_bytes() for p in (tmp_path / "operations").rglob("*.json")}
    reader = _Reader()

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_console_app(console, reader, team_id="team_test")),
            base_url="http://127.0.0.1:8765",
        ) as client:
            url = f"/api/v1/operations/{submitted.operation_id}/preparation-progress"
            assert (await client.get(url)).json()["records"] == []
            progress.append(
                seal_preparation_record(
                    record().model_copy(
                        update={
                            "scope": bound,
                            "observed_at": submitted.requested_at,
                        }
                    )
                )
            )
            response = await client.get(url)
            assert response.status_code == 200
            assert response.json()["records"][0]["kind"] == "AUTHORIZATION_RECORDED"
            assert (await client.post(url)).status_code == 405
            assert (
                await client.get(url.replace(submitted.operation_id, "invalid"))
            ).status_code == 404
            assert (
                await client.get(url.replace(submitted.operation_id, "operation_" + "f" * 32))
            ).status_code == 404
            path = tmp_path / "progress" / submitted.operation_id / "AUTHORIZATION_RECORDED.json"
            path.write_text('{"private":"do not echo"}')
            failed = await client.get(url)
            assert failed.status_code == 503
            assert failed.json()["error"]["code"] == "PREPARATION_PROGRESS_UNAVAILABLE"
            assert "do not echo" not in failed.text

    asyncio.run(exercise())
    assert reader.project_ids == []
    assert {p: p.read_bytes() for p in (tmp_path / "operations").rglob("*.json")} == before


def test_progress_http_remains_independent_while_team_reader_is_busy(tmp_path: Path) -> None:
    console, _, submitted = _console(tmp_path)
    reader = _HeldSnapshotReader()

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_console_app(console, reader, team_id="team_test")),
            base_url="http://127.0.0.1:8765",
        ) as client:
            reading = asyncio.create_task(client.get("/api/v1/team"))
            assert await asyncio.to_thread(reader.entered.wait, 2)
            try:
                busy = await client.get("/api/v1/team")
                assert busy.status_code == 503
                response = await asyncio.wait_for(
                    client.get(f"/api/v1/operations/{submitted.operation_id}/preparation-progress"),
                    1,
                )
                assert response.status_code == 200 and response.json()["records"] == []
            finally:
                reader.release.set()
                await reading

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["dispatch", "seed", "after_seed"])
def test_real_execute_observes_dispatch_and_verified_seed_only_after_each_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Run the real entry sequence with typed offline authority and seed adapters."""
    fixture = preparation_fixture(tmp_path, monkeypatch)
    fixture.sealing.seal(fixture.plan.plan_sha256)
    draft = fixture.builder.build(fixture.plan.plan_sha256)
    plan = fixture.plan
    route = ProviderRouteConfig(
        provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
    )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        team_id=plan.source.scope.team_id,
        model_routes=(route,),
    )

    class Backend:
        _organization = tmp_path / "organization"

        def prepare(self, _: str) -> PrepareProjectResult:
            return PrepareProjectResult(
                status=PrepareProjectStatus.PREPARED,
                repository_id=draft.facts.target.repository_id,
                baseline_compilation_sha256=draft.facts.target.baseline_spec_sha256,
                preparation=draft.facts.target,
            )

        def _workforce(self) -> object:
            policy = _policy()
            selected = policy.routes[3].model_copy(
                update={
                    "provider": route.provider,
                    "model": route.model,
                    "reasoning_effort": route.reasoning_effort,
                    "route_kind": route.kind.value,
                    "connection_mode": config.effective_connection_mode(route),
                }
            )
            return _agents(), policy.model_copy(
                update={
                    "routes": (selected,),
                    "default_tier": selected.tier,
                    "risk_floors": tuple(
                        f.model_copy(update={"minimum_tier": selected.tier})
                        for f in policy.risk_floors
                    ),
                }
            )

    entry = NativeRecoveryEntry(
        config,
        {"ASE_MYSQL_DSN": "mysql://unused/test"},
        cast(ProductionProjectDeliveryBackend, Backend()),
    )
    monkeypatch.setattr(
        entry,
        "_services",
        lambda *args: (fixture.builder._authorization, fixture.builder, fixture.sealing),
    )

    class TaskRepository:
        def __init__(self, _: str) -> None:
            pass

        def get(self, _: str) -> None:
            raise TaskNotFound("offline missing Task")

        def close(self) -> None:
            pass

    monkeypatch.setattr("ai_software_engineer.recovery.entry.MySqlTaskRepository", TaskRepository)
    authority = OfflineAuthority(fixture)
    monkeypatch.setattr(
        "ai_software_engineer.recovery.entry.MySqlDispatchAuthority",
        lambda *args, **kwargs: authority,
    )

    class Workforce:
        def __init__(self, _: object) -> None:
            pass

        def put_agent(self, value: object) -> object:
            return value

        def put_policy(self, value: object, *, versioned: bool) -> object:
            return value

    monkeypatch.setattr("ai_software_engineer.recovery.entry.FileTeamWorkforceStore", Workforce)
    monkeypatch.setattr(
        "ai_software_engineer.recovery.entry._task_commands",
        lambda profile: plan.permissions.commands,
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.entry._agent_definitions",
        lambda dispatch, commands: {
            AgentRole.CODER: _definitions()[AgentRole.CODER].model_copy(
                update={"permissions": plan.effective_target_permissions}
            ),
        },
    )
    if failure == "dispatch":

        def fail_commit(**kwargs: object) -> None:
            raise ValueError("offline dispatch fence failed")

        monkeypatch.setattr(authority, "commit_recovery", fail_commit)
    manager = SeedManager(fixture)
    monkeypatch.setattr(entry, "_manager", lambda *args: cast(GitWorktreeManager, manager))

    @dataclass
    class Binding:
        worktree: WorktreeRef

    class Coordinator:
        def __init__(self, _: object) -> None:
            pass

        def open_coder(
            self, dispatch: RecoveryDispatchRecord, definitions: object, *, recover: bool
        ) -> Binding:
            target = WorktreeRef(
                dispatch.task_id,
                AgentRole.CODER,
                1,
                tmp_path / "target",
                dispatch.task.base_ref,
                dispatch.task.branch_name or f"ai/{dispatch.task_id}/attempt-1",
                False,
            )
            target.path.mkdir()
            return Binding(target)

    monkeypatch.setattr(
        "ai_software_engineer.recovery.entry.DispatchRoleWorktreeCoordinator", Coordinator
    )
    original_seed = RecoverySeedService.seed

    def seed(service: RecoverySeedService, target: WorktreeRef) -> RecoverySeedRecord:
        if failure == "seed":
            raise ValueError("offline seed verify failed")
        return original_seed(service, target)

    monkeypatch.setattr(RecoverySeedService, "seed", seed)

    def stop_after_seed(*args: object) -> None:
        raise ValueError("offline stop after verified seed")

    monkeypatch.setattr(
        "ai_software_engineer.recovery.entry._approved_parent_context", stop_after_seed
    )
    store = InMemoryPreparationProgressStore()
    operation = operation_for(fixture)
    with (
        observe_recovery_preparation(operation, store.append, clock=lambda: NOW),
        pytest.raises(ValueError, match="offline"),
    ):
        entry._execute(fixture.store, plan, None, route)
    bound = preparation_scope(operation)
    assert bound is not None
    assert [r.kind for r in store.read(bound).records] == {
        "dispatch": [],
        "seed": ["DISPATCH_COMMITTED"],
        "after_seed": ["DISPATCH_COMMITTED", "SEED_VERIFIED"],
    }[failure]


@pytest.mark.parametrize("dispatched", [False, True])
def test_real_supervisor_observes_claim_after_dispatch_return_before_worker_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dispatched: bool
) -> None:
    fixture = preparation_fixture(tmp_path, monkeypatch)
    seed, _, _ = seed_fixture(fixture)
    dispatch = seed.dispatch
    queued = item(task_id=dispatch.task_id, repository_id=dispatch.repository_id)
    boundary = RoleRunBoundary(dispatch.task_id, AgentRole.CODER, 1, 0, dispatch.task.base_ref)
    step = QueuedRoleStep(
        work_item=queued, boundary=boundary, allocation_sha256=dispatch.dispatch_sha256
    )
    tick = dispatcher(MemoryQueue((queued,)), agent("coder")).tick(now=NOW)
    if not dispatched:
        tick = DispatcherTickResult(status=DispatcherTickStatus.IDLE, ticked_at=NOW)

    class Queue:
        def admission(self, _: str) -> RoleQueueAdmission:
            return RoleQueueAdmission(
                task_id=dispatch.task_id,
                repository_id=dispatch.repository_id,
                allocation_sha256=dispatch.dispatch_sha256,
                legacy_artifacts=(),
            )

        def items_for_task(self, _: str) -> tuple[object, ...]:
            return (queued,)

        def step(self, _: str) -> QueuedRoleStep:
            return step

    class Repository(MySqlTaskRepository):
        def __init__(self) -> None:
            pass

        def get(self, task_id: str) -> Task:
            return make_task().model_copy(update={"id": task_id})

    @dataclass
    class Runtime:
        task_repository: MySqlTaskRepository

    class Dispatcher:
        def tick(self, *, now: datetime, work_item_id: str) -> DispatcherTickResult:
            assert work_item_id == queued.id
            # The call has not returned, so the caller must not observe a claim yet.
            assert bound is not None
            assert not store.read(bound).records
            return tick

    store = InMemoryPreparationProgressStore()
    operation = operation_for(fixture)
    bound = preparation_scope(operation)
    assert bound is not None
    supervisor = QueuedDeliverySupervisor(
        queue=cast(MySqlRoleQueue, Queue()),
        guard=WorkerExecutionGuard(),
        artifacts=cast(AcceptedArtifactStore, object()),
        allocation_sha256=dispatch.dispatch_sha256,
        repository_id=dispatch.repository_id,
        records=cast(KnowledgeRecordStore, object()),
        locks_root=tmp_path / "locks",
        build_step=lambda *_: step,
        dispatcher=lambda _: cast(DispatcherLoop, Dispatcher()),
    )

    def stop_start(_: WorkerLease) -> None:
        assert [r.kind for r in store.read(bound).records] == ["EXECUTION_CLAIMED"]
        raise ValueError("offline stop at real worker start")

    monkeypatch.setattr(WorkerLease, "start", stop_start)

    def claim_only(value: PreparationRecord) -> None:
        if value.kind == "EXECUTION_CLAIMED":
            store.append(value)

    with observe_recovery_preparation(operation, claim_only, clock=lambda: NOW):
        # A missing middle diagnostic does not suppress an independently returned claim.
        record_dispatch_committed(fixture.plan, dispatch)
        with pytest.raises(ValueError if dispatched else DeliveryQueuePending):
            supervisor._run(
                cast(RuntimeSession, Runtime(Repository())),
                dispatch.task_id,
                terminal_result=lambda: None,
            )
    assert len(store.read(bound).records) == (1 if dispatched else 0)


def test_console_success_is_not_replayed_when_observation_storage_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fixture = preparation_fixture(tmp_path, monkeypatch)
    failed_root = tmp_path / "blocked-progress-root"
    failed_root.write_text("private unrelated file")
    progress = open_preparation_progress_store(failed_root)
    calls: list[ConsoleIntent] = []

    class Executor:
        def execute(self, intent: ConsoleIntent) -> ConsoleCommandResult:
            calls.append(intent)
            record_authorization(
                fixture.plan, fixture.store.get_authorization(fixture.plan.plan_sha256)
            )
            return ConsoleCommandResult(
                project_id="project_test", stage="IMPLEMENTING", next_action="执行中"
            )

    original = operation_for(fixture)
    store = FileConsoleOperationStore(tmp_path / "operations", team_id=original.team_id)
    console = ProjectConsole(store=store, executor=Executor(), preparation_store=progress)
    submitted = console.submit(original.intent, idempotency_key="observation-failure-once")
    finished = console.run_once()
    assert finished is not None and finished.status is ConsoleOperationStatus.SUCCEEDED
    assert console.run_once() is None
    assert calls == [original.intent]
    assert console.get(submitted.operation_id) == finished
    assert "PREPARATION_OBSERVATION_STORE_SETUP_FAILED" in caplog.text
    assert "PREPARATION_OBSERVATION_STORE_FAILED" in caplog.text
    assert "private unrelated" not in caplog.text


def test_nonexact_and_old_console_operations_return_explicit_empty_progress(tmp_path: Path) -> None:
    console, _, _ = _console(tmp_path)
    unrelated_store = FileConsoleOperationStore(tmp_path / "old", team_id="team_test")
    unrelated = ProjectConsole(store=unrelated_store, executor=_Executor())
    operation = unrelated.submit(_reply_intent(), idempotency_key="nonexact-old-operation")
    value = unrelated.preparation_progress(operation)
    assert value.to_wire() == {"schema_version": "v0.1", "scope": None, "records": []}
    assert console.list_operations()[0].sequence == 1


def test_observation_file_count_and_parent_symlinks_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "progress"
    store = FilePreparationProgressStore(root)
    store.append(record())
    directory = root / scope().operation_id
    for index in range(5):
        (directory / f"unexpected-{index}.json").write_text("{}")
    with pytest.raises(PreparationProgressError):
        store.read(scope())
    link = tmp_path / "linked"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(PreparationProgressError):
        FilePreparationProgressStore(link, read_only=True)


@pytest.mark.parametrize(
    "invalid", ["missing-evidence", "extra-evidence", "unknown-kind", "naive-time", "duplicate"]
)
def test_progress_view_rejects_invalid_wire_records(invalid: str) -> None:
    payload = PreparationProgressView(scope=scope(), records=(record(),)).to_wire()
    records = payload["records"]
    assert isinstance(records, list) and isinstance(records[0], dict)
    entry = records[0]
    if invalid == "missing-evidence":
        entry.pop("evidence")
    elif invalid == "extra-evidence":
        entry["evidence"] = {"authorization_sha256": "d" * 64, "owner_token": "private"}
    elif invalid == "unknown-kind":
        entry["kind"] = "MODEL_RUNNING"
    elif invalid == "naive-time":
        entry["observed_at"] = "2026-10-10T00:00:00"
    else:
        records.append(dict(entry))
    with pytest.raises(ValidationError):
        PreparationProgressView.model_validate(payload)


def test_observation_scope_resets_after_success_nested_scope_and_delivery_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = preparation_fixture(tmp_path, monkeypatch)
    operation = operation_for(fixture)
    authorization = fixture.store.get_authorization(fixture.plan.plan_sha256)
    captured: list[PreparationRecord] = []
    record_authorization(fixture.plan, authorization)
    assert captured == []
    with observe_recovery_preparation(operation, captured.append, clock=lambda: NOW):
        record_authorization(fixture.plan, authorization)
        foreign = operation.model_copy(update={"team_id": "team_other"})
        with observe_recovery_preparation(foreign, captured.append, clock=lambda: NOW):
            record_authorization(fixture.plan, authorization)
        record_authorization(fixture.plan, authorization)
    assert len(captured) == 2
    record_authorization(fixture.plan, authorization)
    assert len(captured) == 2
    with (
        pytest.raises(ValueError, match="actual delivery failure"),
        observe_recovery_preparation(operation, captured.append, clock=lambda: NOW),
    ):
        record_authorization(fixture.plan, authorization)
        raise ValueError("actual delivery failure")
    record_authorization(fixture.plan, authorization)
    assert len(captured) == 3


def test_record_replay_retains_first_observed_time_and_terminal_operation_reads(
    tmp_path: Path,
) -> None:
    console, progress, operation = _console(tmp_path)
    bound = preparation_scope(operation)
    assert bound is not None
    first = seal_preparation_record(
        record().model_copy(
            update={
                "scope": bound,
                "observed_at": operation.requested_at,
            }
        )
    )
    progress.append(first)
    filename = tmp_path / "progress" / operation.operation_id / "AUTHORIZATION_RECORDED.json"
    original = filename.read_bytes()
    later = seal_preparation_record(
        first.model_copy(update={"observed_at": datetime(2027, 1, 1, tzinfo=UTC)})
    )
    progress.append(later)
    assert filename.read_bytes() == original
    finished = console.run_once()
    assert finished is not None and finished.status is ConsoleOperationStatus.SUCCEEDED
    assert console.preparation_progress(finished).records == (first,)
