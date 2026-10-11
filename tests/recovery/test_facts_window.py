"""Complete modern Native observation windows on isolated real durable facts."""

import asyncio
import fcntl
import hashlib
import os
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import MethodType

import pytest

from ai_software_engineer import owned_sessions
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.owned_sessions import OwnedProcessIdentity
from ai_software_engineer.product import FileProductRecordStore
from ai_software_engineer.recovery import current, workspace_snapshot
from ai_software_engineer.recovery.current import (
    NativeRecoveryFacts,
    NativeRecoveryFactsVerifier,
    _RecoveryTargetPreflight,
)
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected, RecoveryScope
from ai_software_engineer.recovery.native import NativeRecoverySource, NativeRecoverySourceReader
from ai_software_engineer.recovery.workspace_records import RecoveryWorkspaceScope
from ai_software_engineer.recovery.workspace_snapshot import (
    TerminalWorkspaceFacts,
    TerminalWorkspaceObservation,
    _terminal_workspace_window,
)
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.git.test_capture import git
from tests.recovery.facts_window_fixture import (
    ModernFailedNativeFixture,
    modern_failed_native_fixture,
)


@pytest.fixture(autouse=True)
def isolated_mysql_facts() -> Iterator[None]:
    """The helper owns resets only after its exclusive database admission gate.

    Keep the mysql marker and repository setup DSN checks. Override the global
    autouse reset so it cannot clear another fixture before acquiring ownership.
    """
    yield


def _old_lock(fixture: ModernFailedNativeFixture) -> Path:
    name = hashlib.sha256(fixture.original.task.id.encode()).hexdigest() + ".lock"
    return (
        Path(fixture.original.preparation.repository_workspace_root)
        / "state/queue-worker-locks"
        / name
    )


def _require_lock(fixture: ModernFailedNativeFixture, *, held: bool) -> None:
    descriptor = os.open(_old_lock(fixture), os.O_RDWR | os.O_NOFOLLOW)
    try:
        if held:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(descriptor)


@pytest.mark.mysql
def test_complete_modern_native_inspection_reads_source_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with modern_failed_native_fixture(tmp_path, monkeypatch) as fixture:
        calls = 0
        order: list[str] = []
        terminal_reads: list[TerminalWorkspaceFacts] = []
        inspect = NativeRecoverySourceReader.inspect
        target = NativeRecoveryFactsVerifier._target_facts
        terminal = workspace_snapshot._read_facts
        observe = workspace_snapshot._observe

        def counted(
            reader: NativeRecoverySourceReader,
            scope: RecoveryScope,
            *,
            failed_run_id: str,
            failed_context_id: str,
        ) -> NativeRecoverySource:
            nonlocal calls
            calls += 1
            _require_lock(fixture, held=True)
            result = inspect(
                reader,
                scope,
                failed_run_id=failed_run_id,
                failed_context_id=failed_context_id,
            )
            order.append("source")
            return result

        def target_read(
            verifier: NativeRecoveryFactsVerifier,
            plan: RecoveryPlan,
            preflight: _RecoveryTargetPreflight,
        ) -> NativeRecoveryFacts:
            result = target(verifier, plan, preflight)
            order.append("target")
            return result

        def terminal_read(
            config: ProductionConfig,
            environment: Mapping[str, str],
            original: NativeRecoverySource,
            sidecar: Path,
            scope: RecoveryWorkspaceScope,
        ) -> TerminalWorkspaceFacts:
            result = terminal(config, environment, original, sidecar, scope)
            terminal_reads.append(result)
            order.append("terminal")
            return result

        def inventory_read(
            manager: GitWorktreeManager, facts: TerminalWorkspaceFacts, guard: WorkerExecutionGuard
        ) -> TerminalWorkspaceObservation:
            result = observe(manager, facts, guard)
            order.append("inventory")
            return result

        monkeypatch.setattr(NativeRecoverySourceReader, "inspect", counted)
        monkeypatch.setattr(NativeRecoveryFactsVerifier, "_target_facts", target_read)
        monkeypatch.setattr(workspace_snapshot, "_read_facts", terminal_read)
        monkeypatch.setattr(workspace_snapshot, "_observe", inventory_read)
        facts = NativeRecoveryFactsVerifier(fixture.config, fixture.environment).inspect(
            fixture.plan
        )
        assert facts.original == fixture.original
        assert facts.target == fixture.original.preparation
        assert calls == 2
        assert order == ["source", "target", "terminal", "inventory"] * 2
        assert len(terminal_reads) == 2 and terminal_reads[0] == terminal_reads[1]
        assert terminal_reads[0] is not terminal_reads[1]
        assert terminal_reads[0].stop is not terminal_reads[1].stop
        _require_lock(fixture, held=False)


