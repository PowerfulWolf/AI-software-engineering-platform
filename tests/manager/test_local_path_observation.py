"""Bounded path parsing preserves complete lsof observations in an owned child."""

from __future__ import annotations

import io
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO, cast

import pydantic
import pytest

from ai_software_engineer.manager import local_path_observation as observation
from ai_software_engineer.manager.local_path_observation import (
    LocalPathObservationError,
    MacPathObservationRequest,
    MacPathObservationResult,
    inspect_mac_paths,
    observe_mac_paths_in_process,
)
from ai_software_engineer.owned_processes import HostOwnedProcessRegistry, OwnedProcessObservation
from ai_software_engineer.owned_spawn import OwnedQuerySpawn


def fixture_body(root: Path) -> bytes:
    return f"p101\0\nfcwd\0tDIR\0n/elsewhere\0\nf4\0tREG\0n{root}/draft.py\0\n".encode()


def test_alias_and_deleted_open_files_are_resolved_completely(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    alias = tmp_path / "outside-alias"
    alias.symlink_to(root)
    body = fixture_body(alias).replace(b"draft.py\0", b"draft.py (deleted)\0")
    assert inspect_mac_paths(body, root, frozenset(), frozenset(), time.monotonic() + 2) == (
        {101},
        {"WORKTREE_PROCESS_ACTIVE"},
    )


@pytest.mark.parametrize("ignored", [False, True])
@pytest.mark.parametrize("cwd_blocker", [False, True])
def test_cwd_coverage_and_blocker_exclusions_are_independent(
    tmp_path: Path, ignored: bool, cwd_blocker: bool
) -> None:
    body = f"p101\0fcwd\0tDIR\0n{tmp_path}\0".encode()
    covered, blockers = inspect_mac_paths(
        body,
        tmp_path,
        frozenset({101}) if ignored else frozenset(),
        frozenset({101}) if cwd_blocker else frozenset(),
        time.monotonic() + 2,
    )
    assert covered == {101}
    assert bool(blockers) == (cwd_blocker and not ignored)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"p101\0fcwd\0tDIR\0n/elsewhere",
        b"pno\0",
        b"p101\0xunknown\0",
        b"n/elsewhere\0",
        b"f4\0n/elsewhere\0",
        b"p101\0fcwd\0tREG\0n/elsewhere\0",
        b"p101\0fcwd\0tDIR\0nrelative\0",
        b"p101\0f4\0tREG\0n/stat (stat: permission)\0",
        b"p101\0f4\0tREG\0n/readlink (readlink: permission)\0",
        b"p101\0f4\0tREG\0n/invalid-\xff\0",
    ],
)
def test_malformed_body_fails_closed(tmp_path: Path, body: bytes) -> None:
    with pytest.raises(LocalPathObservationError):
        inspect_mac_paths(body, tmp_path, frozenset(), frozenset(), time.monotonic() + 2)


def test_fixed_body_process_and_file_limits(tmp_path: Path) -> None:
    for body in (
        b"p1\0" * 4097,
        b"p1\0" + b"f4\0" * 65537,
        b"p1\0" + b"x" * (8 * 1024 * 1024) + b"\0",
    ):
        with pytest.raises(LocalPathObservationError):
            inspect_mac_paths(body, tmp_path, frozenset(), frozenset(), time.monotonic() + 3)


@pytest.mark.parametrize("deadline", [0.0, math.inf, -math.inf, math.nan])
def test_invalid_deadline_refuses_before_resolve(tmp_path: Path, deadline: float) -> None:
    with pytest.raises(LocalPathObservationError):
        inspect_mac_paths(fixture_body(tmp_path), tmp_path, frozenset(), frozenset(), deadline)


