"""Native directory selection stays local, canonical and non-textual."""

import os
import signal
import sys
from contextlib import suppress
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from ai_software_engineer.owned_processes import HostOwnedProcessRegistry, OwnedProcessesUncertain
from ai_software_engineer.web_console.directories import (
    DirectorySelectionError,
    NativeDirectoryChooser,
    _validated_directories,
)


def test_selected_directories_are_canonical_unique_absolute_paths(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    assert _validated_directories([str(first), str(first), str(second)]) == (
        str(first.resolve()),
        str(second.resolve()),
    )


def test_directory_selection_rejects_relative_missing_and_symlink_paths(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    for value in ("relative", str(tmp_path / "missing"), str(alias)):
        with pytest.raises(DirectorySelectionError, match="invalid directory"):
            _validated_directories([value])


def test_macos_cancel_is_not_confused_with_chooser_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ai_software_engineer.web_console.directories.sys.platform", "darwin")
    monkeypatch.setattr(
        "ai_software_engineer.web_console.directories.shutil.which",
        lambda _name: "/usr/bin/osascript",
    )

    monkeypatch.setattr(
        "ai_software_engineer.web_console.directories.run_owned_subprocess",
        lambda *_args, **_kwargs: CompletedProcess((), 1, "", "User canceled. (-128)"),
    )
    assert NativeDirectoryChooser().choose() == ()

    monkeypatch.setattr(
        "ai_software_engineer.web_console.directories.run_owned_subprocess",
        lambda *_args, **_kwargs: CompletedProcess((), 1, "", "syntax error"),
    )
    with pytest.raises(DirectorySelectionError, match="chooser failed"):
        NativeDirectoryChooser().choose()


def _native_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str) -> Path:
    executable = tmp_path / "trusted-chooser-fixture"
    executable.write_text(f"#!{sys.executable}\n{source}\n")
    executable.chmod(0o700)
    monkeypatch.setattr(
        "ai_software_engineer.web_console.directories.shutil.which", lambda _: str(executable)
    )
    return executable


def test_real_chooser_success_is_group_owned_and_does_not_inherit_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = tmp_path / "facts"
    source = (
        "import json,os,pathlib; "
        f"pathlib.Path({str(facts)!r}).write_text(json.dumps([os.getpid(),os.getpgrp(),"
        "os.getenv('ASE_FIXTURE_SECRET'),os.getenv('DISPLAY')])); "
        f"print({str(tmp_path)!r})"
    )
    _native_fixture(tmp_path, monkeypatch, source)
    registry = HostOwnedProcessRegistry()
    with registry.operation_scope("http_write_chooser"):
        assert NativeDirectoryChooser(
            environment={"ASE_FIXTURE_SECRET": "private fixture", "DISPLAY": ":fixture"}
        ).choose() == (str(tmp_path.resolve()),)
    import json

    process_id, group_id, secret, display = json.loads(facts.read_text())
    assert process_id == group_id
    assert secret is None and display == ":fixture"
    registry.require_stopped()


def test_real_chooser_timeout_stops_verified_group_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = tmp_path / "facts"
    _native_fixture(
        tmp_path,
        monkeypatch,
        f"import os,pathlib,time; pathlib.Path({str(facts)!r}).write_text(str(os.getpid())); "
        "time.sleep(20)",
    )
    registry = HostOwnedProcessRegistry()
    with registry.operation_scope("http_write_chooser"), pytest.raises(DirectorySelectionError):
        NativeDirectoryChooser(timeout_seconds=1, environment={}).choose()
    group_id = int(facts.read_text())
    with pytest.raises(ProcessLookupError):
        os.killpg(group_id, 0)
    registry.require_stopped()


def test_real_chooser_uncertain_pipe_cannot_allow_service_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "escaped.pid"
    _native_fixture(
        tmp_path,
        monkeypatch,
        "import pathlib,subprocess,sys; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'], "
        "start_new_session=True); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))",
    )
    registry = HostOwnedProcessRegistry()
    try:
        with (
            registry.operation_scope("http_write_chooser"),
            pytest.raises(DirectorySelectionError, match="停止状态无法确认"),
        ):
            NativeDirectoryChooser(timeout_seconds=1, environment={}).choose()
        assert registry.snapshot()[0].state == "uncertain"
        with pytest.raises(OwnedProcessesUncertain):
            registry.require_stopped()
    finally:
        if pid_file.exists():
            with suppress(ProcessLookupError):
                os.kill(int(pid_file.read_text()), signal.SIGKILL)


@pytest.mark.parametrize("timeout", [0, 121, True])
def test_invalid_chooser_timeout_is_rejected(timeout: int) -> None:
    with pytest.raises(ValueError, match="timeout"):
        NativeDirectoryChooser(timeout_seconds=timeout)
