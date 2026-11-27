"""The trusted git binary skips the macOS xcrun shim, never the caller's PATH."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_software_engineer.git import executable as module


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    module.trusted_git_executable.cache_clear()
    yield
    module.trusted_git_executable.cache_clear()


def _darwin(monkeypatch: pytest.MonkeyPatch, default: str | None) -> None:
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.shutil, "which", lambda name, path: default)


def test_shim_resolves_once_to_the_real_binary_with_a_fixed_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "Developer/usr/bin/git"
    real.parent.mkdir(parents=True)
    real.write_text("")
    real.chmod(0o755)
    _darwin(monkeypatch, "/usr/bin/git")
    monkeypatch.setenv("DEVELOPER_DIR", "/attacker")
    monkeypatch.setenv("PATH", "/attacker/bin")
    calls: list[tuple[object, object]] = []

    def run(argv: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        calls.append((argv, kwargs.get("env")))
        return SimpleNamespace(returncode=0, stdout=f"{real}\n")

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.trusted_git_executable() == str(real)
    assert module.trusted_git_executable() == str(real)
    assert calls == [
        (("/usr/bin/xcrun", "--find", "git"), {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})
    ]


@pytest.mark.parametrize(
    "stdout,returncode,executable",
    [
        ("/usr/bin/git\n", 0, True),
        ("relative/git\n", 0, True),
        ("{real}\n", 1, True),
        ("{real}\n", 0, False),
    ],
)
def test_unusable_resolution_keeps_the_default_path_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
    returncode: int,
    executable: bool,
) -> None:
    real = tmp_path / "git"
    real.write_text("")
    real.chmod(0o755 if executable else 0o644)
    _darwin(monkeypatch, "/usr/bin/git")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=returncode, stdout=stdout.format(real=real)),
    )
    assert module.trusted_git_executable() == "/usr/bin/git"


def test_other_platforms_non_shim_paths_and_xcrun_failures_keep_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.shutil, "which", lambda name, path: "/usr/bin/git")
    monkeypatch.setattr(module.sys, "platform", "linux")
    assert module.trusted_git_executable() == "/usr/bin/git"
    module.trusted_git_executable.cache_clear()
    _darwin(monkeypatch, "/opt/homebrew/bin/git")
    assert module.trusted_git_executable() == "/opt/homebrew/bin/git"
    module.trusted_git_executable.cache_clear()
    _darwin(monkeypatch, "/usr/bin/git")

    def broken(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired("xcrun", 30)

    monkeypatch.setattr(module.subprocess, "run", broken)
    assert module.trusted_git_executable() == "/usr/bin/git"
