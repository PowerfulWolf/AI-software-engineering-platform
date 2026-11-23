from __future__ import annotations

import inspect

from ai_software_engineer.git.policy import (
    NATIVE_RULE_PROPOSAL_ASSESSMENT,
    NATIVE_RULE_PROPOSAL_GUIDANCE,
    is_protected_rule_path,
)
from ai_software_engineer.knowledge.assessment_validation import KNOWLEDGE_ASSESSMENT_INSTRUCTIONS
from ai_software_engineer.manager import production_agents
from ai_software_engineer.multi_directory import service


def test_protected_rule_paths_stay_read_only() -> None:
    assert is_protected_rule_path(".trellis/spec/core/execution-retry-policy.md")
    assert not is_protected_rule_path("docs/execution-retry-policy.md")


def test_requested_native_rule_edit_becomes_a_proposal_in_every_upstream_prompt() -> None:
    assert ".trellis/" in NATIVE_RULE_PROPOSAL_GUIDANCE
    assert "non_goals" in NATIVE_RULE_PROPOSAL_GUIDANCE
    single = inspect.getsource(production_agents)
    joint = inspect.getsource(service)
    # Product, Designer and Planner on both the single- and multi-directory paths.
    assert single.count("+ NATIVE_RULE_PROPOSAL_GUIDANCE") == 3
    assert joint.count("+ NATIVE_RULE_PROPOSAL_GUIDANCE") == 3


def test_downstream_knowledge_assessment_does_not_raise_ownership_gaps() -> None:
    assert KNOWLEDGE_ASSESSMENT_INSTRUCTIONS.endswith(NATIVE_RULE_PROPOSAL_ASSESSMENT)
    assert "do not return GAP" in NATIVE_RULE_PROPOSAL_ASSESSMENT
