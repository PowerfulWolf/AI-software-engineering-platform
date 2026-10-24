"""Bounded OS facts and exact recorded births; no real provider or database."""

import ctypes
import errno
import hashlib
import os
import platform
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

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


def _darwin_boot_query(body: bytes, *, status: int = 0) -> _DarwinInspector:
    inspector = _DarwinInspector.__new__(_DarwinInspector)

    def query(*arguments: object) -> int:
        assert arguments[0] == b"kern.bootsessionuuid"
        size = ctypes.cast(cast(ctypes.c_void_p, arguments[2]), ctypes.POINTER(ctypes.c_size_t))
        if status == 0:
            assert size.contents.value >= len(body)
            ctypes.memmove(cast(ctypes.c_void_p, arguments[1]), body, len(body))
            size.contents.value = len(body)
        return status

    inspector._libc = cast(ctypes.CDLL, SimpleNamespace(sysctlbyname=query))
    return inspector


def test_darwin_boot_uses_stable_canonical_session_uuid() -> None:
    session = UUID("ABABCDEF-0000-4000-8000-0123456789AB")
    inspector = _darwin_boot_query((str(session).upper() + "\0").encode("ascii"))
    expected = "darwin-session:" + hashlib.sha256(str(session).encode("ascii")).hexdigest()
    assert inspector.boot_identity() == expected
    assert inspector.boot_identity() == expected


@pytest.mark.parametrize("body", [b"not-a-uuid\0", b"", b"123\0extra", b"\xff\0"])
def test_darwin_boot_rejects_malformed_session_uuid(body: bytes) -> None:
    with pytest.raises(OwnedSessionUnknown):
        _darwin_boot_query(body).boot_identity()


@pytest.mark.parametrize(
    "body",
    [
        b"\xff" + b"0" * 35 + b"\0",
        b"00000000-0000-4000-8000-00000000000\0\0",
        b"00000000-0000-4000-8000-000000000000x",
        b"00000000000040008000000000000000    \0",
    ],
)
def test_darwin_boot_rejects_full_size_invalid_uuid(body: bytes) -> None:
    assert len(body) == 37
    with pytest.raises(OwnedSessionUnknown):
        _darwin_boot_query(body).boot_identity()


def test_darwin_boot_denial_never_falls_back_to_adjustable_time() -> None:
    with pytest.raises(OwnedSessionUnknown):
        _darwin_boot_query(b"", status=-1).boot_identity()


def test_recorded_boot_bridge_checks_before_and_after_full_empty_sweeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = _proof()
    calls: list[str] = []

    class CurrentInspector(Inspector):
        def boot_identity(self) -> str:
            return "darwin-session:" + "a" * 64

        def members(self, sid: int) -> tuple[OwnedProcessIdentity, ...]:
            calls.append("sweep")
            return ()

    class Bridge:
        def require_current(self, original: OwnedSessionStopProof, current: str) -> None:
            assert original == proof
            assert current == "darwin-session:" + "a" * 64
            calls.append("bridge")

    monkeypatch.setattr(
        "ai_software_engineer.owned_sessions._inspector",
        lambda: CurrentInspector(proof, None),
    )
    with pytest.raises(OwnedSessionUnknown, match="boot identity"):
        require_recorded_session_empty(proof)
    require_recorded_session_empty(proof, boot_continuity=Bridge())
    assert calls == ["bridge", "sweep", "sweep", "bridge"]


def test_recorded_session_rejects_boot_change_during_sweeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = _proof()

    class ChangedInspector(Inspector):
        count = 0

        def boot_identity(self) -> str:
            self.count += 1
            return proof.boot_identity if self.count == 1 else "different-boot"

    monkeypatch.setattr(
        "ai_software_engineer.owned_sessions._inspector",
        lambda: ChangedInspector(proof, None),
    )
    with pytest.raises(OwnedSessionUnknown, match="boot identity"):
        require_recorded_session_empty(proof)


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
