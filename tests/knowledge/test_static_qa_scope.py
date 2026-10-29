"""A sealed static QA proof narrows consultation, never the delivery context."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents.structured import StructuredModelResult
from ai_software_engineer.agents.verification_output import StaticQaMissingEntry
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.knowledge.agents import KnowledgeConsultation
from ai_software_engineer.knowledge.assessment_validation import (
    STATIC_QA_KNOWLEDGE_INSTRUCTIONS,
    STATIC_QA_NODE_KNOWLEDGE_INSTRUCTIONS,
    StaticQaKnowledgeProjection,
)
from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised
from ai_software_engineer.knowledge.models import KnowledgeSnapshot
from ai_software_engineer.knowledge.runtime import StaticQaKnowledgeScope
from tests.knowledge.test_consultation import Model
from tests.knowledge.test_delivery_context import _builder
from tests.orchestration.test_runner import _definitions


def _scope(task_id: str, source_revision: str, criterion_id: str) -> StaticQaKnowledgeScope:
    return StaticQaKnowledgeScope(
        task_id=task_id,
        source_revision=source_revision,
        attempt=1,
        claim_sha256="1" * 64,
        claim_identity_sha256="5" * 64,
        authority_sha256="2" * 64,
        observation_sha256="3" * 64,
        proof_sha256="4" * 64,
        plan_artifact_id="plan_1",
        implementation_artifact_id="impl_1",
        missing=(
            StaticQaMissingEntry(path="tests/browser.test.cjs", criterion_ids=(criterion_id,)),
        ),
    )


def test_named_node_scope_names_only_the_direct_source_gap() -> None:
    legacy = _scope("task_static", "a" * 40, "ac_001")
    baseline = StaticQaKnowledgeProjection(scope=legacy, parent_context_manifest_id="ctx_legacy")
    assert baseline.consultation_payload()["assessment_boundary"] == (
        STATIC_QA_KNOWLEDGE_INSTRUCTIONS
    )
    assert "node_ids" not in baseline.consultation_payload()["run_scope"]["missing"][0]

    entry = legacy.missing[0].model_copy(
        update={"node_ids": ("tests/test_live.py::test_production_a_to_b_live",)}
    )
    named = StaticQaKnowledgeProjection(
        scope=legacy.model_copy(update={"missing": (entry,)}),
        parent_context_manifest_id="ctx_named",
    )
    payload = named.consultation_payload()
    assert payload["assessment_boundary"] == STATIC_QA_NODE_KNOWLEDGE_INSTRUCTIONS
    assert (
        "does not prove the result of dynamic pytest collection" in payload["assessment_boundary"]
    )
    assert payload["run_scope"]["missing"][0]["node_ids"] == [
        "tests/test_live.py::test_production_a_to_b_live"
    ]


def test_static_qa_consults_only_proof_scope_but_preserves_complete_context(
    tmp_path: Path,
) -> None:
    class ScopeModel(Model):
        def complete(
            self,
            *,
            instructions: str,
            input_payload: Mapping[str, object],
            output_schema: Mapping[str, object],
            timeout_seconds: int,
            input_images: tuple[Path, ...] = (),
        ) -> StructuredModelResult:
            assert "live A-to-B acceptance checks remain NOT_RUN" in instructions
            task_input = input_payload["task"]
            assert isinstance(task_input, dict)
            assert set(task_input) == {
                "run_scope",
                "parent_context_manifest_id",
                "assessment_boundary",
                "design_rechecks",
                "approved_knowledge_resolutions",
            }
            assert task_input["run_scope"]["original_acceptance_status"] == "NOT_RUN"
            assert "acceptance_criteria" not in task_input
            return super().complete(
                instructions=instructions,
                input_payload=input_payload,
                output_schema=output_schema,
                timeout_seconds=timeout_seconds,
                input_images=input_images,
            )

    task, contexts, records, builder = _builder(tmp_path, model=ScopeModel())
    full = builder.delegate.build(task, _definitions()[AgentRole.QA], attempt=1)
    scope = _scope(task.id, full.source_revision, task.acceptance_criteria[0].id)
    builder.static_qa_scope = lambda *_: scope
    context = builder.build(task, _definitions()[AgentRole.QA], attempt=1)
    assert context.sections[: len(full.sections)] == full.sections
    assert contexts.get(context.context_id) == context
    receipt = KnowledgeConsultation.model_validate_json(
        next(
            section.content
            for section in context.sections
            if section.name == "knowledge.consultation"
        )
    )
    assert records.get("consultations", receipt.binding.run_id, KnowledgeConsultation) == receipt
    assert receipt.binding.context_manifest_id == full.context_id
    assert receipt.assessment.status == "SUFFICIENT"
    snapshot = records.get("snapshots", receipt.binding.snapshot_sha256, KnowledgeSnapshot)
    assert snapshot.documents and snapshot.documents[0].source_uri == builder.sources[0].uri


def test_static_scope_fails_closed_when_provider_changes_task_or_revision(tmp_path: Path) -> None:
    task, _, _, builder = _builder(tmp_path)
    builder.static_qa_scope = lambda *_: _scope(task.id, "wrong", task.acceptance_criteria[0].id)
    with pytest.raises(ValueError, match="static QA knowledge scope"):
        builder.build(task, _definitions()[AgentRole.QA], attempt=1)


@pytest.mark.parametrize("role", (AgentRole.QA, AgentRole.REVIEWER))
def test_roles_without_consumed_static_decision_keep_complete_consultation(
    tmp_path: Path, role: AgentRole
) -> None:
    class OrdinaryModel(Model):
        def complete(
            self,
            *,
            instructions: str,
            input_payload: Mapping[str, object],
            output_schema: Mapping[str, object],
            timeout_seconds: int,
            input_images: tuple[Path, ...] = (),
        ) -> StructuredModelResult:
            if output_schema["title"] == "KnowledgeIntent":
                task_payload = input_payload["task"]
                assert isinstance(task_payload, dict)
                assert "run_scope" not in task_payload
                assert "acceptance_criteria" in task_payload["task"]
                assert "context" in task_payload
            return super().complete(
                instructions=instructions,
                input_payload=input_payload,
                output_schema=output_schema,
                timeout_seconds=timeout_seconds,
                input_images=input_images,
            )

    task, _, _, builder = _builder(tmp_path, model=OrdinaryModel())
    builder.static_qa_scope = lambda *_: None
    builder.build(task, _definitions()[role], attempt=1)


def test_static_scope_cannot_bypass_an_unresolved_prior_knowledge_gap(tmp_path: Path) -> None:
    task, _, _, builder = _builder(tmp_path, enabled=False)
    definition = _definitions()[AgentRole.QA]
    with pytest.raises(KnowledgeGapRaised):
        builder.build(task, definition, attempt=1)
    base = builder.delegate.build(task, definition, attempt=1)
    builder.static_qa_scope = lambda *_: _scope(
        task.id, base.source_revision, task.acceptance_criteria[0].id
    )
    with pytest.raises(KnowledgeGapRaised):
        builder.build(task, definition, attempt=1)