def _late_mutation(
    fixture: ModernFailedNativeFixture, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidecar = Path(fixture.original.preparation.repository_workspace_root)
    if mode == "capture":
        (Path(fixture.capture.worktree_path) / "hello.txt").write_text(
            "changed after final target\n"
        )
    elif mode == "stop":
        path = sidecar / "state/continuations" / fixture.original.task.id
        (path / f"capture-stop-{fixture.plan.source.failed_run_id}.json").unlink()
    elif mode == "sql":
        connection = open_mysql_connection(fixture.environment["ASE_MYSQL_DSN"])
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE tasks SET status='FAILED' WHERE id=%s", (fixture.original.task.id,)
                )
            connection.commit()
        finally:
            connection.close()
    elif mode == "ignored_inventory":
        root = Path(fixture.capture.worktree_path) / ".venv"
        root.mkdir()
        (root / "extra.txt").write_text("local ignored environment\n")
    elif mode == "live_session":
        root = sidecar / "state/continuations" / fixture.original.task.id
        stop = FileContinuationStore(root, task_id=fixture.original.task.id).capture_stop(
            fixture.plan.source.failed_run_id
        )
        proof = stop.process_stop.session_proof
        assert proof is not None
        inspector = owned_sessions._inspector()
        leader = proof.leader

        class OccupiedLeader:
            def boot_identity(self) -> str:
                return inspector.boot_identity()

            def identity(self, pid: int) -> OwnedProcessIdentity | None:
                return leader if pid == leader.process_id else inspector.identity(pid)

            def members(self, sid: int) -> tuple[OwnedProcessIdentity, ...]:
                return inspector.members(sid)

        monkeypatch.setattr(owned_sessions, "_inspector", OccupiedLeader)
    else:
        raise AssertionError("unknown mutation")


@pytest.mark.mysql
@pytest.mark.parametrize("mode", ["capture", "stop", "sql", "ignored_inventory", "live_session"])
def test_terminal_rechecks_after_the_last_complete_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    with modern_failed_native_fixture(tmp_path, monkeypatch) as fixture:
        if mode == "ignored_inventory":
            git_root = Path(
                git(fixture.project, "rev-parse", "--path-format=absolute", "--git-common-dir")
            )
            with (git_root / "info/exclude").open("a") as stream:
                stream.write("\n.venv/\n")
        target = NativeRecoveryFactsVerifier._target_facts
        target_reads = 0

        def changed_after_target(
            verifier: NativeRecoveryFactsVerifier,
            plan: RecoveryPlan,
            preflight: _RecoveryTargetPreflight,
        ) -> NativeRecoveryFacts:
            nonlocal target_reads
            result = target(verifier, plan, preflight)
            target_reads += 1
            if target_reads == 2:
                _late_mutation(fixture, mode, monkeypatch)
            return result

        monkeypatch.setattr(NativeRecoveryFactsVerifier, "_target_facts", changed_after_target)
        with pytest.raises(RecoveryRejected):
            fixture.reader.inspect(fixture.plan)
        assert target_reads == 2
        _require_lock(fixture, held=False)


@pytest.mark.mysql
@pytest.mark.parametrize("mode", ["approved_source", "clean_target"])
def test_second_complete_native_source_and_target_pass_detects_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    with modern_failed_native_fixture(tmp_path, monkeypatch) as fixture:
        observe = workspace_snapshot._observe
        observations = 0

        def change_after_first_terminal(
            manager: GitWorktreeManager,
            facts: TerminalWorkspaceFacts,
            guard: WorkerExecutionGuard,
        ) -> TerminalWorkspaceObservation:
            nonlocal observations
            result = observe(manager, facts, guard)
            observations += 1
            if observations == 1:
                if mode == "approved_source":
                    sidecar = Path(fixture.original.preparation.repository_workspace_root)
                    store = FileProductRecordStore(sidecar / "state/product", read_only=True)
                    path = store._request_record_path(
                        "specs",
                        fixture.original.product.request_id,
                        fixture.original.product.version,
                        create=False,
                    )
                    path.write_text("{}")
                else:
                    (fixture.project / "hello.txt").write_text("uncommitted target drift\n")
            return result

        monkeypatch.setattr(workspace_snapshot, "_observe", change_after_first_terminal)
        with pytest.raises(RecoveryRejected):
            fixture.reader.inspect(fixture.plan)
        assert observations == 1
        _require_lock(fixture, held=False)


