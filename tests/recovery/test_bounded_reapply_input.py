"""A bounded Coder Context still contains one whole approved patch per run."""

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_software_engineer.artifacts import seal_artifact
from ai_software_engineer.context import FileContextBuilder
from ai_software_engineer.domain import (
    AgentRole,
    StateEvent,
    TaskStatus,
)
from ai_software_engineer.domain.delivery_resolution import RejectedCoderOutputEvidence
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.recovery.bounded_input import (
    accepted_reapply_source_index,
    complete_reapply_source_refs,
    scheduled_reapply_context_sources,
    validate_scheduled_reapply_context,
)
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryPlan, RecoveryRejected
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact
from ai_software_engineer.work_queue.models import QueueArtifactReceipt
from tests.domain.factories import NOW, make_coder_progress_artifact, make_task
from tests.recovery.test_authorization import make_plan
from tests.recovery.test_inherited_reapply_inputs import inherited_input


def _plan(root: Path) -> RecoveryPlan:
    root.mkdir()
    old = make_plan(root)
    capture = replace(
        old.capture.to_capture(),
        patch=b"diff --git a/src/now.py b/src/now.py\n+NOW = True\n",
    )
    return RecoveryPlan.create(
        **{
            **old.to_wire(),
            "input_mode": "coder_reapply",
            "capture": CapturedChanges.from_capture(capture),
            "inherited_reapply_inputs": (
                inherited_input("d", body="old patch A\n"),
                inherited_input("e", body="old patch B\n"),
            ),
        }
    )


def test_complete_inventory_keeps_each_approved_source_and_digest(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "project")
    refs = complete_reapply_source_refs(plan)
    assert [ref.source_id for ref in refs] == [
        "recovery.inherited_patch." + "d" * 64,
        "recovery.inherited_patch." + "e" * 64,
        "recovery.patch",
    ]
    assert [ref.sha256 for ref in refs] == [
        hashlib.sha256(b"old patch A\n").hexdigest(),
        hashlib.sha256(b"old patch B\n").hexdigest(),
        hashlib.sha256(plan.capture.patch.encode()).hexdigest(),
    ]
    assert [ref.bytes for ref in refs] == [12, 12, len(plan.capture.patch.encode())]


@pytest.mark.parametrize("selected", [0, 1, 2])
def test_one_complete_source_is_required_and_all_others_absent(
    tmp_path: Path, selected: int
) -> None:
    plan = _plan(tmp_path / "project")
    task = make_task().model_copy(update={"repository": str(tmp_path / "project")})
    decision_sha = "f" * 64
    sources = scheduled_reapply_context_sources(plan, decision_sha, selected)
    builder = FileContextBuilder(tmp_path / "project", plan.permissions, sources=sources)
    context = builder.build(task, AgentRole.CODER, attempt=selected + 1)
    validate_scheduled_reapply_context(plan, decision_sha, selected, context)
    patches = tuple(
        section for section in context.sections if section.name.startswith("source:recovery.")
        and (section.name.endswith("patch") or "inherited_patch" in section.name)
    )
    refs = complete_reapply_source_refs(plan)
    assert len(patches) == 1
    assert patches[0].name == "source:" + refs[selected].source_id
    assert patches[0].sha256 == refs[selected].sha256
    assert not patches[0].truncated
    for role in (AgentRole.QA, AgentRole.REVIEWER):
        assert not any(
            section.name == "source:recovery.input_schedule"
            or section.name.startswith("source:recovery.inherited_patch")
            or section.name == "source:recovery.patch"
            for section in builder.build(task, role, attempt=1).sections
        )


