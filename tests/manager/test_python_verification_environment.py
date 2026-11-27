"""The MySQL verification sandbox PATH bypasses macOS xcrun shims, nothing more."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_software_engineer.manager import python_verification as module


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    module.macos_developer_tool_directory.cache_clear()


def _xcrun(monkeypatch: pytest.MonkeyPatch, *, stdout: str, returncode: int = 0) -> list[object]:
    calls: list[object] = []

    def run(argv: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        calls.append((argv, kwargs.get("env")))
        return SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.subprocess, "run", run)
    return calls


def test_macos_prepends_the_real_git_directory_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = tmp_path / "Developer/usr/bin"
    tools.mkdir(parents=True)
    (tools / "git").write_text("")
    calls = _xcrun(monkeypatch, stdout=f"{tools / 'git'}\n")
    environment = module.python_mysql_sandbox_environment()
    assert environment["PATH"] == f"{tools}:/usr/bin:/bin"
    assert set(environment) == {"PATH", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE"}
    scratch = tmp_path / "scratch"
    with_cache = module.python_mysql_sandbox_environment(scratch)
    assert with_cache["xcrun_db"] == str(scratch / "xcrun_db")
    assert {key: value for key, value in with_cache.items() if key != "xcrun_db"} == environment
    assert calls == [(("/usr/bin/xcrun", "--find", "git"), calls[0][1])], "resolved once"
    assert calls[0][1] == {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}


@pytest.mark.parametrize(
    "stdout,returncode",
    [
        ("/usr/bin/git\n", 0),  # still the shim itself
        ("relative/git\n", 0),
        ("/missing/Developer/usr/bin/git\n", 0),
        ("", 1),
    ],
)
def test_unusable_resolution_keeps_the_fixed_path(
    monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int
) -> None:
    _xcrun(monkeypatch, stdout=stdout, returncode=returncode)
    environment = module.python_mysql_sandbox_environment(Path("/scratch"))
    assert environment["PATH"] == "/usr/bin:/bin"
    assert "xcrun_db" not in environment, "no cache override without a real developer directory"


def test_xcrun_failure_and_other_platforms_keep_the_fixed_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.sys, "platform", "linux")
    assert module.python_mysql_sandbox_environment()["PATH"] == "/usr/bin:/bin"
    module.macos_developer_tool_directory.cache_clear()
    monkeypatch.setattr(module.sys, "platform", "darwin")

    def broken(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired("xcrun", 20)

    monkeypatch.setattr(module.subprocess, "run", broken)
    assert module.python_mysql_sandbox_environment()["PATH"] == "/usr/bin:/bin"
