"""Actual discovery commands preserve owned uncertainty independently of image facts."""

from __future__ import annotations

import os
import platform
import socket
import sys
import tempfile
from pathlib import Path

import pytest

from ai_software_engineer import owned_sessions
from ai_software_engineer.domain.native_verification import NativeVerificationCapabilityDetail
from ai_software_engineer.manager import python_verification_discovery as discovery
from ai_software_engineer.owned_processes import HostOwnedProcessRegistry, OwnedProcessesUncertain
from ai_software_engineer.owned_sessions import OwnedProcessIdentity, OwnedSessionUnknown


class _FailOneImageCapture:
    """Fail only the first owner capture for command two, with no fake Popen."""

    def __init__(self, actual: owned_sessions._SessionInspector) -> None:
        self.actual = actual
        self.failed = False

    def boot_identity(self) -> str:
        return self.actual.boot_identity()

    def identity(self, pid: int) -> OwnedProcessIdentity | None:
        if not self.failed:
            self.failed = True
            raise OwnedSessionUnknown("fixture initial OS ownership inspection unavailable")
        return self.actual.identity(pid)

    def members(self, sid: int) -> tuple[OwnedProcessIdentity, ...]:
        return self.actual.members(sid)


def _discovery_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[HostOwnedProcessRegistry, Path, socket.socket, list[str]]:
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "if 'image' in sys.argv:\n"
        "    print('sha256:' + 'a' * 64)\n"
        "else:\n"
        "    print('fixture-daemon')\n"
    )
    docker.chmod(0o700)
    codex = tmp_path / "codex"
    codex.write_text("fixture codex binary\n")
    monkeypatch.setattr(discovery, "_binary", lambda name: codex if name == "codex" else docker)
    monkeypatch.setattr(discovery, "dependency_fingerprint", lambda root: "b" * 64)
    # Platform capability is irrelevant to this Linux/Darwin registry execution;
    # preserve the actual OS inspector before only bypassing the discovery gate.
    operating_system = platform.system()
    factory = owned_sessions._inspector
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    if operating_system != "Darwin":
        monkeypatch.setattr(owned_sessions, "_inspector", lambda: owned_sessions._LinuxInspector())
        factory = owned_sessions._inspector
    captures: list[str] = []

    def inspector() -> owned_sessions._SessionInspector:
        captures.append("capture")
        actual = factory()
        return _FailOneImageCapture(actual) if len(captures) == 2 else actual

    monkeypatch.setattr(owned_sessions, "_inspector", inspector)
    path = Path(tempfile.gettempdir()) / ("ase-owned-discovery-" + str(os.getpid()) + ".sock")
    path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    return HostOwnedProcessRegistry(), path, server, captures


def test_image_ownership_unknown_is_not_a_missing_image_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, path, server, captures = _discovery_fixture(tmp_path, monkeypatch)
    try:
        with (
            registry.operation_scope("operation_fixture_discovery"),
            pytest.raises(discovery.PythonMysqlDiscoveryError) as caught,
        ):
            discovery.discover_python_mysql_host_prerequisites(
                codex_executable="codex", docker_socket=str(path)
            )
        assert caught.value.code is NativeVerificationCapabilityDetail.PROCESS_STATE_UNCONFIRMED
        assert str(caught.value) == "VERIFICATION_PROCESS_STATE_UNCONFIRMED"
        assert len(captures) == 2
    finally:
        server.close()
        path.unlink(missing_ok=True)


def test_two_later_successful_discoveries_do_not_clear_an_earlier_owned_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, path, server, captures = _discovery_fixture(tmp_path, monkeypatch)
    try:
        with (
            registry.operation_scope("operation_fixture_discovery"),
            pytest.raises(discovery.PythonMysqlDiscoveryError) as caught,
        ):
            discovery.discover_python_mysql_host_prerequisites(
                codex_executable="codex", docker_socket=str(path)
            )
        assert caught.value.code is NativeVerificationCapabilityDetail.PROCESS_STATE_UNCONFIRMED
        (unknown,) = registry.snapshot()
        assert unknown.kind == "tool" and unknown.state == "uncertain"
        # finish_owned_process cleaned and reaped the actual fixture leader;
        # this independent current absence does not fabricate its lost birth/SID proof.
        with pytest.raises(ProcessLookupError):
            os.kill(unknown.process_id, 0)
        for attempt in (1, 2):
            with registry.operation_scope(f"operation_fixture_recheck_{attempt}"):
                result = discovery.discover_python_mysql_host_prerequisites(
                    codex_executable="codex", docker_socket=str(path)
                )
            assert result.mysql_image_id == "sha256:" + "a" * 64
            assert registry.snapshot() == (unknown,)
        assert len(captures) == 6
        assert registry.shutdown_failed and not registry.await_stopped(0)
        with pytest.raises(OwnedProcessesUncertain):
            registry.require_stopped()
    finally:
        server.close()
        path.unlink(missing_ok=True)
