"""Worker ownership covers subprocess lifetime and platform candidate finalization."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from ai_software_engineer.agents import CodexCliAgentAdapter
from ai_software_engineer.agents.codex_cli import CodexCliError, SubprocessCodexCommandRunner
from ai_software_engineer.execution import SubprocessCommandExecutor
from ai_software_engineer.work_queue.ports import DeliveryQueuePending, QueueLeaseLost
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.agents.test_codex_cli import _DirtySuccessRunner, _git, _repository
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request
from tests.execution.test_executor import _permissions


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
