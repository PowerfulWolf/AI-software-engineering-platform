"""Stopped baseline waits bind effective queue source without rewriting Task history."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

import pytest

from ai_software_engineer.domain import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.multi_directory import cancellation
from ai_software_engineer.multi_directory.cancellation import (
    FileRequirementCancellationStore,
    RequirementCancellationRejected,
    RequirementCancellationService,
    RequirementCancellationTarget,
)
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.recovery.baseline_source import (
    RecoveryBaselineEpoch,
    validate_pre_candidate_sources,
)
from ai_software_engineer.work_queue import baseline
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep
from ai_software_engineer.work_queue.models import QueuedWorkItem
from tests.manager.test_requirement_deletion import _delivery
from tests.work_queue.test_baseline_pause_mysql import PausedFixture
from tests.work_queue.test_baseline_pause_mysql import paused as paused
from tests.work_queue.test_mysql_queue import dispatcher

pytestmark = pytest.mark.mysql


def _service(
    paused: PausedFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    RequirementCancellationService, JointCheckpoint, tuple[RequirementCancellationTarget, ...]
]:
    platform, checkpoint, _, _, _ = _delivery(tmp_path / "requirement", monkeypatch)
    checkpoint = checkpoint.model_copy(update={"stage": JointStage.DELIVERING})
    task = paused.repository.get(paused.binding.task_id)
    source = paused.queue.step(paused.work_item_id).boundary.source_revision
    assert source == paused.binding.execution_source_revision
    assert source != task.base_ref
    assert paused.repository.list_events(task.id)[-1].source_revision == task.base_ref

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> FrozenDatetime:
            return cls.fromtimestamp((paused.now + timedelta(seconds=10)).timestamp(), tz)

    monkeypatch.setattr(cancellation, "datetime", FrozenDatetime)
    service = RequirementCancellationService(
        paused.repository,
        paused.queue,
        FileRequirementCancellationStore(
            platform.project.requirements_root / checkpoint.delivery_id
        ),
    )
    targets = (
        RequirementCancellationTarget(task=task, repository_id=paused.binding.scope.repository_id),
    )
    return service, checkpoint, targets


@pytest.mark.parametrize("interrupt", [False, True])
@pytest.mark.parametrize("environment", [False, True], ids=("baseline_pause", "environment_wait"))
def test_real_baseline_wait_cancels_and_partial_replays_current_execution_source(
    paused: PausedFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt: bool,
    environment: bool,
) -> None:
    if environment:
        authority = paused.authorization()
        assert paused.queue.release_baseline_pause(paused.binding, authority)
        tick = dispatcher(paused.queue, "worker_cancel_environment").tick(
            now=paused.now + timedelta(seconds=6), work_item_id=authority.work_item_id
        )
        assert tick.claim is not None and tick.lease_owner_token is not None
        item = tick.claim.work_item
        disposition = decide_delivery_disposition(
            DeliveryFailureFacts(
                task_id=item.task_id,
                work_item_id=item.id,
                role=item.role,
                classification="ENVIRONMENT_UNAVAILABLE",
                source_revision=paused.queue.step(item.id).boundary.source_revision,
                task_intent_sha256=task_intent_sha256(paused.repository.get(item.task_id)),
                checkpoint_sequence=item.checkpoint_sequence,
                budget_available=True,
            )
        )
        assert disposition.facts.execution_baseline_sha256 is None
        paused.queue.wait(
            item.id,
            lease_id=tick.claim.lease.id,
            owner_token=tick.lease_owner_token,
            status=WorkItemStatus.WAITING_DEPENDENCY,
            reason=disposition.reason,
            disposition=disposition,
            now=paused.now + timedelta(seconds=7),
        )
    service, checkpoint, targets = _service(paused, tmp_path, monkeypatch)
    historical_events = paused.repository.list_events(targets[0].task.id)
    original_close = paused.queue.close_cancelled_task
    if interrupt:

        def fail_close(*args: object, **kwargs: object) -> tuple[QueuedWorkItem, ...]:
            raise RuntimeError("after cancellation event")

        monkeypatch.setattr(paused.queue, "close_cancelled_task", fail_close)
        with pytest.raises(RuntimeError, match="after cancellation event"):
            service.cancel(checkpoint, targets, action="CLOSE_REQUIREMENT")
        before = service.records.path.read_bytes()
        monkeypatch.setattr(paused.queue, "close_cancelled_task", original_close)
    receipt = service.cancel(checkpoint, targets, action="CLOSE_REQUIREMENT")
    if interrupt:
        assert service.records.path.read_bytes() == before
    service.cancel(checkpoint, targets, action="CLOSE_REQUIREMENT")
    assert receipt.tasks[0].source_revision == targets[0].task.base_ref
    waiting = next(item for item in receipt.tasks[0].queue_items if item.id == paused.work_item_id)
    assert waiting.wait_disposition is not None
    assert (
        waiting.wait_disposition.facts.source_revision == paused.binding.execution_source_revision
    )
    assert paused.repository.get(targets[0].task.id).status is TaskStatus.BLOCKED
    events = paused.repository.list_events(targets[0].task.id)
    assert len(events) == 3
    assert events[:-1] == historical_events
    assert events[-1].source_revision == paused.binding.execution_source_revision
    reservation = paused.plan.facts.continuation
    assert reservation is not None
    validate_pre_candidate_sources(
        paused.repository.get(targets[0].task.id),
        events,
        (RecoveryBaselineEpoch(paused.binding, reservation.next_execution_attempt),),
    )
    assert all(
        item.status is WorkItemStatus.CLOSED
        for item in paused.queue.items_for_task(targets[0].task.id)
    )


@pytest.mark.parametrize("timing", ["before_receipt", "after_receipt", "mutation_fence"])
def test_real_baseline_wait_rejects_effective_source_drift_before_any_event(
    paused: PausedFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timing: str
) -> None:
    service, checkpoint, targets = _service(paused, tmp_path, monkeypatch)
    original_step = paused.queue.step

    def drifted(identity: str) -> QueuedRoleStep:
        step = original_step(identity)
        return step.model_copy(
            update={"boundary": replace(step.boundary, source_revision="f" * 40)}
        )

    if timing == "before_receipt":
        monkeypatch.setattr(paused.queue, "step", drifted)
    elif timing == "after_receipt":
        original_append = paused.repository.append_event

        def crash(event: StateEvent) -> None:
            raise RuntimeError("after receipt")

        monkeypatch.setattr(paused.repository, "append_event", crash)
        with pytest.raises(RuntimeError, match="after receipt"):
            service.cancel(checkpoint, targets, action="CLOSE_REQUIREMENT")
        monkeypatch.setattr(paused.repository, "append_event", original_append)
        monkeypatch.setattr(paused.queue, "step", drifted)
    else:
        original_append = paused.repository.append_event

        def race(event: StateEvent) -> None:
            monkeypatch.setattr(paused.queue, "step", drifted)
            original_append(event)

        monkeypatch.setattr(paused.repository, "append_event", race)
    with pytest.raises(RequirementCancellationRejected, match="工程等待与当前任务事实不一致"):
        service.cancel(checkpoint, targets, action="CLOSE_REQUIREMENT")
    assert paused.repository.get(targets[0].task.id) == targets[0].task
    assert len(paused.repository.list_events(targets[0].task.id)) == 2
    if timing == "before_receipt":
        assert not service.records.path.exists()


def test_baseline_wait_refuses_missing_immutable_step(
    paused: PausedFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.work_queue.ports import QueueNotFound

    service, checkpoint, targets = _service(paused, tmp_path, monkeypatch)

    def missing_step(identity: str) -> QueuedRoleStep:
        raise QueueNotFound("missing immutable step")

    monkeypatch.setattr(paused.queue, "original_step", missing_step)
    with pytest.raises(RequirementCancellationRejected):
        service.cancel(checkpoint, targets, action="CLOSE_REQUIREMENT")
    assert paused.repository.get(targets[0].task.id) == targets[0].task
    assert len(paused.repository.list_events(targets[0].task.id)) == 2
    assert not service.records.path.exists()


def test_missing_overlay_cannot_qualify_original_same_item_source(
    paused: PausedFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if paused.work_item_id != paused.plan.facts.work_item_id:
        pytest.skip("reserved successor has its own durable current-source boundary")
    service, checkpoint, targets = _service(paused, tmp_path, monkeypatch)
    monkeypatch.setattr(baseline, "consumptions", lambda queue, task_id: ())
    with pytest.raises(RequirementCancellationRejected):
        service.cancel(checkpoint, targets, action="CLOSE_REQUIREMENT")
    assert paused.repository.get(targets[0].task.id) == targets[0].task
    assert len(paused.repository.list_events(targets[0].task.id)) == 2
    assert not service.records.path.exists()
