"""Actual modern failed recovery input, with exclusive ownership of the test DB.

Consumers use the ``mysql`` marker with a local empty ``isolated_mysql_facts``
fixture override: the global autouse reset must not precede the shared probe guard.
This helper owns every reset after exact database and exclusivity admission.
Only the model-client port is offline; native stages, claims and stop records are real.
"""

from __future__ import annotations

import fcntl
import json
import os
import shlex
import signal
import stat
import subprocess
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

import ai_software_engineer.manager.production_backend as production_backend
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.recovery import RecoveryScope
from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryPlan
from ai_software_engineer.recovery.native import NativeRecoverySource, NativeRecoverySourceReader
from ai_software_engineer.recovery.workspace_snapshot import read_terminal_workspace_snapshot
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from tests.manager.test_production_backend import _git
from tests.mysql_safety import (
    _MUTABLE_FACT_TABLES,
    require_isolated_mysql_test_database,
    reset_mysql_test_facts,
)
from tests.recovery.execution_fixture import OfflineRecoveryClients, offline_failed_codex

_DATABASE = "ai_software_engineer_test"
_LOCK_PATH = Path("/tmp/ase-ai-software-engineer-test-probe.lock")
_LOCK_NAME = "ase:isolated-probe:" + _DATABASE


@dataclass(frozen=True)
class ModernFailedNativeFixture:
    config: ProductionConfig
    environment: Mapping[str, str] = field(repr=False)
    project: Path
    reader: NativeRecoveryFactsVerifier
    original: NativeRecoverySource
    capture: CapturedChanges
    plan: RecoveryPlan


@dataclass
class _ExclusiveDatabase:
    connection: Connection
    owned_processes_stopped: bool = False