def test_missing_or_changed_selected_source_rejects(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "project")
    task = make_task().model_copy(update={"repository": str(tmp_path / "project")})
    decision_sha = "f" * 64
    sources = scheduled_reapply_context_sources(plan, decision_sha, 1)
    context = FileContextBuilder(
        tmp_path / "project", plan.permissions, sources=sources
    ).build(task, AgentRole.CODER, attempt=2)
    selected_name = "source:" + complete_reapply_source_refs(plan)[1].source_id
    missing = context.model_copy(
        update={"sections": tuple(s for s in context.sections if s.name != selected_name)}
    )
    with pytest.raises(RecoveryRejected):
        validate_scheduled_reapply_context(plan, decision_sha, 1, missing)
    mutated = context.model_copy(
        update={
            "sections": tuple(
                s.model_copy(update={"content": "changed"}) if s.name == selected_name else s
                for s in context.sections
            )
        }
    )
    with pytest.raises(RecoveryRejected):
        validate_scheduled_reapply_context(plan, decision_sha, 1, mutated)
    with pytest.raises(RecoveryRejected):
        validate_scheduled_reapply_context(plan, "a" * 64, 1, context)
    with pytest.raises(RecoveryRejected):
        validate_scheduled_reapply_context(plan, decision_sha, 0, context)


def test_no_out_of_range_or_non_reapply_schedule(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "project")
    with pytest.raises(RecoveryRejected):
        scheduled_reapply_context_sources(plan, "f" * 64, 3)
    with pytest.raises(RecoveryRejected):
        complete_reapply_source_refs(make_plan(tmp_path / "other"))


def _accepted_progress(
    plan: RecoveryPlan, root: Path, *, source_index: int, number: int, previous: str | None
) -> tuple[object, StateEvent, AcceptedRoleArtifact, object]:
    task = make_task().model_copy(
        update={
            "id": plan.new_task_id,
            "repository": str(root),
            "base_ref": plan.target_base_revision,
        }
    )
    context = FileContextBuilder(
        root,
        plan.permissions,
        sources=scheduled_reapply_context_sources(plan, "f" * 64, source_index),
    ).build(task, AgentRole.CODER, attempt=number)
    original = make_coder_progress_artifact()
    artifact = seal_artifact(
        original.model_copy(
            update={
                "artifact_id": f"art_progress_{number:03d}",
                "task_id": plan.new_task_id,
                "producer": original.producer.model_copy(
                    update={"run_id": f"run_schedule_{number:03d}"}
                ),
                "source_revision": plan.target_base_revision,
                "context_manifest_id": context.context_id,
                "supersedes": previous,
                "content": original.content.model_copy(update={"checkpoint_sequence": number}),
            }
        ),
        validated_at=NOW,
    )
    event = StateEvent(
        event_id=f"evt_schedule_{number:03d}",
        task_id=plan.new_task_id,
        from_status=TaskStatus.IMPLEMENTING,
        to_status=TaskStatus.CONTINUE_REQUIRED,
        actor=AgentRole.ORCHESTRATOR,
        attempt=number,
        reason="coder_requested_continuation",
        artifact_ids=(artifact.artifact_id,),
        source_revision=plan.target_base_revision,
        occurred_at=NOW,
    )
    publication = AcceptedRoleArtifact(
        task_id=plan.new_task_id,
        work_item_id=f"work_schedule_{number:03d}",
        lease_id=f"lease_schedule_{number:03d}",
        dispatch_sequence=number,
        checkpoint_sequence=number,
        run_id=artifact.producer.run_id,
        context_manifest_id=context.context_id,
        source_revision=plan.target_base_revision,
        receipt=QueueArtifactReceipt(
            artifact_id=artifact.artifact_id, sha256=artifact.integrity.sha256
        ),
    )
    return artifact, event, publication, context


