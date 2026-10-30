"""Candidate Git reads use the trusted owned-process launch gate."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_software_engineer.agents import candidate_source
from ai_software_engineer.git import WorkspacePolicyError
from ai_software_engineer.owned_processes import HostOwnedProcessRegistry, OwnedProcessesUncertain


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "fixture")
    return root


def test_short_candidate_git_reads_repeat_with_a_verified_owner_scope(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    registry = HostOwnedProcessRegistry()

    with registry.operation_scope("operation_candidate_source_repeat"):
        for _ in range(20):
            assert candidate_source._git(root, "rev-parse", "--verify", "HEAD")
            assert candidate_source._git(root, "status", "--porcelain") == b""
        registry.require_stopped()

    assert registry.snapshot() == ()


def test_candidate_git_captures_owner_before_a_short_command_can_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The former direct-Popen route loses the leader before owner capture."""
    root = _repository(tmp_path)
    registry = HostOwnedProcessRegistry()
    direct_popen_calls = 0

    def eager_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        nonlocal direct_popen_calls
        direct_popen_calls += 1
        process: subprocess.Popen[bytes] = subprocess.Popen(*args, **kwargs)  # type: ignore[call-overload]
        process.wait(timeout=3)
        return process

    monkeypatch.setattr(
        candidate_source,
        "subprocess",
        SimpleNamespace(
            DEVNULL=subprocess.DEVNULL,
            PIPE=subprocess.PIPE,
            SubprocessError=subprocess.SubprocessError,
            Popen=eager_popen,
        ),
    )
    with registry.operation_scope("operation_candidate_source_short_exit"):
        assert candidate_source._git(root, "rev-parse", "--verify", "HEAD")
        registry.require_stopped()

    assert direct_popen_calls == 0
    assert registry.snapshot() == ()


def test_candidate_git_failure_is_typed_and_does_not_leave_owned_processes(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    registry = HostOwnedProcessRegistry()

    with registry.operation_scope("operation_candidate_source_failure"):
        with pytest.raises(WorkspacePolicyError, match="Git objects"):
            candidate_source._git(root, "rev-parse", "--verify", "does-not-exist")
        # A nonzero Git exit is still a fully observed stop; it must not leave a
        # registry entry that would block a later controlled restart.
        assert registry.snapshot() == ()


def test_candidate_git_timeout_stops_the_owned_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repository(tmp_path)
    registry = HostOwnedProcessRegistry()
    ticks = iter((0.0, 31.0))
    monkeypatch.setattr(
        candidate_source, "time", SimpleNamespace(monotonic=lambda: next(ticks))
    )

    with registry.operation_scope("operation_candidate_source_timeout"):
        with pytest.raises(WorkspacePolicyError, match="timed out"):
            candidate_source._git(root, "rev-parse", "--verify", "HEAD")
        registry.require_stopped()

    assert registry.snapshot() == ()


def test_candidate_git_rejects_a_failed_owned_spawn_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repository(tmp_path)
    registry = HostOwnedProcessRegistry()

    def refused(*_args: object, **_kwargs: object) -> object:
        raise OwnedProcessesUncertain("fixture ownership refused")

    monkeypatch.setattr(candidate_source, "spawn_owned_query", refused)
    with registry.operation_scope("operation_candidate_source_spawn_refused"):
        with pytest.raises(WorkspacePolicyError, match="could not start"):
            candidate_source._git(root, "rev-parse", "--verify", "HEAD")
        assert registry.snapshot() == ()
