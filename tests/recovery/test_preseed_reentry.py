"""Public recovery re-entry after allocation/worktree creation, before seed publication."""

from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Literal

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.git import WorktreeRef
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_delivery import DeliveryRouteAdapterFactory
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration.retry import RetryResult
from ai_software_engineer.recovery import RecoveryRejected
from ai_software_engineer.recovery.entry import NativeRecoveryEntry
from ai_software_engineer.recovery.records import RecoveryInvocationRecord, RecoverySeedRecord
from ai_software_engineer.recovery.resume import DeliveryResumeOutcome, DeliveryResumeResult
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.store import MySqlTaskRepository, TaskNotFound
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from tests.git.test_capture import git
from tests.manager.test_production_backend import _git
from tests.recovery.execution_fixture import OfflineRecoveryClients
from tests.recovery.facts_window_fixture import modern_failed_native_fixture
from tests.recovery.test_execution import OfflineFactory
from tests.recovery.test_native import _snapshot

pytestmark = pytest.mark.mysql


@pytest.fixture(autouse=True)
def isolated_mysql_facts() -> Iterator[None]:
    """The native fixture owns resets after exact DB identity and exclusive admission."""
    yield


class _BeforeSeedInterruption(RuntimeError):
    """One bounded interruption with no provider or seed publication."""


def _continue(host: TeamHost, command: ResumeProjectDelivery) -> DeliveryResumeResult:
    result = host.resume_delivery(command)
    assert isinstance(result, DeliveryResumeResult)
    return result


def _task_ids(dsn: str) -> frozenset[str]:
    with closing(open_mysql_connection(dsn)) as connection, connection.cursor(DictCursor) as cursor:
        cursor.execute("SELECT id FROM tasks")
        return frozenset(str(row["id"]) for row in cursor.fetchall())


def _require_unstarted(dsn: str, store: FileRecoveryStore, plan_sha256: str) -> None:
    task_id = store.get_task_record(plan_sha256).task.id
    with pytest.raises(RecoveryRecordMissing):
        store.get_seed(plan_sha256)
    with pytest.raises(RecoveryRecordMissing):
        store.get_invocation(plan_sha256)
    with MySqlTaskRepository(dsn) as repository, pytest.raises(TaskNotFound):
        repository.get(task_id)
    with closing(open_mysql_connection(dsn)) as connection, connection.cursor(DictCursor) as cursor:
        for table in ("state_events", "work_queue_items", "work_queue_claims"):
            cursor.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE task_id=%s", (task_id,))
            row = cursor.fetchone()
            assert row is not None and row["count"] == 0


