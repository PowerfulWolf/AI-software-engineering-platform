"""An inherited Plan reference is accepted only with original immutable facts."""

import hashlib
from pathlib import Path

import pytest

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.context.models import ContextBudget, ContextBundle, ContextSection
from ai_software_engineer.context.ports import ContextStoreError
from ai_software_engineer.context.store import _manifest_digest
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.recovery.context_capacity import (
    LEGACY_CAPACITY_REASON,
    LegacyContextCapacitySourceReader,
    _require_plan_queue_reference,
)
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, RoleQueueAdmission
from ai_software_engineer.work_queue.models import QueueArtifactReceipt
from tests.domain.factories import NOW, make_plan_artifact, make_state_event, make_task


@pytest.mark.parametrize(
    "fault",
    (
        "none",
        "plan_source",
        "context_task",
        "context_role",
        "context_attempt",
        "context_source",
        "context_time",
        "missing_context",
        "terminal_reference",
        "ambiguous_event",
    ),
)
def test_only_the_original_plan_and_its_actual_context_can_be_inherited(
    tmp_path: Path, fault: str
) -> None:
    from datetime import timedelta

    task = make_task().model_copy(update={"status": TaskStatus.BLOCKED, "attempts": 2})
    context = ContextBundle(
        context_id="ctx_" + "0" * 64,
        task_id=task.id,
        role=AgentRole.ORCHESTRATOR,
        attempt=1,
        source_revision=task.base_ref,
        sections=(
            ContextSection(
                name="original.plan",
                uri="plan://original",
                content="original plan context",
                sha256=hashlib.sha256(b"original plan context").hexdigest(),
                tokens=3,
                priority=1,
            ),
        ),
        budget=ContextBudget(max_input_tokens=100, reserved_output_tokens=0, used_input_tokens=3),
        built_at=NOW + timedelta(seconds=1),
    )
    changes: dict[str, dict[str, object]] = {
        "context_task": {"task_id": "task_another_original"},
        "context_role": {"role": AgentRole.CODER},
        "context_attempt": {"attempt": 2},
        "context_source": {"source_revision": "d" * 40},
        "context_time": {"built_at": NOW + timedelta(seconds=3)},
    }
    context = context.model_copy(update=changes.get(fault, {}))
    context = context.model_copy(update={"context_id": "ctx_" + _manifest_digest(context)})
    FileContextStore(tmp_path / "contexts").put(context)
    plan = make_plan_artifact().model_copy(
        update={
            "task_id": task.id,
            "context_manifest_id": context.context_id,
            "source_revision": "d" * 40 if fault == "plan_source" else task.base_ref,
        }
    )
    plan = seal_artifact(plan, validated_at=NOW)
    FileArtifactStore(tmp_path / "artifacts").put(plan)
    accepted = make_state_event().model_copy(
        update={
            "task_id": task.id,
            "from_status": TaskStatus.PLANNING,
            "to_status": TaskStatus.IMPLEMENTING,
            "artifact_ids": (plan.artifact_id,),
            "reason": "plan_validated",
            "source_revision": task.base_ref,
            "occurred_at": NOW + timedelta(seconds=2),
        }
    )
    terminal = accepted.model_copy(
        update={
            "event_id": "evt_capacity_terminal",
            "from_status": TaskStatus.IMPLEMENTING,
            "to_status": TaskStatus.BLOCKED,
            "attempt": 2,
            "reason": LEGACY_CAPACITY_REASON,
            "artifact_ids": ("art_unrelated_plan",)
            if fault == "terminal_reference"
            else (plan.artifact_id,),
            "occurred_at": NOW + timedelta(seconds=3),
        }
    )
    events = (accepted, terminal)
    if fault == "ambiguous_event":
        events = (accepted, accepted, terminal)
    elif fault == "missing_context":
        (tmp_path / "contexts" / f"{context.context_id}.json").unlink()
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    if fault == "none":
        # Recovery seeding preserves the approved Plan's original created_at.
        assert plan.created_at < context.built_at < accepted.occurred_at
        assert (
            LegacyContextCapacitySourceReader._require_original_plan(tmp_path, task, events) == plan
        )
    else:
        with pytest.raises((ValueError, ContextStoreError)):
            LegacyContextCapacitySourceReader._require_original_plan(tmp_path, task, events)
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}


@pytest.mark.parametrize("anchor", ("legacy", "accepted"))
@pytest.mark.parametrize(
    "fault", ("none", "missing", "sha", "task", "run", "context", "source", "duplicate")
)
def test_original_plan_requires_exact_queue_acceptance(anchor: str, fault: str) -> None:
    plan = seal_artifact(
        make_plan_artifact().model_copy(update={"context_manifest_id": "ctx_" + "a" * 64}),
        validated_at=NOW,
    )
    receipt = QueueArtifactReceipt(artifact_id=plan.artifact_id, sha256=plan.integrity.sha256)
    admission = RoleQueueAdmission(
        task_id=plan.task_id,
        repository_id="repository_capacity_plan",
        allocation_sha256="a" * 64,
        legacy_artifacts=(receipt,) if anchor == "legacy" else (),
    )
    published = AcceptedRoleArtifact(
        task_id=plan.task_id,
        work_item_id="work_original_plan",
        lease_id="lease_original_plan",
        dispatch_sequence=1,
        checkpoint_sequence=0,
        run_id=plan.producer.run_id,
        context_manifest_id=plan.context_manifest_id,
        source_revision=plan.source_revision,
        receipt=receipt,
    )
    publications = (published,) if anchor == "accepted" else ()
    if fault == "missing":
        admission = admission.model_copy(update={"legacy_artifacts": ()})
        publications = ()
    elif fault == "sha":
        changed = receipt.model_copy(update={"sha256": "f" * 64})
        if anchor == "legacy":
            admission = admission.model_copy(update={"legacy_artifacts": (changed,)})
        else:
            publications = (published.model_copy(update={"receipt": changed}),)
    elif fault == "task":
        admission = admission.model_copy(update={"task_id": "task_another_original"})
    elif fault in {"run", "context", "source", "duplicate"}:
        if anchor == "legacy":
            # A conflicting accepted publication cannot be ignored merely because
            # the original receipt also exists in a legacy admission.
            publications = (published,)
        fields = {
            "run": {"run_id": "run_unrelated_plan"},
            "context": {"context_manifest_id": "ctx_" + "f" * 64},
            "source": {"source_revision": "f" * 40},
            "duplicate": {},
        }
        changed = published.model_copy(update=fields[fault])
        publications = (changed, changed) if fault == "duplicate" else (changed,)
    if fault == "none":
        _require_plan_queue_reference(plan, admission, publications)
    else:
        with pytest.raises(ValueError, match="exact queue acceptance"):
            _require_plan_queue_reference(plan, admission, publications)
