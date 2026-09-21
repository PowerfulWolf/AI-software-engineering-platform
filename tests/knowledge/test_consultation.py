from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents.structured import StructuredModelResult
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.agents import KnowledgeAwareStructuredClient
from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised, KnowledgeGapRouting
from ai_software_engineer.knowledge.models import KnowledgeEvidence
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from tests.knowledge.test_retrieval_contract import binding, document, snapshot


class Model:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.instructions: dict[str, str] = {}

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        name = str(output_schema["title"])
        self.calls.append(name)
        self.instructions[name] = instructions
        if name == "KnowledgeIntent":
            return StructuredModelResult(payload={"queries": ["original payment"]}, duration_ms=1)
        if name == "KnowledgeAssessment":
            evidence = tuple(
                KnowledgeEvidence.model_validate(value)
                for value in cast(list[object], input_payload["knowledge_evidence"])
            )
            reads = [value.chunk for value in evidence if value.chunk is not None]
            if not reads:
                return StructuredModelResult(
                    payload={"status": "GAP", "gap_question": "What payment identity is required?"},
                    duration_ms=1,
                )
            return StructuredModelResult(
                payload={
                    "status": "SUFFICIENT",
                    "claims": [
                        {
                            "statement": "Use original payment ID.",
                            "citations": [reads[0].citation.to_wire()],
                        }
                    ],
                },
                duration_ms=1,
            )
        consultation = cast(dict[str, object], input_payload["knowledge_consultation"])
        assert consultation["manifest"]
        return StructuredModelResult(payload={"answer": "Use original payment ID."}, duration_ms=1)


@pytest.mark.parametrize("role", list(TeamRole))
def test_real_composition_seam_consults_and_replays(tmp_path: Path, role: TeamRole) -> None:
    frozen = snapshot(document())
    bound = binding(frozen, role)
    model = Model()
    records = KnowledgeRecordStore(tmp_path)
    client = KnowledgeAwareStructuredClient(model, bound, frozen, records)
    args = dict(
        instructions="Produce role output",
        input_payload={"question": "refund"},
        output_schema={"title": "Output"},
        timeout_seconds=10,
    )
    assert client.complete(**args).payload == {"answer": "Use original payment ID."}  # type: ignore[arg-type]
    assert model.calls == ["KnowledgeIntent", "KnowledgeAssessment", "Output"]
    client.complete(**args)  # type: ignore[arg-type]
    assert model.calls == ["KnowledgeIntent", "KnowledgeAssessment", "Output", "Output"]


def test_unknown_stops_before_final_role_call(tmp_path: Path) -> None:
    frozen = snapshot()
    model = Model()
    records = KnowledgeRecordStore(tmp_path)
    client = KnowledgeAwareStructuredClient(model, binding(frozen), frozen, records)
    with pytest.raises(KnowledgeGapRaised) as error:
        client.complete(
            instructions="Act",
            input_payload={"question": "refund"},
            output_schema={"title": "Output"},
            timeout_seconds=10,
        )
    assert error.value.gap.evidence_ids
    assert error.value.gap.question == "请补充当前工作缺少的关键事实。请说明可核验的依据。"
    assert error.value.gap.required_decision == "请提供已核实的信息。请确认将此解答用于当前需求。"
    assert error.value.gap.impact == "角色缺少可靠依据。无法安全继续。"
    route = records.get("gap-routes", error.value.gap.gap_id, KnowledgeGapRouting)
    assert route.rationale == "关键事实需要经过核实并由人工确认。"
    assert "人工确认问题必须使用简体中文" in model.instructions["KnowledgeAssessment"]
    assert model.calls == ["KnowledgeIntent", "KnowledgeAssessment"]
