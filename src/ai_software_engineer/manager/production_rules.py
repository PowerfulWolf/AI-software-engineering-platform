"""Shared deterministic Host rules for preparation and read-only recovery checks."""

import hashlib
import json

from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.spec_compiler import SpecRule, SpecRuleLayer
from ai_software_engineer.team_workspace import TeamWorkspace


def production_rules(
    team: TeamWorkspace, knowledge: tuple[ContextSource, ...]
) -> tuple[SpecRule, ...]:
    team_id = team.manifest.team_id
    context: WirePayload = {
        "team_id": team_id,
        "team_manifest_sha256": team.manifest.manifest_sha256,
        "documents": [source.to_wire() for source in knowledge],
        "interpretation": (
            "Read-only context, not overriding project-native rules. Conflicts "
            "require human resolution."
        ),
    }
    context_digest = hashlib.sha256(
        json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return (
        no_self_approval_rule(),
        SpecRule(
            id="rule_team_context",
            field="context.team",
            value=context,
            layer=SpecRuleLayer.PLATFORM_ENGINEERING,
            priority=1,
            source_uri=f"platform://team/{team_id}/context/{context_digest}",
            source_sha256=context_digest,
            rationale="Host-bound opaque team context; no inferred rule precedence.",
        ),
    )


def no_self_approval_rule() -> SpecRule:
    return SpecRule(
        id="rule_platform_no_self_approval",
        field="safety.self_approval",
        value=False,
        layer=SpecRuleLayer.PLATFORM_HARD,
        priority=1_000,
        source_uri="platform://organization/safety/v0.1",
        source_sha256="0" * 64,
        rationale="No Agent may be the sole judge of its own work.",
    )