def _progress(root: Path, began: float, stage: str) -> None:
    record = {"stage": stage, "elapsed_seconds": round(time.monotonic() - began, 3)}
    descriptor = os.open(
        root / "facts-window-fixture-progress.jsonl",
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(json.dumps(record) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    print("facts-window-fixture: " + json.dumps(record), flush=True)


def _require_no_other_sessions(connection: Connection) -> None:
    with connection.cursor(DictCursor) as cursor:
        cursor.execute(
            "SELECT ID FROM information_schema.PROCESSLIST WHERE DB = %s AND ID <> CONNECTION_ID()",
            (_DATABASE,),
        )
        if cursor.fetchall():
            raise RuntimeError("isolated fixture database has another session; no reset allowed")


def _require_thirteen_empty_tables(connection: Connection) -> None:
    connection.rollback()
    with connection.cursor(DictCursor) as cursor:
        cursor.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()"
        )
        present = {row["TABLE_NAME"] for row in cursor.fetchall()}
        if len(_MUTABLE_FACT_TABLES) != 13 or not set(_MUTABLE_FACT_TABLES) <= present:
            raise RuntimeError("isolated fixture requires all 13 preinitialized fact tables")
        for table in _MUTABLE_FACT_TABLES:
            cursor.execute(f"SELECT COUNT(*) AS count FROM {table}")
            row = cursor.fetchone()
            if row is None or row["count"] != 0:
                raise RuntimeError("isolated fixture facts are not empty; no reset allowed")
    connection.rollback()


@contextmanager
def _exclusive_database(dsn: str, root: Path, began: float) -> Iterator[_ExclusiveDatabase]:
    require_isolated_mysql_test_database(dsn)
    if unquote(urlsplit(dsn).path.removeprefix("/")) != _DATABASE:
        raise pytest.UsageError("facts-window fixture only permits ai_software_engineer_test")
    descriptor = os.open(_LOCK_PATH, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    connection: Connection | None = None
    lock_acquired = False
    exclusive: _ExclusiveDatabase | None = None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or (info.st_dev, info.st_ino) != (_LOCK_PATH.stat().st_dev, _LOCK_PATH.stat().st_ino)
        ):
            raise RuntimeError("shared test database guard is not a private regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        connection = open_mysql_connection(dsn)
        with connection.cursor(DictCursor) as cursor:
            cursor.execute("SELECT DATABASE() AS database_name")
            row = cursor.fetchone()
            if row is None or row["database_name"] != _DATABASE:
                raise RuntimeError("connected database does not match the isolated fixture")
            cursor.execute("SELECT GET_LOCK(%s, 0) AS acquired", (_LOCK_NAME,))
            row = cursor.fetchone()
            if row is None or row["acquired"] != 1:
                raise RuntimeError("isolated test database probe lock is busy")
            lock_acquired = True
        _require_no_other_sessions(connection)
        _require_thirteen_empty_tables(connection)
        exclusive = _ExclusiveDatabase(connection)
        _progress(root, began, "exclusive_13_tables_empty")
        yield exclusive
    finally:
        try:
            if connection is not None and exclusive is not None:
                if not exclusive.owned_processes_stopped:
                    raise RuntimeError("fixture process stop unconfirmed; database facts preserved")
                _require_no_other_sessions(connection)
                reset_mysql_test_facts(dsn)
                _require_thirteen_empty_tables(connection)
                _progress(root, began, "cleanup_13_tables_empty")
        finally:
            if connection is not None:
                try:
                    if lock_acquired:
                        with connection.cursor(DictCursor) as cursor:
                            cursor.execute("SELECT RELEASE_LOCK(%s)", (_LOCK_NAME,))
                finally:
                    connection.rollback()
                    connection.close()
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _owned_processes(executable: Path) -> dict[int, str]:
    result = subprocess.run(
        ("ps", "-axo", "pid=,lstart=,args="),
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        env={"PATH": os.defpath, "LC_ALL": "C"},
    )
    owned: dict[int, str] = {}
    for line in result.stdout.splitlines():
        columns = line.split(maxsplit=6)
        if len(columns) != 7:
            continue
        try:
            arguments = shlex.split(columns[6])
        except ValueError:
            continue
        if str(executable) in arguments:
            owned[int(columns[0])] = " ".join(columns[1:6])
    return owned


def _stop_owned_processes(executable: Path) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid, birth in _owned_processes(executable).items():
            if _owned_processes(executable).get(pid) == birth:
                with suppress(ProcessLookupError):
                    os.kill(pid, sig)
        if not _owned_processes(executable):
            break
        time.sleep(0.05)
    if _owned_processes(executable):
        raise RuntimeError("owned offline fixture process is still present; facts preserved")


@contextmanager
def modern_failed_native_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ModernFailedNativeFixture]:
    """Generate actual failed Coder lineage, without approving or dispatching recovery."""
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    began = time.monotonic()
    executable = tmp_path / "offline-failed-codex"
    _progress(tmp_path, began, "initial")
    with _exclusive_database(dsn, tmp_path, began) as exclusive:
        try:
            project = tmp_path / "project"
            project.mkdir()
            (project / "hello.txt").write_text("hello\n", encoding="utf-8")
            _git("init", "-b", "main", cwd=project)
            _git("add", "hello.txt", cwd=project)
            _git("commit", "-m", "initial", cwd=project)
            config = ProductionConfig(
                platform_root=str(tmp_path / "platform"),
                default_project_id="project_test",
                default_project_name="Test Project",
                codex_executable=offline_failed_codex(tmp_path),
                live_model_execution=True,
                model_routes=(
                    ProviderRouteConfig(
                        provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
                    ),
                ),
            )
            executable = Path(config.codex_executable).resolve()
            if not executable.is_relative_to(tmp_path.resolve()):
                raise RuntimeError("offline fixture executable escaped its private directory")
            environment = {"ASE_MYSQL_DSN": dsn, "PATH": os.environ.get("PATH", os.defpath)}
            monkeypatch.setattr(
                production_backend,
                "ConfiguredStructuredClientFactory",
                lambda *_: OfflineRecoveryClients(),
            )
            host = TeamHost(
                config=config, environment=environment, structured_clients=OfflineRecoveryClients()
            )
            entry = host.project_entry()
            started = entry.start(
                StartProjectDelivery(repository_root=str(project), requirement="Change greeting.")
            )
            _progress(tmp_path, began, "product_ready")
            failed = entry.approve(
                ApproveProductSpec(
                    delivery_id=started.checkpoint.delivery_id,
                    expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
                    approval_reference="offline-original-approval",
                )
            ).checkpoint
            assert failed.stage.value == "BLOCKED" and failed.candidate_revision is None
            _progress(tmp_path, began, "actual_failed_coder_stopped")
            original = NativeRecoverySourceReader(config, environment).discover_failed_coder(
                RecoveryScope(
                    team_id=config.team_id,
                    repository_id=failed.repository_id,
                    repository_root=str(project),
                    delivery_id=failed.delivery_id,
                )
            )
            assert original.task.interruption_continuation_policy is not None
            assert original.task.branch_name is not None
            manager = GitWorktreeManager(
                project,
                Path(config.platform_root) / "worktrees" / failed.repository_id,
                branch_names={original.task.id: original.task.branch_name},
            )
            worktree = manager.recover(
                WorktreeSpec(
                    task_id=original.task.id,
                    role=AgentRole.CODER,
                    attempt=1,
                    source_revision=original.worktree_revision,
                )
            )
            capture = CapturedChanges.from_capture(
                manager.capture_changes(
                    worktree,
                    original.permissions,
                    denied_paths=original.denied_paths,
                    base_revision=original.source.effective_base_revision,
                )
            )
            _progress(tmp_path, began, "actual_capture_complete")
            snapshot = read_terminal_workspace_snapshot(config, environment, original, capture)
            assert snapshot is not None
            _progress(tmp_path, began, "complete_terminal_snapshot")
            plan = RecoveryPlan.create(
                source=original.source,
                capture=capture,
                workspace_snapshot=snapshot,
                target_base_revision=original.source.effective_base_revision,
                target_preparation_sha256=original.preparation.preparation_sha256,
                target_branch_name=original.task.branch_name + "-window",
                permissions=original.permissions,
                target_permissions=original.permissions,
                denied_paths=original.denied_paths,
                created_at=datetime.now(UTC),
            )
            plan.validate_integrity()
            plan.require_execution_supported()
            yield ModernFailedNativeFixture(
                config,
                environment,
                project,
                NativeRecoveryFactsVerifier(config, environment),
                original,
                capture,
                plan,
            )
        finally:
            _stop_owned_processes(executable)
            exclusive.owned_processes_stopped = True
            _progress(tmp_path, began, "owned_processes_zero")
