"""Whole current-account survey isolation preserves exact facts and owned lifecycle."""

from __future__ import annotations

import io
import json
import logging
import math
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, cast

import pydantic
import pytest

from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.manager import legacy_local_execution as legacy
from ai_software_engineer.manager import local_survey_observation as observation
from ai_software_engineer.manager import local_survey_worker as worker
from ai_software_engineer.manager.baseline_production import ProductionBaselineFactCollector
from ai_software_engineer.manager.dispatch import DeliveryAllocation
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.manager.legacy_containment import LocalBootObservation
from ai_software_engineer.manager.legacy_local_execution import LegacyLocalExecutionSurvey
from ai_software_engineer.manager.local_survey_observation import (
    IsolatedLegacyLocalExecutionObserver,
    LocalSurveyObservationError,
    LocalSurveyRequest,
    LocalSurveyResult,
)
from ai_software_engineer.owned_processes import HostOwnedProcessRegistry, OwnedProcessObservation
from ai_software_engineer.owned_sessions import OwnedProcessIdentity
from ai_software_engineer.owned_spawn import OwnedQuerySpawn, spawn_owned_query
from ai_software_engineer.store import TaskRepository
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue

BOOT = LocalBootObservation(
    machine_sha256="a" * 64,
    boot_session_sha256="b" * 64,
    booted_at=datetime(2026, 1, 1, tzinfo=UTC),
)


def request(root: Path) -> LocalSurveyRequest:
    native_boot = "fixture-native-boot"
    identity = OwnedProcessIdentity(
        process_id=os.getpid(), group_id=10, session_id=10, birth_identity="fixture-birth"
    )
    started = time.monotonic()
    return LocalSurveyRequest.create(
        root, BOOT, os.getuid(), native_boot, identity, started, started + 5
    )


def survey(value: LocalSurveyRequest, **updates: object) -> LegacyLocalExecutionSurvey:
    return LegacyLocalExecutionSurvey.create(
        **{
            "worktree_path": value.root,
            "machine_sha256": value.boot.machine_sha256,
            "boot_session_sha256": value.boot.boot_session_sha256,
            "account_sha256": observation._account_digest(value.boot, value.uid),
            "observed_at": datetime.now(UTC),
            "scanner_version": "local-execution-v1",
            "blockers": (),
            **updates,
        }
    )


def result(value: LocalSurveyRequest, worker_pid: int = 777) -> LocalSurveyResult:
    return LocalSurveyResult(
        request_sha256=value.request_sha256,
        worker_pid=worker_pid,
        survey=survey(value),
        incomplete_phase=None,
    )


def test_exact_request_digest_binds_all_fields(tmp_path: Path) -> None:
    value = request(tmp_path)
    assert LocalSurveyRequest.decode(value.encode()) == value
    payload = json.loads(value.encode())
    for key, changed in [
        ("root", "/elsewhere"),
        ("uid", value.uid + 1),
        ("parent_boot_identity", "other"),
        ("parent_identity", {**payload["parent_identity"], "birth_identity": "other"}),
        ("boot", {**payload["boot"], "machine_sha256": "c" * 64}),
        ("started", value.started + 1),
        ("deadline", value.deadline + 1),
        ("extra", 1),
    ]:
        with pytest.raises(LocalSurveyObservationError):
            LocalSurveyRequest.decode(json.dumps({**payload, key: changed}).encode())


@pytest.mark.parametrize(
    "field",
    [
        "protocol",
        "root",
        "boot",
        "uid",
        "parent_boot_identity",
        "parent_identity",
        "started",
        "deadline",
        "request_sha256",
    ],
)
def test_every_request_field_is_mandatory(tmp_path: Path, field: str) -> None:
    payload = json.loads(request(tmp_path).encode())
    payload.pop(field)
    with pytest.raises(LocalSurveyObservationError):
        LocalSurveyRequest.decode(json.dumps(payload).encode())