def test_only_accepted_progress_with_exact_full_context_advances_source(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "project")
    first = _accepted_progress(plan, tmp_path / "project", source_index=0, number=1, previous=None)
    second = _accepted_progress(
        plan, tmp_path / "project", source_index=1, number=2, previous=first[0].artifact_id
    )
    artifacts = {item[0].artifact_id: item[0] for item in (first, second)}
    contexts = {item[3].context_id: item[3] for item in (first, second)}
    artifact_store = SimpleNamespace(get=artifacts.__getitem__)
    context_store = SimpleNamespace(get=contexts.__getitem__)
    assert accepted_reapply_source_index(
        plan, "f" * 64, (), (), artifact_store, context_store
    ) == 0
    assert accepted_reapply_source_index(
        plan, "f" * 64, (first[2],), (first[1],), artifact_store, context_store
    ) == 1
    assert accepted_reapply_source_index(
        plan,
        "f" * 64,
        (first[2], second[2]),
        (first[1], second[1]),
        artifact_store,
        context_store,
    ) == 2
    # Merely accepting an Artifact file is not an accepted progress checkpoint.
    with pytest.raises(RecoveryRejected):
        accepted_reapply_source_index(
            plan, "f" * 64, (first[2],), (), artifact_store, context_store
        )
    # A queue publication from another checkpoint cannot be paired with this
    # Task event, even when its Artifact digest and Context identity match.
    with pytest.raises(RecoveryRejected, match="checkpoint"):
        accepted_reapply_source_index(
            plan,
            "f" * 64,
            (first[2],),
            (first[1].model_copy(update={"attempt": first[1].attempt + 1}),),
            artifact_store,
            context_store,
        )
    with pytest.raises(RecoveryRejected):
        accepted_reapply_source_index(
            plan,
            "f" * 64,
            (first[2], second[2]),
            (first[1],),
            artifact_store,
            context_store,
        )
    wrong_event = first[1].model_copy(update={"reason": "candidate_ready"})
    with pytest.raises(RecoveryRejected):
        accepted_reapply_source_index(
            plan, "f" * 64, (first[2],), (wrong_event,), artifact_store, context_store
        )


def test_foreign_or_skipped_source_cannot_advance(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "project")
    skipped = _accepted_progress(
        plan, tmp_path / "project", source_index=1, number=1, previous=None
    )
    artifacts = {skipped[0].artifact_id: skipped[0]}
    contexts = {skipped[3].context_id: skipped[3]}
    with pytest.raises(RecoveryRejected):
        accepted_reapply_source_index(
            plan,
            "f" * 64,
            (skipped[2],),
            (skipped[1],),
            SimpleNamespace(get=artifacts.__getitem__),
            SimpleNamespace(get=contexts.__getitem__),
        )


def test_exactly_retired_rejected_progress_does_not_block_reapply_source(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path / "project")
    rejected = _accepted_progress(
        plan, tmp_path / "project", source_index=0, number=1, previous=None
    )
    artifacts = {rejected[0].artifact_id: rejected[0]}
    contexts = {rejected[3].context_id: rejected[3]}
    publication = rejected[2]
    evidence = RejectedCoderOutputEvidence(
        scope=EngineeringScope(
            team_id=plan.source.scope.team_id,
            project_id="project_recovery_fixture",
            repository_id=plan.source.scope.repository_id,
            repository_root=plan.source.scope.repository_root,
        ),
        requirement_id=plan.source.scope.delivery_id,
        task_id=plan.new_task_id,
        work_item_id=publication.work_item_id,
        original_lease_id=publication.lease_id,
        original_claim_sha256="1" * 64,
        original_attempt=publication.checkpoint_sequence,
        original_dispatch_sequence=publication.dispatch_sequence,
        checkpoint_sequence=publication.checkpoint_sequence,
        previous_run_id=publication.run_id,
        previous_context_manifest_id=publication.context_manifest_id,
        source_revision=publication.source_revision,
        invocation_start_sha256="2" * 64,
        invocation_outcome_sha256="3" * 64,
        rejected_artifact_id=publication.receipt.artifact_id,
        rejected_artifact_sha256=publication.receipt.sha256,
        expected_sequence=publication.checkpoint_sequence,
        reported_sequence=publication.checkpoint_sequence + 1,
        process_stop_sha256="4" * 64,
        capture_sha256="5" * 64,
        workspace_inventory_sha256="6" * 64,
        checkpoint_sha256="7" * 64,
    )
    artifact_store = SimpleNamespace(get=artifacts.__getitem__)
    context_store = SimpleNamespace(get=contexts.__getitem__)
    assert accepted_reapply_source_index(
        plan,
        "f" * 64,
        (publication,),
        (),
        artifact_store,
        context_store,
        retired_rejected_outputs=(evidence,),
    ) == 0

    # A near miss is not silently discarded: only the complete immutable identity
    # of the consumed rejected-output proof can retire a publication.
    changed = evidence.model_copy(update={"rejected_artifact_sha256": "8" * 64})
    with pytest.raises(RecoveryRejected):
        accepted_reapply_source_index(
            plan,
            "f" * 64,
            (publication,),
            (),
            artifact_store,
            context_store,
            retired_rejected_outputs=(changed,),
        )
