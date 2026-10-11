"""Bounded OS facts and exact recorded births; no real provider or database."""

import ctypes
import errno
import os
import platform
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer.owned_sessions import (
    OwnedProcessIdentity,
    OwnedSessionStopProof,
    OwnedSessionUnknown,
    _BsdInfo,
    _DarwinInspector,
    _LinuxInspector,
    require_recorded_session_empty,
)
from tests.contracts.test_owned_session_stop_schema import _proof


class Inspector:
    def __init__(self, proof: OwnedSessionStopProof, current: OwnedProcessIdentity | None) -> None:
        self.proof, self.current = proof, current

    def boot_identity(self) -> str:
        return self.proof.boot_identity

    def identity(self, pid: int) -> OwnedProcessIdentity | None:
        if self.current is not None and self.current.process_id == pid:
            return self.current
        return None

    def members(self, sid: int) -> tuple[OwnedProcessIdentity, ...]:
        return ()


@pytest.mark.parametrize("same_birth", [False, True])
def test_recorded_peer_pid_reuse_is_separate_from_live_original_birth(
    monkeypatch: pytest.MonkeyPatch,
    same_birth: bool,
) -> None:
    proof = _proof()
    original = proof.observed_processes[1]
    current = original.model_copy(
        update={
            "session_id": 999,
            "birth_identity": original.birth_identity if same_birth else "recycled:birth",
        }
    )
    monkeypatch.setattr(
        "ai_software_engineer.owned_sessions._inspector", lambda: Inspector(proof, current)
    )
    if same_birth:
        with pytest.raises(OwnedSessionUnknown, match="birth remains alive"):
            require_recorded_session_empty(proof)
    else:
        require_recorded_session_empty(proof)


def test_linux_birth_parser_keeps_kernel_ticks_and_arbitrary_comm_delimiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fields = ["S", "1", "202", "101", *(["0"] * 15), "987654321", "0", "0"]
    data = ("202 (fixture ) tricky name) " + " ".join(fields)).encode()
    monkeypatch.setattr(Path, "read_bytes", lambda _: data)
    assert _LinuxInspector().identity(202) == OwnedProcessIdentity(
        process_id=202,
        group_id=202,
        session_id=101,
        birth_identity="linux-ticks:987654321",
    )


@pytest.mark.parametrize("data", [b"missing", b"x" * 8193], ids=["partial", "oversized"])
def test_linux_partial_or_oversized_identity_refuses_inspection(
    monkeypatch: pytest.MonkeyPatch,
    data: bytes,
) -> None:
    monkeypatch.setattr(Path, "read_bytes", lambda _: data)
    with pytest.raises(OwnedSessionUnknown):
        _LinuxInspector().identity(202)


def _short_darwin_birth_query(query_errno: int, short_count: int = 0) -> _DarwinInspector:
    inspector = _DarwinInspector.__new__(_DarwinInspector)

    def short_info(*arguments: object) -> int:
        ctypes.set_errno(query_errno)
        return short_count

    inspector._libproc = cast(ctypes.CDLL, SimpleNamespace(proc_pidinfo=short_info))
    return inspector


@pytest.mark.parametrize("query_errno", [0, errno.ENOENT], ids=["no_errno", "enoent"])
@pytest.mark.parametrize("short_count", [0, ctypes.sizeof(_BsdInfo) - 1], ids=["zero", "partial"])
def test_darwin_short_birth_query_uses_fresh_kernel_absence_after_exit(
    monkeypatch: pytest.MonkeyPatch, query_errno: int, short_count: int
) -> None:
    calls = 0

    def current_sid(pid: int) -> int:
        nonlocal calls
        assert pid == 202
        calls += 1
        if calls == 1:
            return 101
        raise ProcessLookupError(errno.ESRCH, "process exited")

    monkeypatch.setattr(os, "getsid", current_sid)
    assert _short_darwin_birth_query(query_errno, short_count).identity(202) is None
    assert calls == 2


