"""Canonical production roster for the Team-owned AI team."""

from __future__ import annotations

import hashlib
import json

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import (
    AgentProfile,
    BrainTier,
    ModelPolicy,
    ModelRoute,
    RiskModelFloor,
    RiskTier,
    TeamRole,
)
from ai_software_engineer.domain.model import JsonValue

DELIVERY_CAPABILITIES = (
    "implementation",
    "testing",
    "review",
    "security",
    "contract-validation",
    "python",
    "java",
    "cpp",
    "go",
    "typescript",
)

_ROLE_CAPABILITIES: dict[TeamRole, tuple[str, ...]] = {
    TeamRole.MANAGER: (
        "project-management",
        "delivery-coordination",
        "dispatch-authority",
    ),
    TeamRole.PRODUCT: ("product-discovery", "requirements"),
    TeamRole.DESIGNER: ("architecture", "technical-design"),
    TeamRole.PLANNER: ("planning", "scheduler-preview", "model-router-preview"),
    TeamRole.CODER: DELIVERY_CAPABILITIES,
    TeamRole.QA: DELIVERY_CAPABILITIES,
    TeamRole.REVIEWER: DELIVERY_CAPABILITIES,
}
TEAM_CAPABILITIES = tuple(
    dict.fromkeys(
        capability for capabilities in _ROLE_CAPABILITIES.values() for capability in capabilities
    )
)


def production_team_roster(
    config: ProductionConfig,
) -> tuple[tuple[AgentProfile, ...], ModelPolicy]:
    """Return the stable seven-member roster and its immutable default model policy."""
    primary = config.enabled_routes()[0]
    policy = ModelPolicy(
        id="model_policy_delivery_default",
        version="v0.1",
        default_tier=BrainTier.CRITICAL,
        routes=(
            ModelRoute(
                provider=primary.provider,
                model=primary.model,
                tier=BrainTier.CRITICAL,
                capabilities=TEAM_CAPABILITIES,
            ),
        ),
        risk_floors=tuple(
            RiskModelFloor(risk=risk, minimum_tier=BrainTier.CRITICAL) for risk in RiskTier
        ),
    )
    policy = policy.model_copy(
        update={
            "version": "v0.1-"
            + hashlib.sha256(
                json.dumps(
                    policy.model_dump(mode="json", exclude={"version"}),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
        }
    )
    profiles = tuple(
        AgentProfile(
            id=f"agent_team_{role.value}",
            version="v0.1",
            display_name=_display_name(role),
            capabilities=_ROLE_CAPABILITIES[role],
            eligible_roles=(role,),
            max_parallel_assignments=8,
            default_model_policy_id=policy.id,
            metadata=_metadata(role),
        )
        for role in _ROLE_CAPABILITIES
    )
    return profiles, policy


def _display_name(role: TeamRole) -> str:
    return {
        TeamRole.MANAGER: "Manager Agent",
        TeamRole.PRODUCT: "Product Agent",
        TeamRole.DESIGNER: "Designer Agent",
        TeamRole.PLANNER: "Planner Agent",
        TeamRole.CODER: "Coder Agent",
        TeamRole.QA: "QA Agent",
        TeamRole.REVIEWER: "Reviewer Agent",
    }[role]


def _metadata(role: TeamRole) -> dict[str, JsonValue]:
    del role
    return {"ownership": "team", "member_type": "model_agent"}


__all__ = [
    "DELIVERY_CAPABILITIES",
    "TEAM_CAPABILITIES",
    "production_team_roster",
]
