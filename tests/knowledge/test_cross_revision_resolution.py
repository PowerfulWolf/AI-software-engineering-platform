"""Requirement decisions survive a new candidate revision; code facts do not."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from ai_software_engineer.knowledge.agents import shared_with_other_role
from ai_software_engineer.knowledge.gaps import KnowledgeResolution, KnowledgeResolutionSource
from ai_software_engineer.knowledge.models import digest, text_digest

_SCHEMA = Path(__file__).resolve().parents[2] / "schemas/knowledge-resolution.schema.json"


def _resolution(*, cross_revision: bool) -> KnowledgeResolution:
    answer = "Explicit deletion is asserted as physical absence."
    provisional = KnowledgeResolution(
        gap_id="a" * 64,
        previous_run_id="run_knowledge_fixture",
        answer=answer,
        sources=(
            KnowledgeResolutionSource(
                uri="human://fixture/decision", content=answer, sha256=text_digest(answer)
            ),
        ),
        approval_reference="human:fixture",
        approved_by="human:local-console",
        cross_revision=cross_revision,
        resolution_id="0" * 64,
    )
    return provisional.model_copy(
        update={
            "resolution_id": digest(provisional.model_dump(mode="json", exclude={"resolution_id"}))
        }
    )


def test_code_fact_stays_bound_to_its_revision() -> None:
    fact = _resolution(cross_revision=False)
    assert shared_with_other_role(fact, gap_revision="b" * 40, current_revision="b" * 40)
    assert not shared_with_other_role(fact, gap_revision="b" * 40, current_revision="c" * 40)


def test_requirement_decision_reaches_other_roles_after_a_new_candidate() -> None:
    decision = _resolution(cross_revision=True)
    assert shared_with_other_role(decision, gap_revision="b" * 40, current_revision="c" * 40)


def test_default_keeps_historical_digest_and_both_shapes_match_the_schema() -> None:
    fact, decision = _resolution(cross_revision=False), _resolution(cross_revision=True)
    assert "cross_revision" not in fact.to_wire()
    fact.validate_integrity()
    decision.validate_integrity()
    assert decision.to_wire()["cross_revision"] is True
    validator = Draft202012Validator(json.loads(_SCHEMA.read_text()))
    for item in (fact, decision):
        validator.validate(item.to_wire())
    assert KnowledgeResolution.model_validate(decision.to_wire()) == decision
