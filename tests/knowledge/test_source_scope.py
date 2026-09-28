"""Source wrappers must narrow, never erase, retrieval visibility."""

import json

import pytest

from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain import AgentRole, TeamRole
from ai_software_engineer.knowledge.context import snapshot_from_sources
from ai_software_engineer.manager.baseline import ProjectSpecBaseline
from ai_software_engineer.spec_compiler import SpecRule, SpecRuleLayer
from tests.manager.test_baseline import hard_rule


@pytest.mark.parametrize("scope", ["nested", "spec_foreign", "orchestrator_only"])
def test_source_wrappers_cannot_broaden_document_scope(scope: str) -> None:
    source = ContextSource(
        source_id="team.background",
        uri="team://team_ai/knowledge/knowledge_document_refunds",
        content="# Refunds\nOriginal payment identity.",
        roles=(AgentRole.CODER,),
    )
    rule = SpecRule(
        id="rule_context_team",
        field="context.team",
        layer=SpecRuleLayer.PLATFORM_ENGINEERING,
        priority=100,
        scopes=("*",),
        source_uri="platform://context/team",
        source_sha256="a" * 64,
        rationale="Selected team knowledge",
        value={
            "team_id": "team_ai",
            "team_manifest_sha256": "b" * 64,
            "documents": [source.to_wire()],
            "interpretation": "background only",
        },
    )
    if scope == "spec_foreign":
        rule = rule.model_copy(
            update={
                "field": "governance.foreign",
                "value": {
                    "spec_id": "spec_foreign",
                    "spec_key": "foreign",
                    "version": 1,
                    "title": "Foreign spec",
                    "body_markdown": "Never import foreign rules",
                    "roles": [],
                    "stages": [],
                    "repository_ids": ["repository_other"],
                    "path_globs": ["*"],
                    "verification": "tests",
                },
            }
        )
    baseline = ProjectSpecBaseline(
        repository_id="repository_payments",
        repository_profile_sha256="c" * 64,
        rules=(hard_rule(), rule),
        baseline_sha256="0" * 64,
    )
    from ai_software_engineer.manager.baseline import _baseline_digest

    baseline = baseline.model_copy(update={"baseline_sha256": _baseline_digest(baseline)})
    wrapper = ContextSource(
        source_id="project.baseline",
        uri=f"baseline://repository_payments/{baseline.baseline_sha256}",
        content=json.dumps(baseline.to_wire()),
        roles=(AgentRole.REVIEWER,) if scope == "nested" else (),
    )
    if scope == "orchestrator_only":
        wrapper = source.model_copy(update={"roles": (AgentRole.ORCHESTRATOR,)})
    frozen = snapshot_from_sources(
        team_id="team_ai",
        project_id="project_payments",
        requirement_id="req_scope",
        repository_ids=("repository_payments",),
        sources=(("repository_payments", wrapper),),
    )
    assert frozen.documents == ()


def test_roles_survive_direct_team_background() -> None:
    frozen = snapshot_from_sources(
        team_id="team_ai",
        project_id="project_payments",
        requirement_id="req_scope",
        repository_ids=("repository_payments",),
        sources=(
            (
                "repository_payments",
                ContextSource(
                    source_id="team.background",
                    uri="team://team_ai/knowledge/background",
                    content="Scoped",
                    roles=(AgentRole.CODER, AgentRole.ORCHESTRATOR),
                ),
            ),
        ),
    )
    assert frozen.documents[0].roles == (TeamRole.CODER,)
