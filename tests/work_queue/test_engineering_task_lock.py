"""Engineering process-lock observation is separate from Worker execution authority."""

import fcntl
import os
from hashlib import sha256
from pathlib import Path

import pytest

from ai_software_engineer.work_queue.ports import QueueConflict
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


def test_task_scope_check_requires_exact_live_scope_and_grants_no_worker_authority(
    tmp_path: Path,
) -> None:
    guard = WorkerExecutionGuard()
    with pytest.raises(QueueConflict):
        guard.check_task_scope("task_exact")
    with guard.task_scope(tmp_path / "locks", "task_exact"):
        guard.check_task_scope("task_exact")
        assert guard.lease is None
        with pytest.raises(QueueConflict, match="active Worker"):
            guard.check()
        with pytest.raises(QueueConflict, match="exact held Task"):
            guard.check_task_scope("task_foreign")
        with (
            pytest.raises(QueueConflict, match="nested"),
            guard.task_scope(tmp_path / "locks", "task_exact"),
        ):
            raise AssertionError("nested ownership must be rejected")
    assert guard.inherited_fds == ()
    with pytest.raises(QueueConflict):
        guard.check_task_scope("task_exact")


def test_closed_task_scope_fd_cannot_be_used_as_engineering_lock(tmp_path: Path) -> None:
    guard = WorkerExecutionGuard()
    with guard.task_scope(tmp_path / "locks", "task_exact"):
        os.close(guard.inherited_fds[0])
        with pytest.raises(QueueConflict, match="no longer live"):
            guard.check_task_scope("task_exact")


def test_unlocked_task_scope_fd_is_not_a_held_engineering_lock(tmp_path: Path) -> None:
    guard = WorkerExecutionGuard()
    with guard.task_scope(tmp_path / "locks", "task_exact"):
        fcntl.flock(guard.inherited_fds[0], fcntl.LOCK_UN)
        with pytest.raises(QueueConflict, match="no longer held"):
            guard.check_task_scope("task_exact")


@pytest.mark.parametrize("mutation", ["replace", "symlink", "permissions", "descriptor"])
def test_changed_task_lock_identity_is_rejected(tmp_path: Path, mutation: str) -> None:
    guard = WorkerExecutionGuard()
    root = tmp_path / "locks"
    with guard.task_scope(root, "task_exact"):
        path = root / (sha256(b"task_exact").hexdigest() + ".lock")
        if mutation in {"replace", "symlink"}:
            path.rename(root / "original-held.lock")
            if mutation == "replace":
                path.touch(mode=0o600)
            else:
                path.symlink_to(root / "original-held.lock")
        elif mutation == "permissions":
            path.chmod(0o644)
        else:
            guard.inherited_fds = ()
        with pytest.raises(QueueConflict):
            guard.check_task_scope("task_exact")
