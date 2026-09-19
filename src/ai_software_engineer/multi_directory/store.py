"""External append-only journal with process exclusion and optimistic cursors."""

from __future__ import annotations

import fcntl
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import TypeAdapter

from ai_software_engineer.manager.delivery import DeliveryCheckpointStale
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage


class JointJournal:
    def __init__(self, root: Path, *, read_only: bool = False) -> None:
        self.root = root.absolute()
        self._read_only = read_only
        _no_symlinks(self.root)
        if read_only:
            if not self.root.is_dir():
                raise ValueError("joint journal is missing")
        else:
            self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, delivery_id: str) -> Path:
        TypeAdapter(DeliveryId).validate_python(delivery_id)
        if not delivery_id.startswith("delivery_multi_"):
            raise ValueError("not a joint delivery ID")
        result = self.root / delivery_id
        _no_symlinks(result)
        return result

    @contextmanager
    def lock(self, delivery_id: str) -> Iterator[None]:
        if self._read_only:
            raise ValueError("journal is read-only")
        directory = self.directory(delivery_id)
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(directory / "operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("joint delivery is already running; inspect status") from error
            yield
        finally:
            os.close(fd)

    def current(self, delivery_id: str) -> JointCheckpoint | None:
        history = self.history(delivery_id)
        return history[-1] if history else None

    def history(self, delivery_id: str) -> tuple[JointCheckpoint, ...]:
        previous: JointCheckpoint | None = None
        history: list[JointCheckpoint] = []
        for path in sorted(self.directory(delivery_id).glob("*.json")):
            _no_symlinks(path)
            item = JointCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))
            item.validate_integrity()
            if item.delivery_id != delivery_id or path.name != f"{item.sequence:06d}.json":
                raise ValueError("joint journal identity mismatch")
            _validate_successor(previous, item)
            previous = item
            history.append(item)
        return tuple(history)

    def append(self, checkpoint: JointCheckpoint, *, expected: str | None) -> JointCheckpoint:
        if self._read_only:
            raise ValueError("journal is read-only")
        checkpoint.validate_integrity()
        previous = self.current(checkpoint.delivery_id)
        if (previous.checkpoint_sha256 if previous else None) != expected:
            raise DeliveryCheckpointStale("joint checkpoint changed")
        _validate_successor(previous, checkpoint)
        directory = self.directory(checkpoint.delivery_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{checkpoint.sequence:06d}.json"
        fd, temporary = tempfile.mkstemp(prefix=".record-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(checkpoint.model_dump_json(indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError as error:
                raise DeliveryCheckpointStale(
                    "joint checkpoint was concurrently appended"
                ) from error
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return checkpoint


def _no_symlinks(path: Path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("joint journal cannot traverse symlinks")


def _validate_successor(previous: JointCheckpoint | None, item: JointCheckpoint) -> None:
    if previous is None:
        if item.sequence != 1:
            raise ValueError("joint journal has a missing initial record")
        return
    if (
        item.sequence != previous.sequence + 1
        or item.previous_checkpoint_sha256 != previous.checkpoint_sha256
    ):
        raise ValueError("joint journal hash chain is broken")
    for field in (
        "delivery_id",
        "team_id",
        "team_manifest_sha256",
        "project_id",
        "project_manifest_sha256",
        "scope",
        "title",
        "requirement",
        "submitted_at",
    ):
        if getattr(item, field) != getattr(previous, field):
            raise ValueError("joint intake is immutable")
    if previous.approval is not None and (
        item.product_spec != previous.product_spec or item.approval != previous.approval
    ):
        raise ValueError("approved joint product is immutable")
    if item.integration_retry_approval != previous.integration_retry_approval:
        approval = item.integration_retry_approval
        if (
            previous.integration_retry_approval is not None
            or approval is None
            or approval.proposal.checkpoint_sha256 != previous.checkpoint_sha256
            or previous.attempts.get("integration", 0) != 3
            or previous.integration is None
            or not any(check.returncode != 0 for check in previous.integration.checks)
            or previous.stage not in {JointStage.BLOCKED, JointStage.PLANNING}
            or item.children != previous.children
            or item.attempts != previous.attempts
            or item.plan != previous.plan
            or item.integration != previous.integration
            or item.stage != previous.stage
        ):
            raise ValueError("integration retry requires an exact immutable approval")
    if previous.design is not None and item.design != previous.design:
        raise ValueError("committed joint design and plan are immutable")
    if previous.planning_upgrade is not None and item.planning_upgrade != previous.planning_upgrade:
        raise ValueError("human planning upgrade is immutable")
    if (
        previous.planning_decision is not None
        and item.planning_decision != previous.planning_decision
        and (
            previous.planning_upgrade is not None
            or item.planning_upgrade is None
            or previous.stage is not JointStage.PLANNING
            or previous.plan is not None
            or item.planning_decision is None
            or item.planning_decision.facts != previous.planning_decision.facts
            or item.planning_decision.mode.value != "COMPLEX"
        )
    ):
        raise ValueError("planning decision cannot be downgraded or replaced")
    if previous.integration_retry_approval is not None and item.attempts.get(
        "integration", 0
    ) < previous.attempts.get("integration", 0):
        raise ValueError("approved integration attempts cannot be reset")
    if (
        previous.single_repository_acceptance is not None
        and item.single_repository_acceptance != previous.single_repository_acceptance
    ):
        raise ValueError("single-repository acceptance is immutable")
    if previous.plan is not None and item.plan != previous.plan:
        explicit_integration_replan = (
            previous.stage is JointStage.BLOCKED
            and previous.integration is not None
            and item.stage is JointStage.PLANNING
            and item.plan is None
            and item.integration == previous.integration
        )
        if not explicit_integration_replan:
            raise ValueError("committed joint design and plan are immutable")
    if previous.stage == "DONE":
        raise ValueError("completed joint delivery is immutable")