@pytest.mark.parametrize(
    "failure",
    [
        "uid_bool",
        "pid_bool",
        "birth_missing",
        "boot_missing",
        "deadline_nan",
        "deadline_bool",
        "relative",
        "traversal",
        "duplicate",
        "truncated",
        "oversize",
        "utf8",
        "deep",
    ],
)
def test_bad_request_types_bounds_and_nested_keys_reject(tmp_path: Path, failure: str) -> None:
    payload = json.loads(request(tmp_path).encode())
    if failure == "uid_bool":
        payload["uid"] = True
    elif failure == "pid_bool":
        payload["parent_identity"]["process_id"] = True
    elif failure == "birth_missing":
        payload["parent_identity"].pop("birth_identity")
    elif failure == "boot_missing":
        payload["boot"].pop("booted_at")
    elif failure == "deadline_nan":
        payload["deadline"] = math.nan
    elif failure == "deadline_bool":
        payload["deadline"] = True
    elif failure == "relative":
        payload["root"] = "relative"
    elif failure == "traversal":
        payload["root"] = "/a/../b"
    raw = json.dumps(payload).encode()
    if failure == "duplicate":
        raw = raw.replace(b'"process_id":', b'"process_id":1,"process_id":')
    elif failure == "truncated":
        raw = raw[:-1]
    elif failure == "oversize":
        raw = b"x" * (64 * 1024 + 1)
    elif failure == "utf8":
        raw = b"\xff"
    elif failure == "deep":
        raw = b"[" * 2000
    with pytest.raises(LocalSurveyObservationError):
        LocalSurveyRequest.decode(raw)


@pytest.mark.parametrize(
    "field", ["protocol", "request_sha256", "worker_pid", "survey", "incomplete_phase"]
)
def test_every_result_field_is_mandatory(tmp_path: Path, field: str) -> None:
    payload = json.loads(result(request(tmp_path)).encode())
    payload.pop(field)
    with pytest.raises(LocalSurveyObservationError):
        LocalSurveyResult.decode(json.dumps(payload).encode())


@pytest.mark.parametrize(
    "failure",
    [
        "sha",
        "worker",
        "root",
        "machine",
        "boot",
        "account",
        "scanner",
        "digest",
        "phase",
        "extra",
        "duplicate",
        "worker_bool",
        "family",
    ],
)
def test_complete_result_binding_rejects_foreign_or_malformed_facts(
    tmp_path: Path, failure: str
) -> None:
    value = request(tmp_path)
    report = result(value)
    fields = {
        "root": ("worktree_path", "/elsewhere"),
        "machine": ("machine_sha256", "c" * 64),
        "boot": ("boot_session_sha256", "c" * 64),
        "account": ("account_sha256", "c" * 64),
        "scanner": ("scanner_version", "different"),
    }
    if failure in fields:
        key, changed = fields[failure]
        report = report.model_copy(update={"survey": survey(value, **{key: changed})})
    payload = json.loads(report.encode())
    if failure == "sha":
        payload["request_sha256"] = "0" * 64
    elif failure == "worker":
        payload["worker_pid"] = 778
    elif failure == "digest":
        payload["survey"]["survey_sha256"] = "0" * 64
    elif failure == "phase":
        payload["incomplete_phase"] = "private raw argv"
    elif failure == "extra":
        payload["private"] = "denied"
    elif failure == "worker_bool":
        payload["worker_pid"] = True
    elif failure == "family":
        payload["protocol"] = "other"
    raw = json.dumps(payload).encode()
    if failure == "duplicate":
        raw = raw.replace(b'"worker_pid":', b'"worker_pid":1,"worker_pid":')
    with pytest.raises(LocalSurveyObservationError):
        LocalSurveyResult.decode(raw).require_request(value, 777)


class FakeProcess:
    pid = 777

    def __init__(self, failure: str) -> None:
        self.returncode = 1 if failure == "status" else 0
        self.failure = failure
        self.wait_timeout: float | None = None

    def wait(self, timeout: float) -> int:
        self.wait_timeout = timeout
        if self.failure == "timeout":
            raise subprocess.TimeoutExpired("private survey fixture", timeout)
        return self.returncode


