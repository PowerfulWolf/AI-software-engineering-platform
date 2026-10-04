"""Worker ownership covers subprocess lifetime and platform candidate finalization."""

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from ai_software_engineer.agents import CodexCliAgentAdapter
from ai_software_engineer.agents.codex_cli import (
    CodexCliError,
    CodexExecutionUnconfirmed,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.execution import SubprocessCommandExecutor
from ai_software_engineer.work_queue.ports import DeliveryQueuePending, QueueLeaseLost
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.agents.test_codex_cli import _DirtySuccessRunner, _git, _repository
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request
from tests.execution.test_executor import _permissions


@pytest.mark.parametrize("prompt", ["", "验收背景\n" * 100_000])
def test_owned_codex_delivers_large_prompt_after_first_lease_poll(
    tmp_path: Path, prompt: str
) -> None:
    """A slow stdin reader must still receive every byte and EOF after 0.2 seconds."""
    result = SubprocessCodexCommandRunner(Guard()).run(
        (
            sys.executable,
            "-c",
            "import os,stat,sys,time; time.sleep(0.4); "
            "assert stat.S_IMODE(os.fstat(0).st_mode) == 0o600; "
            "assert os.fstat(0).st_nlink == 0; "
            "print(len(sys.stdin.read()))",
        ),
        cwd=tmp_path,
        environment={"PATH": os.defpath, "PYTHONIOENCODING": "utf-8"},
        stdin=prompt,
        timeout_seconds=3,
    )
    assert not result.timed_out
    assert result.returncode == 0
    assert result.stdout.strip() == str(len(prompt))
    assert result.process_stop is not None
    result.process_stop.validate_integrity()
    assert result.process_stop.kind == "completed"
    with pytest.raises(ProcessLookupError):
        os.killpg(result.process_stop.group_id, 0)


def test_owned_codex_timeout_terminates_child_after_prompt_delivery(tmp_path: Path) -> None:
    result = SubprocessCodexCommandRunner(Guard()).run(
        (
            sys.executable,
            "-c",
            "import os,sys,time; sys.stdin.read(); print(os.getpid(),flush=True); time.sleep(30)",
        ),
        cwd=tmp_path,
        environment={},
        stdin="Complete prompt",
        timeout_seconds=0.5,
    )
    assert result.timed_out
    assert result.process_stop is not None
    result.process_stop.validate_integrity()
    assert result.process_stop.kind == "local_execution_limit"
    assert result.process_stop.returncode == result.returncode
    with pytest.raises(ProcessLookupError):
        os.kill(int(result.stdout.strip()), 0)


def test_local_limit_records_actual_graceful_exit_without_claiming_completion(
    tmp_path: Path,
) -> None:
    result = SubprocessCodexCommandRunner(Guard()).run(
        (
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM,lambda *args: exit(0)); "
            "time.sleep(30)",
        ),
        cwd=tmp_path,
        environment={},
        stdin="",
        timeout_seconds=0.5,
    )
    assert result.timed_out
    assert result.returncode == 0
    assert result.process_stop is not None
    assert result.process_stop.kind == "local_execution_limit"
    result.process_stop.validate_integrity()


class Guard:
    inherited_fds: tuple[int, ...] = ()

    def __init__(self, marker: Path | None = None) -> None:
        self.marker = marker

    def check(self) -> None:
        if self.marker is not None and self.marker.exists():
            raise QueueLeaseLost("test lease lost")

    @contextmanager
    def write_scope(self) -> Iterator[None]:
        self.check()
        yield
        self.check()


@pytest.mark.parametrize("code", ["exit(0)", "exit(1)", "import time; time.sleep(30)"])
def test_owned_runner_refuses_every_result_without_group_stop_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    killpg = os.killpg

    def unavailable(group: int, sig: int) -> None:
        if sig == 0:
            raise PermissionError("test cannot observe process group")
        killpg(group, sig)

    monkeypatch.setattr(os, "killpg", unavailable)
    with pytest.raises(CodexExecutionUnconfirmed):
        SubprocessCodexCommandRunner(Guard()).run(
            (sys.executable, "-c", code),
            cwd=tmp_path,
            environment={},
            stdin="",
            timeout_seconds=0.3,
        )


def test_owned_codex_start_failure_keeps_typed_error(tmp_path: Path) -> None:
    with pytest.raises(CodexCliError, match="could not start"):
        SubprocessCodexCommandRunner(Guard()).run(
            (str(tmp_path / "missing-codex"),),
            cwd=tmp_path,
            environment={},
            stdin="",
            timeout_seconds=1,
        )


@pytest.mark.parametrize("codex", [True, False])
def test_lost_owner_terminates_executor_before_returning(tmp_path: Path, codex: bool) -> None:
    marker = tmp_path / "started"
    code = "from pathlib import Path; import time; Path('started').touch(); time.sleep(30)"
    guard = Guard(marker)
    argv = (sys.executable, "-c", code)
    with pytest.raises(QueueLeaseLost):
        if codex:
            SubprocessCodexCommandRunner(guard).run(
                argv,
                cwd=tmp_path,
                environment={},
                stdin="",
                timeout_seconds=5,
            )
        else:
            SubprocessCommandExecutor(
                tmp_path,
                _permissions(),
                execution_guard=guard,
            ).run(argv, timeout_seconds=5)
    assert marker.exists()


def test_lost_owner_retains_dirty_draft_without_committing(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_DirtySuccessRunner(request),
        execution_guard=Guard(root / "src" / "change.py"),
    )
    with pytest.raises(QueueLeaseLost):
        adapter.run(request)
    assert _git(root, "rev-parse", "HEAD") == base
    assert (root / "src" / "change.py").is_file()
    assert _git(root, "status", "--porcelain")


def test_task_lock_excludes_other_workers_but_not_other_tasks(tmp_path: Path) -> None:
    first, second = WorkerExecutionGuard(), WorkerExecutionGuard()
    with first.task_scope(tmp_path, "task_first"):
        with pytest.raises(DeliveryQueuePending), second.task_scope(tmp_path, "task_first"):
            pytest.fail("second worker acquired the Task")
        with second.task_scope(tmp_path, "task_second"):
            assert second.inherited_fds
    with second.task_scope(tmp_path, "task_first"):
        assert second.inherited_fds
