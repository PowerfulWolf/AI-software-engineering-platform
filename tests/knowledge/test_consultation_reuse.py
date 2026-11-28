"""Later runs of one Task role reuse the sealed knowledge verdict for unchanged inputs."""

from pathlib import Path

from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.agents import (
    KnowledgeConsultationReuse,
    KnowledgeConsultationService,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from tests.knowledge.test_consultation import Model
from tests.knowledge.test_retrieval_contract import binding, document, snapshot


def _later(frozen, run: str, role: TeamRole = TeamRole.CODER):  # type: ignore[no-untyped-def]
    return binding(frozen, role).model_copy(
        update={
            "run_id": "run_knowledge_" + run,
            "source_revision": "c" * 40,
            "context_manifest_id": "ctx_" + run[-1] * 64,
        }
    )


def test_second_attempt_with_same_key_makes_no_model_call(tmp_path: Path) -> None:
    frozen = snapshot(document())
    records = KnowledgeRecordStore(tmp_path)
    model = Model()
    service = KnowledgeConsultationService(model, records)
    first = service.consult(
        binding(frozen), frozen, {"attempt": 1}, timeout_seconds=30, reuse_key="key-a"
    )
    assert model.calls == ["KnowledgeIntent", "KnowledgeAssessment"]
    assert first.assessment.status == "SUFFICIENT"
    assert (
        records.get("consultation-reuse", "key-a", KnowledgeConsultationReuse).run_id
        == first.binding.run_id
    )

    second = service.consult(
        _later(frozen, "002"), frozen, {"attempt": 2}, timeout_seconds=30, reuse_key="key-a"
    )
    # No new knowledge model call; the new run still re-read and sealed its own evidence.
    assert model.calls == ["KnowledgeIntent", "KnowledgeAssessment"]
    assert second.binding.run_id != first.binding.run_id
    assert second.intent == first.intent and second.assessment == first.assessment
    assert second.manifest.citations and second.call_ids == ()


def test_changed_key_or_other_role_consults_again(tmp_path: Path) -> None:
    frozen = snapshot(document())
    records = KnowledgeRecordStore(tmp_path)
    model = Model()
    service = KnowledgeConsultationService(model, records)
    service.consult(binding(frozen), frozen, {}, timeout_seconds=30, reuse_key="key-a")
    service.consult(_later(frozen, "003"), frozen, {}, timeout_seconds=30, reuse_key="key-b")
    assert model.calls == ["KnowledgeIntent", "KnowledgeAssessment"] * 2
    # A key copied to another role never reuses the coder's verdict.
    service.consult(
        _later(frozen, "004", TeamRole.QA), frozen, {}, timeout_seconds=30, reuse_key="key-a"
    )
    assert model.calls == ["KnowledgeIntent", "KnowledgeAssessment"] * 3


def test_without_key_behaviour_is_unchanged(tmp_path: Path) -> None:
    frozen = snapshot(document())
    model = Model()
    service = KnowledgeConsultationService(model, KnowledgeRecordStore(tmp_path))
    service.consult(binding(frozen), frozen, {}, timeout_seconds=30)
    service.consult(_later(frozen, "005"), frozen, {}, timeout_seconds=30)
    assert model.calls == ["KnowledgeIntent", "KnowledgeAssessment"] * 2