@pytest.mark.parametrize("change", ("unchanged", "dirty_target", "target_drift"))
def test_public_continue_reuses_approved_allocation_after_interruption_before_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: Literal["unchanged", "dirty_target", "target_drift"],
) -> None:
    # The shared helper admits only the exact isolated DB, holds its OS/MySQL locks,
    # checks all 13 tables are empty, and stops its owned offline child before cleanup.
    with modern_failed_native_fixture(tmp_path, monkeypatch) as native:
        dsn = native.config.require_mysql_dsn(native.environment)

        def new_host() -> TeamHost:
            return TeamHost(
                config=native.config,
                environment=native.environment,
                structured_clients=OfflineRecoveryClients(),
            )

        host = new_host()
        old_task = native.original.task
        with MySqlTaskRepository(dsn) as repository:
            old_events = repository.list_events(old_task.id)
        old_tree = Path(native.capture.worktree_path)
        old_bytes = _snapshot(old_tree)
        old_task_ids = _task_ids(dsn)
        assert old_task_ids == {old_task.id}

        # Make the old draft conflict with the latest base. Only the explicitly
        # proposed coder_reapply Plan authorizes Coder to adapt the complete patch.
        (native.project / "hello.txt").write_text("new base greeting\n", encoding="utf-8")
        _git("add", "hello.txt", cwd=native.project)
        _git("commit", "-m", "new approved recovery base", cwd=native.project)
        recovery = host.recovery_entry()
        assert native.original.source.failed_run_id is not None
        assert native.original.source.failed_context_id is not None
        plan, path = recovery.propose(
            repository_root=str(native.project),
            delivery_id=native.original.source.scope.delivery_id,
            failed_run_id=native.original.source.failed_run_id,
            failed_context_id=native.original.source.failed_context_id,
            input_mode="coder_reapply",
        )
        command = ResumeProjectDelivery(delivery_id=plan.source.scope.delivery_id)
        proposed = _continue(host, command)
        assert proposed.outcome is DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED
        assert proposed.recovery_plan_sha256 == plan.plan_sha256
        assert proposed.checkpoint.task_id == old_task.id

        factories: list[OfflineFactory] = []
        reused_targets: list[WorktreeRef] = []
        seed_writes: list[RecoverySeedRecord] = []
        invocation_writes: list[RecoveryInvocationRecord] = []
        execute = NativeRecoveryEntry.execute
        put_seed = FileRecoveryStore.put_seed
        put_invocation = FileRecoveryStore.put_invocation

        def offline_factory(seed: RecoverySeedService) -> DeliveryRouteAdapterFactory:
            # Completed delivery releases clean role worktrees. Observe recovery
            # identity here, after the real seed gate and before any provider call.
            receipt_target = seed.store.get_seed(plan.plan_sha256).capture.to_capture().worktree
            assert seed.dispatch == dispatch
            assert receipt_target == target
            assert (target.path.stat().st_dev, target.path.stat().st_ino) == target_identity
            assert (target.path / ".git").read_bytes() == target_git
            reused_targets.append(receipt_target)
            routes = OfflineFactory(seed)
            factories.append(routes)
            return routes

        def execute_offline(
            entry: NativeRecoveryEntry,
            plan_file: Path,
            *,
            route_factory: Callable[[RecoverySeedService], DeliveryRouteAdapterFactory]
            | None = None,
        ) -> RetryResult:
            # Inject only the existing provider port. Public resume_execution and
            # the real facts/sealing/allocation/worktree/seed chain stay intact.
            assert route_factory is None
            return execute(entry, plan_file, route_factory=offline_factory)

        def record_seed(store: FileRecoveryStore, record: RecoverySeedRecord) -> RecoverySeedRecord:
            sealed = put_seed(store, record)
            seed_writes.append(sealed)
            return sealed

        def record_invocation(
            store: FileRecoveryStore, record: RecoveryInvocationRecord
        ) -> RecoveryInvocationRecord:
            sealed = put_invocation(store, record)
            invocation_writes.append(sealed)
            return sealed

        monkeypatch.setattr(NativeRecoveryEntry, "execute", execute_offline)
        monkeypatch.setattr(FileRecoveryStore, "put_seed", record_seed)
        monkeypatch.setattr(FileRecoveryStore, "put_invocation", record_invocation)
        interrupted_targets: list[WorktreeRef] = []

        def interrupt_before_seed(
            seed: RecoverySeedService, target: WorktreeRef
        ) -> RecoverySeedRecord:
            assert not interrupted_targets
            assert target.path.is_dir()
            assert seed.dispatch.task_id == target.task_id == plan.new_task_id
            assert git(target.path, "status", "--porcelain") == ""
            assert git(target.path, "rev-parse", "HEAD") == plan.target_base_revision
            _require_unstarted(dsn, seed.store, plan.plan_sha256)
            interrupted_targets.append(target)
            raise _BeforeSeedInterruption("bounded offline interruption before seed")

        with monkeypatch.context() as fault:
            fault.setattr(RecoverySeedService, "seed", interrupt_before_seed)
            with pytest.raises(_BeforeSeedInterruption, match="before seed"):
                _continue(
                    host,
                    ResumeProjectDelivery(
                        delivery_id=command.delivery_id,
                        approved_plan_sha256=plan.plan_sha256,
                        approval_reference="exact-preseed-reentry-approval",
                    ),
                )

        assert len(interrupted_targets) == 1
        target = interrupted_targets[0]
        target_identity = (target.path.stat().st_dev, target.path.stat().st_ino)
        target_git = (target.path / ".git").read_bytes()
        store, loaded = recovery.open_plan(path)
        assert loaded == plan
        authorization = store.get_authorization(plan.plan_sha256)
        task_record = store.get_task_record(plan.plan_sha256)
        dispatch = recovery._dispatch_for(store, plan)
        assert authorization.decision.approved
        assert task_record.task.status is TaskStatus.NEW and task_record.task.attempts == 0
        assert dispatch.task == task_record.task
        assert tuple(phase.role for phase in dispatch.phases) == (
            AgentRole.CODER,
            AgentRole.QA,
            AgentRole.REVIEWER,
        )
        assert len({phase.agent_id for phase in dispatch.phases}) == 3
        resource_ids = tuple((p.assignment.id, p.lease.id) for p in dispatch.phases)
        immutable_bytes = {
            file: file.read_bytes()
            for category in ("plan", "authorization", "task")
            for file in (path.parent / f"{category}-{plan.plan_sha256}.json",)
        }
        _require_unstarted(dsn, store, plan.plan_sha256)
        assert _task_ids(dsn) == old_task_ids
        assert not factories and not seed_writes and not invocation_writes

        if change == "dirty_target":
            (target.path / "hello.txt").write_text("unreceipted target draft\n", encoding="utf-8")
        elif change == "target_drift":
            (native.project / "hello.txt").write_text("newer unapproved base\n", encoding="utf-8")
            _git("add", "hello.txt", cwd=native.project)
            _git("commit", "-m", "drift after allocation", cwd=native.project)
        target_bytes = _snapshot(target.path)

        # A new trusted Host reconstructs all service/store objects. The Continue
        # command intentionally has no approval digest/reference or budget override.
        reopened = new_host()
        reopened_recovery = reopened.recovery_entry()
        assert reopened_recovery is not recovery
        if change == "target_drift":
            with pytest.raises(RecoveryRejected):
                reopened_recovery.require_current_plan(path)
        result = _continue(reopened, command)
        reopened_store, _ = reopened_recovery.open_plan(path)
        assert reopened_store.get_authorization(plan.plan_sha256) == authorization
        assert reopened_store.get_task_record(plan.plan_sha256) == task_record
        reopened_dispatch = reopened_recovery._dispatch_for(reopened_store, plan)
        assert reopened_dispatch == dispatch
        assert (
            tuple((p.assignment.id, p.lease.id) for p in reopened_dispatch.phases) == resource_ids
        )
        assert all(file.read_bytes() == before for file, before in immutable_bytes.items())
        if change == "unchanged":
            assert result.outcome is DeliveryResumeOutcome.RECOVERED, result.next_action
            assert result.checkpoint.stage is DeliveryStage.DONE
            assert result.checkpoint.task_id == task_record.task.id
            assert result.checkpoint.candidate_revision is not None
            assert len(factories) == 1
            assert reused_targets == [target]
            requests = factories[0].calls
            assert [request.role for request in requests] == [
                AgentRole.CODER,
                AgentRole.QA,
                AgentRole.REVIEWER,
            ]
            coder = requests[0]
            assert coder.task_id == task_record.task.id and coder.attempt == 1
            assert coder.source_revision == task_record.task.base_ref == target.head_revision
            receipt = reopened_store.get_seed(plan.plan_sha256)
            invocation = reopened_store.get_invocation(plan.plan_sha256)
            assert seed_writes == [receipt]
            assert invocation_writes == [invocation]
            assert not receipt.capture.patch and not receipt.capture.files
            assert receipt.capture.to_capture().worktree == target
            assert invocation.run_id == coder.run_id
            assert invocation.context_manifest_id == coder.context_manifest_id
            context = FileContextStore(path.parent.parent.parent / "contexts", read_only=True).get(
                coder.context_manifest_id
            )
            patch_sections = [s for s in context.sections if s.name == "source:recovery.patch"]
            assert len(patch_sections) == 1
            patch = patch_sections[0]
            assert not patch.truncated and patch.content == plan.capture.patch
            assert plan.capture.patch and "partially implemented" in patch.content
            assert requests[1].source_revision == requests[2].source_revision
            assert requests[1].source_revision == result.checkpoint.candidate_revision
            assert _task_ids(dsn) == old_task_ids | {task_record.task.id}
            with MySqlTaskRepository(dsn) as repository:
                completed_task = repository.get(task_record.task.id)
                assert completed_task.status is TaskStatus.DONE
                assert completed_task.retry_policy == task_record.task.retry_policy
            # Normal terminal adoption must not publish another seed/invocation or
            # run any role again, including after one further service reconstruction.
            repeated = _continue(new_host(), command)
            assert repeated.checkpoint == result.checkpoint
            assert len(factories) == len(seed_writes) == len(invocation_writes) == 1
            assert len(requests) == 3
        else:
            if change == "dirty_target":
                assert result.outcome is DeliveryResumeOutcome.WAITING_HUMAN
                assert "clean initial worktree" in result.next_action
            else:
                assert result.outcome is DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED
                assert result.recovery_plan_sha256 != plan.plan_sha256
            assert result.checkpoint == proposed.checkpoint
            _require_unstarted(dsn, reopened_store, plan.plan_sha256)
            assert _task_ids(dsn) == old_task_ids
            assert not factories and not seed_writes and not invocation_writes
            assert not reused_targets
            assert (target.path.stat().st_dev, target.path.stat().st_ino) == target_identity
            assert (target.path / ".git").read_bytes() == target_git
            assert _snapshot(target.path) == target_bytes

        assert _snapshot(old_tree) == old_bytes
        with MySqlTaskRepository(dsn) as repository:
            assert repository.get(old_task.id) == old_task
            assert repository.list_events(old_task.id) == old_events
