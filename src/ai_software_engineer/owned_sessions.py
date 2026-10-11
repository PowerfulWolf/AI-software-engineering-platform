"""Private actual-spawn capability for bounded POSIX session stop observation.

This is not a process-selection tool. Only trusted runners pass their actual Popen;
the proof covers its original SID, never an unobserved descendant that used setsid.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import platform
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self

from pydantic import AwareDatetime, Field, StrictInt, model_validator

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import StageSha256

_POPEN_CLASS = subprocess.Popen
_MAX_PROCESSES = 16_384
_MAX_OBSERVATIONS = 1_000_000
_SCAN_SECONDS = 1.0


class OwnedSessionUnknown(RuntimeError):
    """A complete, identity-bound stop of this original session is unknown."""


class OwnedProcessIdentity(DomainModel):
    process_id: Annotated[StrictInt, Field(gt=0)]
    group_id: Annotated[StrictInt, Field(gt=0)]
    session_id: Annotated[StrictInt, Field(gt=0)]
    birth_identity: Annotated[NonEmptyStr, Field(max_length=128)]


class OwnedSessionStopProof(DomainModel):
    schema_version: Literal["v1"] = "v1"
    proof_scope: Literal["owned_session_empty"] = "owned_session_empty"
    boot_identity: Annotated[NonEmptyStr, Field(max_length=128)]
    leader: OwnedProcessIdentity
    observed_processes: Annotated[
        tuple[OwnedProcessIdentity, ...], Field(max_length=_MAX_PROCESSES)
    ]
    observation_count: Annotated[StrictInt, Field(ge=2, le=_MAX_OBSERVATIONS)]
    observations_sha256: StageSha256
    observed_at: AwareDatetime
    proof_sha256: StageSha256

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if not self.leader.process_id == self.leader.group_id == self.leader.session_id:
            raise ValueError("owned proof must bind its isolated spawned leader")
        identities = tuple((p.process_id, p.birth_identity) for p in self.observed_processes)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("owned observations require sorted unique process birth identities")
        if self.leader not in self.observed_processes or any(
            p.session_id != self.leader.session_id for p in self.observed_processes
        ):
            raise ValueError("owned proof may contain only the exact original session")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "proof_sha256": "0" * 64})
        return value.model_copy(update={"proof_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return _digest(self.model_dump(mode="json", exclude={"proof_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.proof_sha256 != self.recompute_sha256():
            raise ValueError("owned session stop proof digest mismatch")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class _SessionInspector(Protocol):
    def boot_identity(self) -> str: ...

    def identity(self, pid: int) -> OwnedProcessIdentity | None: ...

    def members(self, sid: int) -> tuple[OwnedProcessIdentity, ...]: ...


class _LinuxInspector:
    def boot_identity(self) -> str:
        value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if len(value) != 36:
            raise OwnedSessionUnknown("OS boot identity is unavailable")
        return "linux:" + value

    def identity(self, pid: int) -> OwnedProcessIdentity | None:
        try:
            value = Path(f"/proc/{pid}/stat").read_bytes()
        except FileNotFoundError:
            return None
        if len(value) > 8192:
            raise OwnedSessionUnknown("OS process identity exceeds inspection bound")
        # comm is an arbitrary parenthesized name; its last closing bracket owns
        # the delimiter. starttime is kernel ticks since boot, not wall-clock ps.
        fields = value[value.rfind(b")") + 2 :].split()
        if len(fields) < 20:
            raise OwnedSessionUnknown("OS process identity is incomplete")
        return OwnedProcessIdentity(
            process_id=pid,
            group_id=int(fields[2]),
            session_id=int(fields[3]),
            birth_identity="linux-ticks:" + fields[19].decode("ascii"),
        )

    def members(self, sid: int) -> tuple[OwnedProcessIdentity, ...]:
        deadline = time.monotonic() + _SCAN_SECONDS
        result: list[OwnedProcessIdentity] = []
        count = 0
        with os.scandir("/proc") as entries:
            for entry in entries:
                if not entry.name.isdecimal():
                    continue
                count += 1
                if count > _MAX_PROCESSES or time.monotonic() >= deadline:
                    raise OwnedSessionUnknown("complete OS process enumeration exceeded bound")
                pid = int(entry.name)
                try:
                    member_sid = os.getsid(pid)
                except ProcessLookupError:
                    continue
                if member_sid != sid:
                    # Kernel/system processes can have PGID/SID zero; they are
                    # outside this owned positive SID and not signal targets.
                    continue
                identity = self.identity(pid)
                if identity is not None and identity.session_id == sid:
                    result.append(identity)
        return tuple(sorted(result, key=lambda p: p.process_id))


class _BsdInfo(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("exit_status", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        ("ppid", ctypes.c_uint32),
        ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32),
        ("ruid", ctypes.c_uint32),
        ("rgid", ctypes.c_uint32),
        ("svuid", ctypes.c_uint32),
        ("svgid", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        ("nfiles", ctypes.c_uint32),
        ("pgid", ctypes.c_uint32),
        ("jobc", ctypes.c_uint32),
        ("tdev", ctypes.c_uint32),
        ("tpgid", ctypes.c_uint32),
        ("nice", ctypes.c_int32),
        ("start_sec", ctypes.c_uint64),
        ("start_usec", ctypes.c_uint64),
    ]


class _Timeval(ctypes.Structure):
    _fields_ = [("seconds", ctypes.c_long), ("microseconds", ctypes.c_int32)]


class _DarwinInspector:
    def __init__(self) -> None:
        self._libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        self._libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        self._libproc.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._libproc.proc_listallpids.restype = ctypes.c_int
        self._libproc.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self._libproc.proc_pidinfo.restype = ctypes.c_int
        self._libc.sysctlbyname.argtypes = [
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        self._libc.sysctlbyname.restype = ctypes.c_int

    def boot_identity(self) -> str:
        value = _Timeval()
        size = ctypes.c_size_t(ctypes.sizeof(value))
        if self._libc.sysctlbyname(
            b"kern.boottime",
            ctypes.byref(value),
            ctypes.byref(size),
            None,
            0,
        ):
            raise OwnedSessionUnknown("OS boot identity is unavailable")
        if size.value != ctypes.sizeof(value) or value.seconds <= 0:
            raise OwnedSessionUnknown("OS boot identity is incomplete")
        return f"darwin:{value.seconds}:{value.microseconds}"

    def identity(self, pid: int) -> OwnedProcessIdentity | None:
        try:
            sid = os.getsid(pid)
        except ProcessLookupError:
            return None
        value = _BsdInfo()
        ctypes.set_errno(0)
        count = self._libproc.proc_pidinfo(pid, 3, 0, ctypes.byref(value), ctypes.sizeof(value))
        if count != ctypes.sizeof(value):
            if ctypes.get_errno() == errno.ESRCH:
                return None
            raise OwnedSessionUnknown("OS process birth identity is unavailable")
        if value.pid != pid or not value.start_sec or value.start_usec >= 1_000_000:
            raise OwnedSessionUnknown("OS process birth identity is incomplete")
        # SID lookup and BSD birth record are separate syscalls. Reject a changed
        # session rather than bind two observations from different identities.
        try:
            if os.getsid(pid) != sid:
                raise OwnedSessionUnknown("OS process session changed during inspection")
        except ProcessLookupError:
            return None
        return OwnedProcessIdentity(
            process_id=pid,
            group_id=value.pgid,
            session_id=sid,
            birth_identity=f"darwin-time:{value.start_sec}:{value.start_usec}",
        )

    def members(self, sid: int) -> tuple[OwnedProcessIdentity, ...]:
        deadline = time.monotonic() + _SCAN_SECONDS
        pids = (ctypes.c_int * (_MAX_PROCESSES + 1))()
        count = self._libproc.proc_listallpids(pids, ctypes.sizeof(pids))
        if count <= 0 or count > _MAX_PROCESSES:
            raise OwnedSessionUnknown("complete OS process enumeration exceeded bound")
        seen = tuple(pids[:count])
        if len(set(seen)) != len(seen) or any(pid < 0 for pid in seen):
            raise OwnedSessionUnknown("complete OS process enumeration is malformed")
        result: list[OwnedProcessIdentity] = []
        for pid in seen:
            if pid == 0:  # Darwin's kernel_task cannot belong to the owned positive SID.
                continue
            if time.monotonic() >= deadline:
                raise OwnedSessionUnknown("complete OS process enumeration exceeded bound")
            try:
                member_sid = os.getsid(pid)
            except ProcessLookupError:
                continue
            if member_sid == sid:
                identity = self.identity(pid)
                if identity is not None:
                    result.append(identity)
        return tuple(sorted(result, key=lambda p: p.process_id))


def _inspector() -> _SessionInspector:
    operating_system = platform.system()
    if operating_system == "Darwin":
        return _DarwinInspector()
    if operating_system == "Linux":
        return _LinuxInspector()
    raise OwnedSessionUnknown("complete owned-session inspection is unsupported")


def require_recorded_session_empty(proof: OwnedSessionStopProof) -> None:
    """Read-only current-fact recheck of a new proof; grants no signal capability."""
    proof.validate_integrity()
    inspector = _inspector()
    if inspector.boot_identity() != proof.boot_identity:
        raise OwnedSessionUnknown("recorded owned-session boot identity is no longer current")
    for _ in range(2):
        deadline = time.monotonic() + _SCAN_SECONDS
        if inspector.identity(proof.leader.process_id) is not None:
            raise OwnedSessionUnknown("recorded owned-session leader identity is now occupied")
        for observed in proof.observed_processes:
            if time.monotonic() >= deadline:
                raise OwnedSessionUnknown("recorded owned-process recheck exceeded bound")
            current = inspector.identity(observed.process_id)
            if current is not None and current.birth_identity == observed.birth_identity:
                raise OwnedSessionUnknown("an observed owned process birth remains alive")
        if inspector.members(proof.leader.session_id):
            raise OwnedSessionUnknown("recorded owned session is no longer empty")


class OwnedSessionController:
    """One trusted Popen capability, never a supplied PID or process selector."""

    def __init__(self, process: subprocess.Popen[str] | subprocess.Popen[bytes]) -> None:
        if (
            not isinstance(process, _POPEN_CLASS)
            or getattr(process, "_child_created", False) is not True
        ):
            raise AttributeError("owned session requires the actual successfully spawned Popen")
        self._process = process
        self._lock = threading.RLock()
        self._inspector = _inspector()
        self._boot = self._inspector.boot_identity()
        leader = self._inspector.identity(process.pid)
        if leader is None or not leader.process_id == leader.group_id == leader.session_id:
            raise OwnedSessionUnknown("spawned leader does not own an isolated session")
        self._leader = leader
        self._observed: dict[tuple[int, str], OwnedProcessIdentity] = {
            (leader.process_id, leader.birth_identity): leader,
        }
        self._count = 0
        self._digest = hashlib.sha256()
        self._observe()

    def _require_owner_identity(self) -> None:
        if self._inspector.boot_identity() != self._boot:
            raise OwnedSessionUnknown("owned-session boot identity changed")
        leader = self._inspector.identity(self._leader.process_id)
        if leader is not None and leader != self._leader:
            raise OwnedSessionUnknown("owned-session leader birth identity changed")

    def _observe(self) -> tuple[OwnedProcessIdentity, ...]:
        if self._count >= _MAX_OBSERVATIONS:
            raise OwnedSessionUnknown("owned-session observation bound exceeded")
        self._require_owner_identity()
        known_before = self._known_members()
        members = self._inspector.members(self._leader.session_id)
        # Reused SID/PID between the first owner query and enumeration is not
        # authority to signal a new unrelated session.
        self._require_owner_identity()
        known_after = self._known_members()
        member_births = {(p.process_id, p.birth_identity) for p in members}
        if any(
            status == "same_owned_birth" and (pid, birth) not in member_births
            for pid, birth, status in known_after
        ):
            raise OwnedSessionUnknown("complete session observation omitted a known living birth")
        if (
            len(members) > _MAX_PROCESSES
            or any(p.session_id != self._leader.session_id for p in members)
            or len({p.process_id for p in members}) != len(members)
        ):
            raise OwnedSessionUnknown("complete owned-session observation is inconsistent")
        for member in members:
            key = member.process_id, member.birth_identity
            previous = self._observed.get(key)
            # A peer may change PGID inside the original SID. Retain its current
            # identity; every prior group remains in the observation digest.
            if previous is not None and previous.session_id != member.session_id:
                raise OwnedSessionUnknown("owned process session identity changed")
            self._observed[key] = member
        if len(self._observed) > _MAX_PROCESSES:
            raise OwnedSessionUnknown("owned-session identity history exceeded bound")
        self._count += 1
        self._digest.update(
            json.dumps(
                {
                    "members": [p.to_wire() for p in members],
                    "known_before": known_before,
                    "known_after": known_after,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        return members

    def _known_members(self) -> list[tuple[int, str, str]]:
        """An observed owned peer cannot vanish merely by leaving the original SID."""
        deadline = time.monotonic() + _SCAN_SECONDS
        result: list[tuple[int, str, str]] = []
        for key, previous in sorted(self._observed.items()):
            if time.monotonic() >= deadline:
                raise OwnedSessionUnknown("known owned-process recheck exceeded bound")
            current = self._inspector.identity(previous.process_id)
            if current is not None and current.birth_identity == previous.birth_identity:
                if current.session_id != self._leader.session_id:
                    raise OwnedSessionUnknown("an observed owned process left its original session")
                result.append((*key, "same_owned_birth"))
            else:
                # A recycled child PID is not its original birth. Never signal
                # it under a stale identity. SID reuse has a stricter leader gate.
                result.append((*key, "original_birth_absent"))
        return result

    def observe_session(self) -> None:
        """Trusted active-owner polling records peers without signalling them."""
        with self._lock:
            self._observe()

    def _signal(self, members: tuple[OwnedProcessIdentity, ...], sent: signal.Signals) -> None:
        for member in members:
            self._require_owner_identity()
            self._known_members()
            current = self._inspector.identity(member.process_id)
            if current is None:
                continue
            if current != member:
                raise OwnedSessionUnknown("owned process identity changed before signal")
            try:
                # Individual verified members avoids signalling an unchecked
                # reused PGID. Repeated full scans include every observed group.
                os.kill(member.process_id, sent)
            except ProcessLookupError:
                continue

    def stop(self, *, timeout_seconds: float = 1.0) -> OwnedSessionStopProof:
        """Finite TERM/KILL with complete identity-bound session rechecks."""
        with self._lock:
            return self._stop(timeout_seconds=timeout_seconds)

    def _stop(self, *, timeout_seconds: float) -> OwnedSessionStopProof:
        if not 0 < timeout_seconds < float("inf"):
            raise ValueError("owned-session stop requires a finite positive timeout")
        for sent in (signal.SIGTERM, signal.SIGKILL):
            deadline = time.monotonic() + timeout_seconds
            while True:
                self._process.poll()  # reap leader separately from SID observation
                first = self._observe()
                second = self._observe()
                if not first and not second and self._process.returncode is not None:
                    return self._proof()
                # The second complete enumeration is fresh; each identity is
                # checked again immediately before its signal.
                self._signal(second, sent)
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        raise OwnedSessionUnknown("owned session has not become completely empty")

    def require_empty(self) -> OwnedSessionStopProof:
        """Read-only independent recheck; does not signal or infer stop from EOF."""
        with self._lock:
            return self._require_empty()

    def _require_empty(self) -> OwnedSessionStopProof:
        if self._process.poll() is None or self._observe() or self._observe():
            raise OwnedSessionUnknown("owned session has not become completely empty")
        return self._proof()

    def _proof(self) -> OwnedSessionStopProof:
        return OwnedSessionStopProof.create(
            boot_identity=self._boot,
            leader=self._leader,
            observed_processes=tuple(self._observed[k] for k in sorted(self._observed)),
            observation_count=self._count,
            observations_sha256=self._digest.hexdigest(),
            observed_at=datetime.now(UTC),
        )
