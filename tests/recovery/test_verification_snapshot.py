"""Legacy checkpoint projections cannot override actual terminal runtime evidence."""

from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
)
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.verification_snapshot import (
    CandidateRuntimeSnapshot,
    validate_candidate_snapshot,
)
from tests.e2e.test_delivery_checkpoint import _checkpoint, _full_fields
from tests.project_manager.test_dispatch import RecordingDispatchStore, _facts, _service


@pytest.mark.parametrize(
    "mutation",
    [None, "legacy_base", "foreign_revision", "task", "revision", "chain", "candidate", "future"],
)
def test_candidate_snapshot_accepts_stale_projection_not_changed_facts(
    tmp_path: Path, mutation: str | None
) -> None:
    request, workforce = _facts(tmp_path)
    dispatch = _service(RecordingDispatchStore(), workforce, request).commit_dispatch(request)
    task = dispatch.task.model_copy(update={"status": TaskStatus.FAILED, "attempts": 1})
    states = (
        TaskStatus.NEW,
        TaskStatus.PLANNING,
        TaskStatus.IMPLEMENTING,
        TaskStatus.QA,
        TaskStatus.FAILED,
    )
    events = tuple(
        StateEvent(
            event_id=f"evt_snapshot_{index}",
            task_id=task.id,
            from_status=before,
            to_status=after,
            actor=AgentRole.ORCHESTRATOR,
            reason="candidate_ready" if after is TaskStatus.QA else "fixture",
            artifact_ids=("art_impl_snapshot",) if after is TaskStatus.QA else (),
            source_revision="b" * 40 if index >= 2 else task.base_ref,
            occurred_at=task.updated_at,
        )
        for index, (before, after) in enumerate(pairwise(states))
    )
    fields = {
        **_full_fields(),
        "project_id": dispatch.project_id,
        "dispatch_commit_id": dispatch.id,
        "dispatch_commit_sha256": dispatch.dispatch_sha256,
        "task_id": task.id,
        "task_revision": 0,
        "task_status": TaskStatus.NEW,
        "candidate_revision": None,
        "stage": DeliveryStage.BLOCKED,
        "failure_code": DeliveryFailureCode.INVARIANT_VIOLATION,
        "failure_summary": "legacy stale projection",
        "next_action": DeliveryNextAction.REQUEST_HUMAN,
    }
    checkpoint = _checkpoint(Path(task.repository), **fields)
    snapshot = CandidateRuntimeSnapshot(task, 4, dispatch, events)
    if mutation in ("legacy_base", "foreign_revision"):
        snapshot = replace(
            snapshot,
            events=(
                *events[:-1],
                events[-1].model_copy(
                    update={
                        "source_revision": task.base_ref if mutation == "legacy_base" else "f" * 40
                    }
                ),
            ),
        )
    elif mutation == "task":
        snapshot = replace(snapshot, task=task.model_copy(update={"title": "changed"}))
    elif mutation == "revision":
        snapshot = replace(snapshot, revision=3)
    elif mutation == "chain":
        snapshot = replace(
            snapshot,
            events=(events[0].model_copy(update={"from_status": TaskStatus.QA}), *events[1:]),
        )
    elif mutation == "candidate":
        snapshot = replace(
            snapshot,
            events=(
                *events[:2],
                events[2].model_copy(update={"reason": "not_candidate"}),
                events[3],
            ),
        )
    elif mutation == "future":
        checkpoint = checkpoint.model_copy(update={"task_revision": 5})
    if mutation in (None, "legacy_base"):
        validate_candidate_snapshot(checkpoint, snapshot)
    else:
        with pytest.raises(RecoveryRejected):
            validate_candidate_snapshot(checkpoint, snapshot)