@pytest.mark.mysql
@pytest.mark.parametrize("mode", ["busy", "missing", "symlink", "replaced"])
def test_existing_worker_lock_rejects_without_recreating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    with modern_failed_native_fixture(tmp_path, monkeypatch) as fixture:
        path = _old_lock(fixture)
        descriptor = -1
        if mode == "busy":
            descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif mode == "missing":
            path.unlink()
        elif mode == "symlink":
            path.unlink()
            path.symlink_to(tmp_path / "not-a-worker-lock")
        else:
            observe = workspace_snapshot._observe
            observations = 0

            def replace_lock(
                manager: GitWorktreeManager,
                facts: TerminalWorkspaceFacts,
                guard: WorkerExecutionGuard,
            ) -> TerminalWorkspaceObservation:
                nonlocal observations
                result = observe(manager, facts, guard)
                observations += 1
                if observations == 2:
                    path.unlink()
                    handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                    os.close(handle)
                return result

            monkeypatch.setattr(workspace_snapshot, "_observe", replace_lock)
        try:
            with pytest.raises(RecoveryRejected):
                fixture.reader.inspect(fixture.plan)
            if mode == "missing":
                assert not path.exists()
            elif mode == "symlink":
                assert path.is_symlink() and not path.exists()
        finally:
            if descriptor >= 0:
                os.close(descriptor)


@pytest.mark.mysql
@pytest.mark.parametrize("mode", ["instance", "class", "subclass"])
def test_stronger_native_inspect_retains_the_original_complete_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    with modern_failed_native_fixture(tmp_path, monkeypatch) as fixture:
        inspect = NativeRecoverySourceReader.inspect
        standard = current._STANDARD_NATIVE_INSPECT
        sources = 0
        stronger_calls = 0

        def counted_source(
            reader: NativeRecoverySourceReader,
            scope: RecoveryScope,
            *,
            failed_run_id: str,
            failed_context_id: str,
        ) -> NativeRecoverySource:
            nonlocal sources
            sources += 1
            return inspect(
                reader, scope, failed_run_id=failed_run_id, failed_context_id=failed_context_id
            )

        def stronger(
            verifier: NativeRecoveryFactsVerifier, plan: RecoveryPlan
        ) -> NativeRecoveryFacts:
            nonlocal stronger_calls
            stronger_calls += 1
            return standard(verifier, plan)

        reader = fixture.reader
        if mode == "instance":
            monkeypatch.setattr(reader, "_inspect", MethodType(stronger, reader))
        elif mode == "class":
            monkeypatch.setattr(NativeRecoveryFactsVerifier, "_inspect", stronger)
        else:

            class Stronger(NativeRecoveryFactsVerifier):
                def _inspect(self, plan: RecoveryPlan) -> NativeRecoveryFacts:
                    return stronger(self, plan)

            reader = Stronger(fixture.config, fixture.environment)
        monkeypatch.setattr(NativeRecoverySourceReader, "inspect", counted_source)
        assert reader.inspect(fixture.plan).original == fixture.original
        assert stronger_calls == 2
        assert sources == 6
        _require_lock(fixture, held=False)


@pytest.mark.mysql
def test_closed_foreign_or_third_terminal_window_observation_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with modern_failed_native_fixture(tmp_path, monkeypatch) as fixture:
        with (
            pytest.raises(RecoveryRejected),
            _terminal_workspace_window(
                fixture.config, fixture.environment, fixture.plan.source
            ) as incomplete,
        ):
            incomplete.observe(
                fixture.original,
                fixture.capture,
                permissions=fixture.plan.permissions,
                supplement=fixture.plan.scope_supplement,
            )
        _require_lock(fixture, held=False)
        with _terminal_workspace_window(
            fixture.config, fixture.environment, fixture.plan.source
        ) as window:

            def observe() -> None:
                window.observe(
                    fixture.original,
                    fixture.capture,
                    permissions=fixture.plan.permissions,
                    supplement=fixture.plan.scope_supplement,
                )

            with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(RecoveryRejected):
                pool.submit(observe).result()

            async def foreign_async_task() -> None:
                observe()

            with pytest.raises(RecoveryRejected):
                asyncio.run(foreign_async_task())
            observe()
            observe()
            with pytest.raises(RecoveryRejected):
                observe()
        with pytest.raises(RecoveryRejected):
            observe()
        _require_lock(fixture, held=False)