@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "status",
        "stderr",
        "timeout",
        "oversize",
        "truncated",
        "sha",
        "worker",
        "stop",
        "startup",
        "finish_deadline",
    ],
)
def test_single_fixed_owned_launch_and_complete_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    value = request(tmp_path)
    process = FakeProcess(failure)
    owned = cast(OwnedProcessObservation, object())
    finished: list[tuple[object, object, bool]] = []

    def spawn(
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        cwd: Path | None = None,
        stdin: int = subprocess.DEVNULL,
        stdout: int | BinaryIO = subprocess.PIPE,
        stderr: int | BinaryIO = subprocess.PIPE,
    ) -> OwnedQuerySpawn:
        assert argv == (
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(Path(observation.__file__).with_name("local_survey_worker.py")),
        )
        assert cwd == Path("/") and dict(environment) == {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "C",
            "LC_ALL": "C",
        }
        assert not isinstance(stdout, int) and not isinstance(stderr, int)
        actual = LocalSurveyRequest.decode(os.read(stdin, 64 * 1024))
        assert actual == value
        payload = result(value, 778 if failure == "worker" else 777).encode()
        if failure == "sha":
            payload = payload.replace(value.request_sha256.encode(), b"0" * 64)
        elif failure == "oversize":
            payload = b"x" * (64 * 1024 + 1)
        elif failure == "truncated":
            payload = payload[:-1]
        stdout.write(payload)
        if failure == "stderr":
            stderr.write(b"private secret error")
        if failure == "startup":
            monkeypatch.setattr(time, "monotonic", lambda: value.deadline + 1)
        return OwnedQuerySpawn(cast(subprocess.Popen[bytes], process), owned)

    def finish(
        actual: subprocess.Popen[bytes], original: OwnedProcessObservation, *, output_drained: bool
    ) -> None:
        finished.append((actual, original, output_drained))
        if failure == "stop":
            raise RuntimeError("private secret stop")
        if failure == "finish_deadline":
            monkeypatch.setattr(time, "monotonic", lambda: value.deadline + 1)

    monkeypatch.setattr(observation, "spawn_owned_query", spawn)
    monkeypatch.setattr(observation, "finish_owned_process", finish)
    if failure == "none":
        observed = observation._observe_survey_worker(value)
        observed.require_request(value, 777)
    else:
        with pytest.raises(LocalSurveyObservationError) as caught:
            observation._observe_survey_worker(value)
        assert str(caught.value) == "isolated local execution survey incomplete"
    assert finished == [(process, owned, True)]


@pytest.mark.parametrize("failure", ["absent", "foreign", "uid", "error"])
def test_facade_failure_is_exact_incomplete_with_safe_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    value = request(tmp_path)

    def capture(pid: int) -> tuple[str, OwnedProcessIdentity | None]:
        if failure == "error":
            raise RuntimeError("secret argv must not escape")
        return (
            value.parent_boot_identity,
            None
            if failure == "absent"
            else value.parent_identity.model_copy(update={"process_id": pid + 1}),
        )

    monkeypatch.setattr(observation, "observe_current_process", capture)
    if failure == "uid":
        monkeypatch.setattr(os, "geteuid", lambda: value.uid + 1)
    report = IsolatedLegacyLocalExecutionObserver().observe(worktree_root=tmp_path, boot=BOOT)
    assert report.blockers == ("PROCESS_SCAN_INCOMPLETE",)
    report.validate_integrity()
    assert "secret argv" not in caplog.text and str(tmp_path) not in caplog.text


@pytest.mark.parametrize(
    "argv",
    [
        ("/bin/ps", "-ww", "-U", "501", "-o", "pid=,ppid=,uid=,stat=,lstart=,command="),
        ("/usr/sbin/lsof", "-n", "-P", "-a", "-u", "501", "-F0pftn"),
        ("/usr/sbin/lsof", "-n", "-P", "-a", "-u", "501", "-p", "101,102", "-F0pftn"),
    ],
)
def test_exact_fixed_queries_allow_only_expected_forms(argv: tuple[str, ...]) -> None:
    worker._require_fixed_query(argv, 501)


@pytest.mark.parametrize(
    "tail",
    [
        "102,101",
        "101,101",
        "0",
        "-1",
        "True",
        "101;id",
        "\u0661",
        "01",
        "2147483648",
        "",
        ",".join(str(pid) for pid in range(1, 4098)),
    ],
)
def test_targeted_lsof_pid_tokens_are_exact_and_bounded(tail: str) -> None:
    with pytest.raises(legacy._IncompleteSurvey):
        worker._require_fixed_query(
            ("/usr/sbin/lsof", "-n", "-P", "-a", "-u", "501", "-p", tail, "-F0pftn"), 501
        )


@pytest.mark.parametrize(
    "argv",
    [
        ("/bin/sh", "-c", "id"),
        ("/bin/ps",),
        ("/usr/sbin/lsof", "-n", "-P", "-a", "-u", "502", "-F0pftn"),
        ("/usr/sbin/lsof", "-n", "-P", "-a", "-u", "501", "-F0pftn", "extra"),
    ],
)
def test_other_query_argv_refuse_before_start(argv: tuple[str, ...]) -> None:
    with pytest.raises(legacy._IncompleteSurvey):
        worker._require_fixed_query(argv, 501)


