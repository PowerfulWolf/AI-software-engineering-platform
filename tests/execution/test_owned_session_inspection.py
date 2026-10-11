"""Bounded OS facts and exact recorded births; no real provider or database."""

import os
import platform
from pathlib import Path

import pytest

from ai_software_engineer.owned_sessions import (
    OwnedProcessIdentity,
    OwnedSessionStopProof,
    OwnedSessionUnknown,
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


@pytest.mark.skipif(platform.system() != "Darwin", reason="requires Darwin libproc")
def test_real_darwin_saturated_process_buffer_is_not_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ai_software_engineer.owned_sessions._MAX_PROCESSES", 1)
    with pytest.raises(OwnedSessionUnknown, match="enumeration exceeded bound"):
        _DarwinInspector().members(os.getsid(os.getpid()))