@pytest.mark.parametrize("current_sid", [101, 999], ids=["still_living", "recycled_pid"])
@pytest.mark.parametrize("query_errno", [0, errno.ENOENT, errno.EPERM, errno.EINVAL])
def test_darwin_short_birth_query_cannot_discard_a_current_or_recycled_process(
    monkeypatch: pytest.MonkeyPatch, current_sid: int, query_errno: int
) -> None:
    calls = 0

    def sid(pid: int) -> int:
        nonlocal calls
        calls += 1
        return 101 if calls == 1 else current_sid

    monkeypatch.setattr(os, "getsid", sid)
    with pytest.raises(OwnedSessionUnknown, match="birth identity is unavailable"):
        _short_darwin_birth_query(query_errno).identity(202)


@pytest.mark.parametrize("query_errno", [errno.EPERM, errno.EINVAL])
def test_darwin_failed_birth_and_denied_fresh_sid_are_unknown(
    monkeypatch: pytest.MonkeyPatch, query_errno: int
) -> None:
    calls = 0

    def sid(pid: int) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return 101
        raise OSError(query_errno, "inspection unavailable")

    monkeypatch.setattr(os, "getsid", sid)
    with pytest.raises(OwnedSessionUnknown, match="birth identity is unavailable"):
        _short_darwin_birth_query(errno.ENOENT).identity(202)


def test_darwin_initial_kernel_absence_does_not_query_a_birth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspector = _short_darwin_birth_query(0)

    def absent(pid: int) -> int:
        raise ProcessLookupError(errno.ESRCH, "process absent")

    def unexpected_query(*arguments: object) -> int:
        raise AssertionError("a known absent process has no birth query")

    monkeypatch.setattr(os, "getsid", absent)
    monkeypatch.setattr(inspector._libproc, "proc_pidinfo", unexpected_query)
    assert inspector.identity(202) is None


@pytest.mark.parametrize("last_sid", [101, 999], ids=["stable_session", "changed_session"])
def test_darwin_complete_birth_still_requires_matching_second_sid(
    monkeypatch: pytest.MonkeyPatch, last_sid: int
) -> None:
    inspector = _short_darwin_birth_query(0)
    calls = 0

    def sid(pid: int) -> int:
        nonlocal calls
        calls += 1
        return 101 if calls == 1 else last_sid

    def complete_info(*arguments: object) -> int:
        value = ctypes.cast(cast(ctypes.c_void_p, arguments[3]), ctypes.POINTER(_BsdInfo)).contents
        value.pid, value.pgid, value.start_sec, value.start_usec = 202, 202, 1000, 2
        return ctypes.sizeof(value)

    monkeypatch.setattr(os, "getsid", sid)
    monkeypatch.setattr(inspector._libproc, "proc_pidinfo", complete_info)
    if last_sid == 101:
        assert inspector.identity(202) == OwnedProcessIdentity(
            process_id=202, group_id=202, session_id=101, birth_identity="darwin-time:1000:2"
        )
    else:
        with pytest.raises(OwnedSessionUnknown, match="session changed"):
            inspector.identity(202)
    assert calls == 2


@pytest.mark.skipif(platform.system() != "Darwin", reason="requires Darwin libproc")
def test_real_darwin_exit_between_sid_and_birth_query_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(30)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={},
        start_new_session=True,
    )
    inspector = _DarwinInspector()
    original_info = inspector._libproc.proc_pidinfo
    calls = 0

    def query_after_real_exit(*arguments: object) -> int:
        nonlocal calls
        calls += 1
        process.kill()
        process.wait(timeout=2)
        return cast(int, original_info(*arguments))

    monkeypatch.setattr(inspector._libproc, "proc_pidinfo", query_after_real_exit)
    try:
        assert inspector.identity(process.pid) is None
        assert calls == 1
        with pytest.raises(ProcessLookupError):
            os.getsid(process.pid)
    finally:
        if process.poll() is None:
            with suppress(ProcessLookupError):
                process.kill()
            process.wait(timeout=2)


@pytest.mark.skipif(platform.system() != "Darwin", reason="requires Darwin libproc")
def test_real_darwin_saturated_process_buffer_is_not_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ai_software_engineer.owned_sessions._MAX_PROCESSES", 1)
    with pytest.raises(OwnedSessionUnknown, match="enumeration exceeded bound"):
        _DarwinInspector().members(os.getsid(os.getpid()))
