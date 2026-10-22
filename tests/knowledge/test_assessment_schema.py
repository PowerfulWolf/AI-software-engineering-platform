"""The actual consultation transport constrains whole citations to this Run's READs."""

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, ValidationError

from ai_software_engineer.agents.json_schema import strict_output_schema
from ai_software_engineer.agents.structured import StructuredModelResult
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.assessment_validation import (
    KnowledgeAssessment,
    assessment_output_schema,
)
from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised
from ai_software_engineer.knowledge.models import KnowledgeCitation, KnowledgeEvidence
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from tests.knowledge.test_consultation import Model
from tests.knowledge.test_retrieval_contract import binding, document, snapshot


class _SchemaCapture(Model):
    def __init__(self) -> None:
        super().__init__()
        self.schema: Mapping[str, object] = {}
        self.citations: tuple[dict[str, object], ...] = ()

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        if output_schema["title"] == "KnowledgeAssessment":
            self.schema = output_schema
            evidence = tuple(
                KnowledgeEvidence.model_validate(item)
                for item in cast(list[object], input_payload["knowledge_evidence"])
            )
            self.citations = tuple(
                dict[str, object](item.chunk.citation.to_wire())
                for item in evidence
                if item.status == "READ" and item.chunk is not None
            )
        return super().complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )


def _capture(tmp_path: Path) -> _SchemaCapture:
    first = document()
    second = document("# Other payments\n\nRefunds require original payment reference.").model_copy(
        update={"document_id": "doc_other", "source_uri": "knowledge://project_payments/other"}
    )
    frozen = snapshot(first, second)
    model = _SchemaCapture()
    consultation = KnowledgeConsultationService(model, KnowledgeRecordStore(tmp_path)).consult(
        binding(frozen), frozen, {"task": "approved original"}, timeout_seconds=30
    )
    assert len(consultation.manifest.citations) == len(model.citations) == 2
    return model


def _assessment(citations: list[dict[str, object]]) -> dict[str, object]:
    return KnowledgeAssessment.model_validate(
        {"status": "SUFFICIENT", "claims": [{"statement": "Read fact", "citations": citations}]}
    ).model_dump(mode="json")


@pytest.mark.parametrize("strict", [False, True])
def test_actual_assessment_schema_rejects_changed_exact_chunk_id(
    tmp_path: Path, strict: bool
) -> None:
    model = _capture(tmp_path)
    schema = strict_output_schema(model.schema) if strict else model.schema
    validator = Draft202012Validator(schema)
    validator.validate(_assessment([model.citations[0]]))
    validator.validate(_assessment(list(model.citations)))
    wrong = dict(model.citations[0])
    original = str(wrong["chunk_id"])
    # The production failure changed two valid hex characters while retaining every other field.
    wrong["chunk_id"] = original[:20] + ("eb" if original[20:22] != "eb" else "12") + original[22:]
    with pytest.raises(ValidationError):
        validator.validate(_assessment([wrong]))


@pytest.mark.parametrize("strict", [False, True])
def test_actual_assessment_schema_rejects_cross_read_field_splicing(
    tmp_path: Path, strict: bool
) -> None:
    model = _capture(tmp_path)
    schema = strict_output_schema(model.schema) if strict else model.schema
    mixed = {**model.citations[0], "chunk_id": model.citations[1]["chunk_id"]}
    assert mixed not in model.citations
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(_assessment([mixed]))


@pytest.mark.parametrize(
    "field", ["document_id", "scope", "document_sha256", "chunk_id", "chunk_sha256", "source_uri"]
)
def test_each_citation_field_is_bound_as_a_complete_object(tmp_path: Path, field: str) -> None:
    model = _capture(tmp_path)
    wrong = dict(model.citations[0])
    replacements: dict[str, object] = {
        "document_id": "doc_unread",
        "scope": "team",
        "document_sha256": "f" * 64,
        "chunk_id": "f" * 64,
        "chunk_sha256": "f" * 64,
        "source_uri": str(wrong["source_uri"]).upper(),
    }
    wrong[field] = replacements[field]
    assert wrong not in model.citations
    with pytest.raises(ValidationError):
        Draft202012Validator(strict_output_schema(model.schema)).validate(_assessment([wrong]))


def test_duplicate_reads_do_not_expand_schema_or_modify_static_contract(tmp_path: Path) -> None:
    static = KnowledgeAssessment.model_json_schema()
    model = _capture(tmp_path)
    citations = tuple(KnowledgeCitation.model_validate(value) for value in model.citations)
    schema = assessment_output_schema(citations)
    assert assessment_output_schema((*citations, *citations)) == schema
    assert model.schema == schema
    assert KnowledgeAssessment.model_json_schema() == static
    assert static != schema


@pytest.mark.parametrize("status", ["SUFFICIENT", "GAP"])
def test_empty_reads_allow_no_claims_and_keep_semantic_missing_evidence_gate(
    tmp_path: Path, status: str
) -> None:
    class EmptyReads(_SchemaCapture):
        def complete(
            self,
            *,
            instructions: str,
            input_payload: Mapping[str, object],
            output_schema: Mapping[str, object],
            timeout_seconds: int,
            input_images: tuple[Path, ...] = (),
        ) -> StructuredModelResult:
            result = super().complete(
                instructions=instructions,
                input_payload=input_payload,
                output_schema=output_schema,
                timeout_seconds=timeout_seconds,
                input_images=input_images,
            )
            if output_schema["title"] == "KnowledgeAssessment":
                return StructuredModelResult(payload={"status": status}, duration_ms=1)
            return result

    frozen = snapshot()
    bound = binding(frozen)
    records = KnowledgeRecordStore(tmp_path)
    model = EmptyReads()
    with pytest.raises(KnowledgeGapRaised):
        KnowledgeConsultationService(model, records).consult(
            bound, frozen, {"task": "approved original"}, timeout_seconds=30
        )
    assert model.citations == ()
    from ai_software_engineer.knowledge.agents import KnowledgeConsultation

    accepted = records.get("consultations", bound.run_id, KnowledgeConsultation)
    assert accepted.assessment.status == "GAP" and accepted.assessment.claims == ()
    empty = KnowledgeAssessment(status="GAP").model_dump(mode="json")
    sufficient = KnowledgeAssessment(status="SUFFICIENT").model_dump(mode="json")
    fake = dict[str, object](
        KnowledgeCitation(
            document_id="doc_unread",
            scope="project",
            document_sha256="a" * 64,
            chunk_id="b" * 64,
            chunk_sha256="c" * 64,
            source_uri="knowledge://unread",
        ).to_wire()
    )
    for schema in (model.schema, strict_output_schema(model.schema)):
        Draft202012Validator(schema).validate(empty)
        Draft202012Validator(schema).validate(sufficient)
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(_assessment([fake]))