def test_deadline_checked_after_each_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1.0]
    resolved: list[str] = []

    def resolve(path: Path, strict: bool = False) -> Path:
        resolved.append(str(path))
        now[0] = 3.0
        return path

    monkeypatch.setattr(
        "ai_software_engineer.manager.local_path_observation.time.monotonic", lambda: now[0]
    )
    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(LocalPathObservationError):
        inspect_mac_paths(fixture_body(tmp_path), tmp_path, frozenset(), frozenset(), 2.0)
    assert resolved == ["/elsewhere"]


def test_request_digest_binds_all_inputs_and_rejects_unknown_fields(tmp_path: Path) -> None:
    request = MacPathObservationRequest.create(
        fixture_body(tmp_path), tmp_path, frozenset({2}), frozenset({3}), time.monotonic() + 5
    )
    assert MacPathObservationRequest.decode(request.encode()) == request
    payload = json.loads(request.encode())
    for name, changed in (
        ("body", "p2\u0000"),
        ("root", "/another"),
        ("ignored_pids", [4]),
        ("cwd_blocker_pids", [4]),
        ("deadline", request.deadline + 1),
        ("extra", "refused"),
    ):
        with pytest.raises(LocalPathObservationError):
            MacPathObservationRequest.decode(json.dumps({**payload, name: changed}).encode())
    with pytest.raises(LocalPathObservationError):
        MacPathObservationRequest.decode(
            request.encode().replace(b'"body":', b'"body":"x","body":')
        )


class FakeProcess:
    def __init__(self, returncode: int = 0, timeout: bool = False) -> None:
        self.returncode = returncode
        self.timeout = timeout
        self.wait_timeout: float | None = None

    def wait(self, timeout: float) -> int:
        self.wait_timeout = timeout
        if self.timeout:
            raise subprocess.TimeoutExpired("private path worker", timeout)
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
        "extra",
        "duplicate",
        "bool_pid",
        "negative_pid",
        "duplicate_pid",
        "blocker",
        "stop",
        "startup",
    ],
)
def test_fixed_owned_child_protocol_and_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    process = FakeProcess(returncode=1 if failure == "status" else 0, timeout=failure == "timeout")
    owned = cast(OwnedProcessObservation, object())
    finished: list[tuple[object, object, bool]] = []
    deadline = time.monotonic() + 5

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
            str(Path(observation.__file__).with_name("local_path_worker.py")),
        )
        assert cwd == Path("/")
        assert dict(environment) == {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "C",
            "LC_ALL": "C",
        }
        assert not isinstance(stdout, int) and not isinstance(stderr, int)
        request = MacPathObservationRequest.decode(os.read(stdin, 64 * 1024 * 1024))
        assert request.deadline == deadline
        payload = MacPathObservationResult(
            request_sha256=request.request_sha256,
            covered_pids=(101,),
            blockers=("WORKTREE_PROCESS_ACTIVE",),
        ).encode()
        if failure in {"sha", "extra", "bool_pid", "negative_pid", "duplicate_pid", "blocker"}:
            altered = json.loads(payload)
            if failure == "sha":
                altered["request_sha256"] = "0" * 64
            elif failure == "extra":
                altered["private"] = "secret fixture"
            elif failure == "blocker":
                altered["blockers"] = ["UNKNOWN"]
            else:
                altered["covered_pids"] = {
                    "bool_pid": [True],
                    "negative_pid": [-1],
                    "duplicate_pid": [101, 101],
                }[failure]
            payload = json.dumps(altered).encode()
        elif failure == "oversize":
            payload = b"x" * (256 * 1024 + 1)
        elif failure == "truncated":
            payload = payload[:-1]
        elif failure == "duplicate":
            payload = payload.replace(b'"covered_pids":', b'"covered_pids":[],"covered_pids":')
        stdout.write(payload)
        if failure == "stderr":
            stderr.write(b"private secret fixture")
        if failure == "startup":
            monkeypatch.setattr(
                "ai_software_engineer.manager.local_path_observation.time.monotonic",
                lambda: deadline + 1,
            )
        return OwnedQuerySpawn(cast(subprocess.Popen[bytes], process), owned)

    def finish(
        actual: subprocess.Popen[bytes],
        original: OwnedProcessObservation,
        *,
        output_drained: bool,
    ) -> None:
        finished.append((actual, original, output_drained))
        if failure == "stop":
            raise RuntimeError("private secret stop fixture")

    monkeypatch.setattr(observation, "spawn_owned_query", spawn)
    monkeypatch.setattr(observation, "finish_owned_process", finish)
    if failure == "none":
        assert observe_mac_paths_in_process(
            fixture_body(tmp_path), tmp_path, frozenset(), frozenset(), deadline
        ) == ({101}, {"WORKTREE_PROCESS_ACTIVE"})
    else:
        with pytest.raises(LocalPathObservationError) as caught:
            observe_mac_paths_in_process(
                fixture_body(tmp_path), tmp_path, frozenset(), frozenset(), deadline
            )
        assert "private" not in str(caught.value) and "secret" not in str(caught.value)
    assert finished == [(process, owned, True)]
    if failure != "startup":
        assert process.wait_timeout is not None and 0 < process.wait_timeout <= 5