@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "parent_pid",
        "uid",
        "euid",
        "sid",
        "pgid",
        "boot",
        "birth",
        "gone",
        "native_uid",
        "native_gone",
    ],
)
def test_worker_identity_binds_actual_parent_and_same_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    value = request(tmp_path).model_copy(
        update={
            "uid": 501,
            "parent_boot_identity": "darwin:1:0",
            "parent_identity": OwnedProcessIdentity(
                process_id=101, group_id=10, session_id=10, birth_identity="darwin-time:123:45"
            ),
        }
    )
    monkeypatch.setattr(os, "getpid", lambda: 777)
    monkeypatch.setattr(os, "getppid", lambda: 102 if failure == "parent_pid" else 101)
    monkeypatch.setattr(os, "getsid", lambda pid: 778 if failure == "sid" else 777)
    monkeypatch.setattr(os, "getpgrp", lambda: 778 if failure == "pgid" else 777)
    monkeypatch.setattr(os, "getuid", lambda: 502 if failure == "uid" else 501)
    monkeypatch.setattr(os, "geteuid", lambda: 502 if failure == "euid" else 501)
    monkeypatch.setattr(sys, "platform", "darwin")
    identity = (
        value.parent_identity.model_copy(update={"birth_identity": "darwin-time:124:45"})
        if failure == "birth"
        else value.parent_identity
    )
    monkeypatch.setattr(
        worker,
        "observe_current_process",
        lambda pid: (
            "other" if failure == "boot" else value.parent_boot_identity,
            None if failure == "gone" else identity,
        ),
    )

    def birth(pid: int, deadline: float) -> str:
        if failure == "native_uid":
            raise legacy._IncompleteSurvey
        if failure == "native_gone":
            raise ProcessLookupError
        return "123:45"

    monkeypatch.setattr(worker, "_parent_birth", birth)
    if failure == "none":
        worker._require_worker_parent(value)
    else:
        with pytest.raises((legacy._IncompleteSurvey, ProcessLookupError)):
            worker._require_worker_parent(value)


@pytest.mark.parametrize("failure", ["none", "timeout", "stderr", "status"])
def test_inner_query_is_exact_actual_popen_in_outer_sid_and_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    value = request(tmp_path)
    killed: list[str] = []

    class Process:
        pid = 888
        returncode: int | None = None
        calls = 0

        def wait(self, timeout: float) -> int:
            self.calls += 1
            if failure == "timeout" and self.calls == 1:
                raise subprocess.TimeoutExpired("fixed", timeout)
            self.returncode = 1 if failure == "status" else 0
            return self.returncode

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            killed.append("actual_popen")

    process = Process()

    def popen(
        argv: tuple[str, ...],
        *,
        stdin: int,
        stdout: BinaryIO,
        stderr: BinaryIO,
        cwd: Path,
        env: Mapping[str, str],
        shell: bool,
        start_new_session: bool,
        close_fds: bool,
    ) -> Process:
        assert argv[0] == "/bin/ps" and stdin == subprocess.DEVNULL
        assert cwd == Path("/") and dict(env) == {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "C",
            "LC_ALL": "C",
        }
        assert not shell and not start_new_session and close_fds
        stdout.write(b"complete fixture ps bytes")
        if failure == "stderr":
            stderr.write(b"private details")
        return process

    monkeypatch.setattr("ai_software_engineer.manager.local_survey_worker.subprocess.Popen", popen)
    monkeypatch.setattr(os, "getsid", lambda pid: os.getpid())
    monkeypatch.setattr(os, "getpgrp", os.getpid)
    engine = worker._WorkerSurveyEngine(value)
    token = legacy._DEADLINE.set(value.deadline)
    try:
        argv = (
            "/bin/ps",
            "-ww",
            "-U",
            str(value.uid),
            "-o",
            "pid=,ppid=,uid=,stat=,lstart=,command=",
        )
        if failure == "none":
            assert engine._query(argv) == b"complete fixture ps bytes"
        else:
            with pytest.raises((legacy._IncompleteSurvey, subprocess.TimeoutExpired)):
                engine._query(argv)
    finally:
        legacy._DEADLINE.reset(token)
    assert killed == (["actual_popen"] if failure == "timeout" else [])
    assert process.returncode is not None


@pytest.mark.parametrize("raw", [b"{}", b"{", b"x" * (64 * 1024 + 1), b"\xff"])
def test_worker_emits_no_partial_result_for_invalid_request(raw: bytes) -> None:
    output = io.BytesIO()
    assert worker._execute(io.BytesIO(raw), output) == 1
    assert not output.getvalue()


