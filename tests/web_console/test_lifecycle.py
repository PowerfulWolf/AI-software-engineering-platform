"""Configuration apply lifecycle stays typed, idempotent and secret-free."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.web_console.lifecycle import (
    ApplyConfigurationRequest,
    ConfigurationApplyError,
    ConfigurationApplyState,
    ConfigurationApplyStatus,
    FileConfigurationLifecycle,
    PsSupervisorProcessProbe,
)


class _SupervisorProcessProbe:
    def __init__(self, matches: bool = True) -> None:
        self._matches = matches

    def matches(self, pid: int, script: Path) -> bool:
        return self._matches


def _lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FileConfigurationLifecycle:
    tmp_path.mkdir(exist_ok=True)
    script = tmp_path / "ase-console-service.sh"
    script.write_text("#!/bin/sh\n", encoding="ascii")
    (tmp_path / "ase-console-supervisor.pid").write_text(f"4242\n{script}\n", encoding="utf-8")
    monkeypatch.setattr("ai_software_engineer.web_console.lifecycle.os.kill", lambda *_: None)
    return FileConfigurationLifecycle(tmp_path, supervisor_process_probe=_SupervisorProcessProbe())


def test_apply_request_is_empty_and_state_uses_fixed_safe_summaries() -> None:
    with pytest.raises(ValidationError):
        ApplyConfigurationRequest.model_validate({"command": "restart"})
    with pytest.raises(ValidationError, match="safe fixed text"):
        ConfigurationApplyState(
            request_id="configuration_apply_" + "a" * 32,
            status=ConfigurationApplyStatus.FAILED,
            safe_summary="raw provider exception",
        )


def test_file_lifecycle_records_one_idempotent_pending_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _lifecycle(tmp_path, monkeypatch)

    first = lifecycle.request("a" * 64)
    replay = lifecycle.request("a" * 64)
    concurrent = lifecycle.request("b" * 64)

    assert first == replay == concurrent
    assert first.status is ConfigurationApplyStatus.PENDING
    assert (tmp_path / "configuration-apply.request").read_text() == first.request_id + "\n"
    persisted = json.loads((tmp_path / "configuration-apply.json").read_text())
    assert persisted == first.to_wire()
    assert "a" * 64 not in json.dumps(persisted)
    assert lifecycle.current() == first


def test_file_lifecycle_republishes_missing_marker_for_pending_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _lifecycle(tmp_path, monkeypatch)
    pending = lifecycle.request("a" * 64)
    request = tmp_path / "configuration-apply.request"
    request.unlink()

    replay = lifecycle.request("a" * 64)

    assert replay == pending
    assert request.read_text(encoding="ascii") == pending.request_id + "\n"


def test_file_lifecycle_rejects_missing_supervisor_without_writing(
    tmp_path: Path,
) -> None:
    lifecycle = FileConfigurationLifecycle(tmp_path)

    with pytest.raises(ConfigurationApplyError, match="unavailable"):
        lifecycle.request("a" * 64)

    assert not (tmp_path / "configuration-apply.request").exists()
    assert not (tmp_path / "configuration-apply.json").exists()


def test_file_lifecycle_rejects_unverified_supervisor_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "ase-console-supervisor.pid").write_text("4242\n", encoding="ascii")
    monkeypatch.setattr("ai_software_engineer.web_console.lifecycle.os.kill", lambda *_: None)
    lifecycle = FileConfigurationLifecycle(tmp_path)

    with pytest.raises(ConfigurationApplyError, match="unavailable"):
        lifecycle.request("a" * 64)

    assert not (tmp_path / "configuration-apply.request").exists()


def test_file_lifecycle_rejects_live_foreign_supervisor_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.mkdir(exist_ok=True)
    script = tmp_path / "ase-console-service.sh"
    script.write_text("#!/bin/sh\n", encoding="ascii")
    (tmp_path / "ase-console-supervisor.pid").write_text(f"4242\n{script}\n", encoding="utf-8")
    monkeypatch.setattr("ai_software_engineer.web_console.lifecycle.os.kill", lambda *_: None)
    lifecycle = FileConfigurationLifecycle(
        tmp_path, supervisor_process_probe=_SupervisorProcessProbe(False)
    )

    with pytest.raises(ConfigurationApplyError, match="unavailable"):
        lifecycle.request("a" * 64)

    assert not (tmp_path / "configuration-apply.request").exists()


def test_ps_supervisor_probe_requires_exact_script_and_supervise_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "ase-console-service.sh"

    def completed(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 0, stdout=f"/bin/sh {script} supervise\n", stderr=""
        )

    monkeypatch.setattr("ai_software_engineer.web_console.lifecycle.subprocess.run", completed)
    assert PsSupervisorProcessProbe().matches(4242, script)

    def foreign(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 0, stdout=f"/bin/sh {script} status\n", stderr=""
        )

    monkeypatch.setattr("ai_software_engineer.web_console.lifecycle.subprocess.run", foreign)
    assert not PsSupervisorProcessProbe().matches(4242, script)
