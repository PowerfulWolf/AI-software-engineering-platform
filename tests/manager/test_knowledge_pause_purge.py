"""Physical cleanup binds prospective pause records to their exact knowledge owner."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.agents.structured_pause import StructuredPreAdmissionPauseReceipt
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationIntent,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.purge_knowledge import select_knowledge
from ai_software_engineer.multi_directory.scope import discover_scope
from tests.manager.test_delivery_wait import native as native
from tests.manager.test_knowledge_preparation_pause_consumer import paused_facts
from tests.orchestration.test_native_continuation import Fixture


def checkpoint(native: Fixture) -> JointCheckpoint:
    return JointCheckpoint(
        delivery_id="delivery_multi_pause_purge",
        team_id=native.scope.team_id,
        project_id=native.scope.project_id,
        team_manifest_sha256="a" * 64,
        project_manifest_sha256="b" * 64,
        sequence=1,
        stage=JointStage.READY_FOR_DISCUSSION,
        scope=discover_scope((native.task.repository,)),
        title="Pause cleanup fixture",
        submitted_at=datetime.now(UTC),
        next_action="fixture",
        checkpoint_sha256="c" * 64,
    )


@pytest.mark.parametrize("orphan", [False, True])
def test_owned_pause_and_pre_outcome_orphan_are_selected_without_foreign_lane(
    native: Fixture, tmp_path: Path, orphan: bool
) -> None:
    facts = paused_facts(native, tmp_path / "sidecar/state")
    bound = facts.outcome.intent.binding
    assert facts.outcome.pre_admission_pause is not None
    raw = facts.outcome.pre_admission_pause
    foreign_binding = bound.model_copy(
        update={"requirement_id": "delivery_foreign", "task_id": "task_foreign_001"}
    )
    foreign = KnowledgeInvocationIntent.create(
        binding=foreign_binding,
        phase=facts.outcome.intent.phase,
        request_sha256=facts.outcome.intent.request_sha256,
        timeout_seconds=facts.outcome.intent.timeout_seconds,
        claim=None,
        created_at=facts.outcome.intent.created_at,
    )
    foreign_lane = KnowledgeRecordStore(
        facts.records.root / "invocations" / invocation_lane_sha256(foreign_binding)
    )
    foreign_lane.put(
        "knowledge-invocation-intents", foreign.binding.run_id + ":" + foreign.phase, foreign
    )
    foreign_lane.put("structured-admission-pauses", raw.receipt_sha256, raw)
    if orphan:
        (
            facts.lane.root
            / KnowledgeRecordStore._name("knowledge-invocation-outcomes", bound.run_id + ":intent")
        ).unlink()
        (
            facts.records.root
            / KnowledgeRecordStore._name("knowledge-pause-intents", facts.outcome.outcome_sha256)
        ).unlink()
    selected = select_knowledge(
        facts.records.root,
        checkpoint(native),
        identities={native.task.id},
        task_repositories={native.task.id: facts.queue.item.repository_id},
        repository_id=facts.queue.item.repository_id,
    )
    raw_path = facts.lane.root / KnowledgeRecordStore._name(
        "structured-admission-pauses", raw.receipt_sha256
    )
    assert raw_path in selected and facts.lane.root in selected
    assert not any(
        path == foreign_lane.root or path.parent == foreign_lane.root for path in selected
    )
    if not orphan:
        assert (
            facts.records.root
            / KnowledgeRecordStore._name("knowledge-pause-intents", facts.outcome.outcome_sha256)
            in selected
        )
    assert (
        foreign_lane.get(
            "structured-admission-pauses", raw.receipt_sha256, StructuredPreAdmissionPauseReceipt
        )
        == raw
    )


def test_pause_with_no_matching_intent_cannot_be_swept_by_lane_name(
    native: Fixture, tmp_path: Path
) -> None:
    facts = paused_facts(native, tmp_path / "sidecar/state")
    assert facts.outcome.pre_admission_pause is not None
    raw = facts.outcome.pre_admission_pause
    foreign = StructuredPreAdmissionPauseReceipt.create(
        **raw.model_dump(exclude={"request_sha256", "receipt_sha256"}), request_sha256="9" * 64
    )
    facts.lane.put("structured-admission-pauses", foreign.receipt_sha256, foreign)
    with pytest.raises(ValueError, match="no exact intent"):
        select_knowledge(
            facts.records.root,
            checkpoint(native),
            identities={native.task.id},
            task_repositories={native.task.id: facts.queue.item.repository_id},
            repository_id=facts.queue.item.repository_id,
        )