def test_real_facade_scans_without_new_public_shape_and_releases_ownership(tmp_path: Path) -> None:
    registry = HostOwnedProcessRegistry()
    started = time.monotonic()
    with registry.operation_scope("operation_real_complete_local_survey"):
        report = IsolatedLegacyLocalExecutionObserver().observe(worktree_root=tmp_path, boot=BOOT)
    report.validate_integrity()
    assert "PROCESS_SCAN_INCOMPLETE" not in report.blockers
    assert (
        report.worktree_path == str(tmp_path.resolve())
        and report.scanner_version == "local-execution-v1"
    )
    assert time.monotonic() - started < 5
    assert not registry.snapshot()
    registry.require_stopped()


def test_expired_original_deadline_never_starts_whole_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = request(tmp_path)
    monkeypatch.setattr(time, "monotonic", lambda: value.deadline)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("expired survey must not spawn")

    monkeypatch.setattr(observation, "spawn_owned_query", forbidden)
    with pytest.raises(LocalSurveyObservationError):
        observation._observe_survey_worker(value)


def test_whole_worker_resolves_complete_captured_lsof_without_another_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = request(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("whole worker must not spawn path helpers")

    monkeypatch.setattr(legacy, "observe_mac_paths_in_process", forbidden)
    alias = tmp_path / "alias"
    root = tmp_path / "root"
    root.mkdir()
    alias.symlink_to(root)
    token = legacy._DEADLINE.set(value.deadline)
    try:
        assert worker._WorkerSurveyEngine(value)._inspect_mac_paths(
            f"p101\0\nfcwd\0tDIR\0n/elsewhere\0\nf4\0tREG\0n{alias}/draft.py\0\n".encode(),
            root,
            ignored_pids=frozenset(),
            cwd_blocker_pids=frozenset(),
        ) == ({101}, {"WORKTREE_PROCESS_ACTIVE"})
    finally:
        legacy._DEADLINE.reset(token)


@pytest.mark.parametrize("previous_propagate", [True, False])
def test_worker_restores_log_propagation_on_complete_failure(previous_propagate: bool) -> None:
    logger = logging.getLogger("ai_software_engineer.manager.legacy_local_execution")
    old = logger.propagate
    previous_handlers = tuple(logger.handlers)
    logger.propagate = previous_propagate
    try:
        assert worker._execute(io.BytesIO(b"{}"), io.BytesIO()) == 1
        assert logger.propagate == previous_propagate
        assert tuple(logger.handlers) == previous_handlers
    finally:
        logger.propagate = old


def test_real_failed_whole_launch_reaps_live_same_session_peer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = request(tmp_path)
    actual_spawn = spawn_owned_query
    peer_marker = tmp_path / "peer-started"
    child = "import time; time.sleep(30)"
    script = (
        "import pathlib, subprocess, sys; "
        f"peer = subprocess.Popen([sys.executable, '-I', '-S', '-B', '-c', {child!r}]); "
        f"pathlib.Path({str(peer_marker)!r}).write_text(str(peer.pid)); "
        "raise SystemExit(1)"
    )

    def spawn(
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        cwd: Path | None = None,
        stdin: int = subprocess.DEVNULL,
        stdout: int | BinaryIO = subprocess.PIPE,
        stderr: int | BinaryIO = subprocess.PIPE,
    ) -> OwnedQuerySpawn:
        assert Path(argv[-1]).name == "local_survey_worker.py"
        return actual_spawn(
            (sys.executable, "-I", "-S", "-B", "-c", script),
            environment=environment,
            cwd=cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(observation, "spawn_owned_query", spawn)
    registry = HostOwnedProcessRegistry()
    with (
        registry.operation_scope("operation_failed_whole_worker_peer_cleanup"),
        pytest.raises(LocalSurveyObservationError),
    ):
        observation._observe_survey_worker(value)
    assert peer_marker.read_text().isdigit()
    assert not registry.snapshot()
    registry.require_stopped()


def test_whole_worker_fixed_loader_does_not_execute_startup_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation = tmp_path / "interpreter"
    binaries = installation / "bin"
    binaries.mkdir(parents=True)
    python = binaries / "python"
    python.symlink_to(sys.executable)
    dependencies = (
        installation
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    dependencies.mkdir(parents=True)
    real_dependencies = Path(pydantic.__file__).parent.parent
    for entry in real_dependencies.iterdir():
        if entry.name not in {"sitecustomize.py", "unexpected-startup.pth"}:
            (dependencies / entry.name).symlink_to(entry)
    marker = tmp_path / "unexpected-startup-code"
    startup = f"import pathlib; pathlib.Path({str(marker)!r}).touch()\n"
    (dependencies / "sitecustomize.py").write_text(startup)
    (dependencies / "unexpected-startup.pth").write_text(startup)
    monkeypatch.setattr(sys, "executable", str(python))
    registry = HostOwnedProcessRegistry()
    with registry.operation_scope("operation_no_site_whole_worker"):
        report = IsolatedLegacyLocalExecutionObserver().observe(worktree_root=tmp_path, boot=BOOT)
    assert "PROCESS_SCAN_INCOMPLETE" not in report.blockers
    assert not marker.exists()
    assert not registry.snapshot()
    registry.require_stopped()


def test_worker_checks_fresh_parent_before_after_and_final_with_original_birth_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = request(tmp_path)
    events: list[str] = []

    def parent(actual: LocalSurveyRequest) -> None:
        assert actual == value
        events.append("parent")

    class Engine(worker._WorkerSurveyEngine):
        def _processes(self, uid: int) -> dict[int, legacy._Process]:
            assert uid == value.uid
            events.append("inventory")
            return {101: legacy._Process(101, 1, "S", "fixture-birth", "/bin/zsh", "zsh")}

        def _desktop_sandbox_chains(
            self, processes: dict[int, legacy._Process], root: Path
        ) -> dict[int, tuple[legacy._DesktopProcessIdentity, ...]]:
            events.append("desktop")
            return {}

        def _mac_paths(
            self,
            uid: int,
            root: Path,
            *,
            pids: tuple[int, ...] | None = None,
            ignored_pids: frozenset[int] = frozenset(),
            cwd_blocker_pids: frozenset[int] = frozenset(),
        ) -> tuple[set[int], set[legacy.LegacyLocalExecutionBlocker]]:
            events.append("paths")
            return {101}, set()

        def _birth(self, pid: int) -> str:
            events.append("final-birth")
            return "fixture-birth"

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(worker, "_require_worker_parent", parent)
    monkeypatch.setattr(worker, "_WorkerSurveyEngine", Engine)
    output = io.BytesIO()
    assert worker._execute(io.BytesIO(value.encode()), output) == 0
    LocalSurveyResult.decode(output.getvalue()).survey.require_idle()
    assert events == [
        "parent",
        "parent",
        "inventory",
        "desktop",
        "paths",
        "inventory",
        "parent",
        "desktop",
        "parent",
        "final-birth",
        "parent",
    ]


@pytest.mark.parametrize("inject_observer", [False, True])
def test_production_collector_constructor_defaults_to_isolation_and_preserves_injection(
    tmp_path: Path,
    inject_observer: bool,
) -> None:
    class Allocation:
        task_id = "task_constructor_only"
        validations = 0

        def validate_integrity(self) -> None:
            self.validations += 1

    class Observer:
        def observe(
            self, *, worktree_root: Path, boot: LocalBootObservation
        ) -> LegacyLocalExecutionSurvey:
            raise AssertionError("constructor must not scan or access production resources")

    allocation = Allocation()
    injected = Observer()
    unused = object()
    collector = ProductionBaselineFactCollector(
        allocation=cast(DeliveryAllocation, allocation),
        scope=EngineeringScope(
            team_id="team",
            project_id="project",
            repository_id="repo",
            repository_root=str(tmp_path),
        ),
        requirement_id="requirement_constructor_only",
        repository=cast(TaskRepository, unused),
        queue=cast(MySqlRoleQueue, unused),
        artifacts=cast(ArtifactStore, unused),
        git=cast(GitWorktreeManager, unused),
        sidecar_state=tmp_path,
        locks_root=tmp_path,
        permissions=cast(AgentPermissions, unused),
        source_native_rules=(),
        runtime_manifest_sha256="a" * 64,
        inputs=cast(StoredCoderExecutionInputResolver, unused),
        local_execution_observer=injected if inject_observer else None,
    )
    assert allocation.validations == 1
    assert collector.artifacts.task_id == allocation.task_id
    if inject_observer:
        assert collector.local_execution_observer is injected
    else:
        assert isinstance(collector.local_execution_observer, IsolatedLegacyLocalExecutionObserver)