def test_expired_parent_deadline_never_spawns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("expired request must not spawn")

    monkeypatch.setattr(observation, "spawn_owned_query", forbidden)
    with pytest.raises(LocalPathObservationError):
        observe_mac_paths_in_process(
            fixture_body(tmp_path), tmp_path, frozenset(), frozenset(), 0.0
        )


def test_deadline_checked_between_every_lsof_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = iter((1.0, 1.0, 1.0, 3.0))
    monkeypatch.setattr(
        "ai_software_engineer.manager.local_path_observation.time.monotonic", lambda: next(clock)
    )
    with pytest.raises(LocalPathObservationError):
        inspect_mac_paths(b"p101\0f4\0tREG\0nrelative\0", tmp_path, frozenset(), frozenset(), 2.0)


@pytest.mark.parametrize("failure", ["truncated", "oversize", "digest", "expired", "missing"])
def test_worker_emits_no_partial_result_for_invalid_request(tmp_path: Path, failure: str) -> None:
    from ai_software_engineer.manager.local_path_worker import _execute

    request = MacPathObservationRequest.create(
        fixture_body(tmp_path), tmp_path, frozenset(), frozenset(), time.monotonic() + 5
    )
    raw = request.encode()
    if failure == "truncated":
        raw = raw[:-1]
    elif failure == "oversize":
        raw = b"x" * (64 * 1024 * 1024 + 1)
    elif failure == "digest":
        raw = raw.replace(request.request_sha256.encode(), b"0" * 64)
    elif failure == "expired":
        raw = MacPathObservationRequest.create(
            fixture_body(tmp_path), tmp_path, frozenset(), frozenset(), 0.0
        ).encode()
    else:
        payload = json.loads(raw)
        payload.pop("protocol")
        raw = json.dumps(payload).encode()
    output = io.BytesIO()
    assert _execute(io.BytesIO(raw), output) == 1
    assert output.getvalue() == b""


def test_real_small_owned_worker_preserves_alias_and_releases_ownership(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    registry = HostOwnedProcessRegistry()
    with registry.operation_scope("operation_small_path_worker"):
        covered, blockers = observe_mac_paths_in_process(
            fixture_body(alias), root, frozenset(), frozenset(), time.monotonic() + 5
        )
    assert covered == {101}
    assert blockers == {"WORKTREE_PROCESS_ACTIVE"}
    assert not registry.snapshot()
    registry.require_stopped()


def test_worker_direct_dependency_loader_never_executes_sitecustomize_or_pth(
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
    with registry.operation_scope("operation_no_site_path_worker"):
        assert observe_mac_paths_in_process(
            fixture_body(tmp_path), tmp_path, frozenset(), frozenset(), time.monotonic() + 5
        ) == ({101}, {"WORKTREE_PROCESS_ACTIVE"})
    assert not marker.exists()
    assert not registry.snapshot()
    registry.require_stopped()
