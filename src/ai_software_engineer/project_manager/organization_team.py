"""Canonical production roster for the organization-owned AI team."""

from __future__ import annotations

import hashlib
import json

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import (
    AgentProfile,
    BrainTier,
    ModelPolicy,
    ModelRoute,
    OrganizationRole,
    RiskModelFloor,
    RiskTier,
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

_ROLE_CAPABILITIES: dict[OrganizationRole, tuple[str, ...]] = {
    OrganizationRole.PROJECT_MANAGER: (
        "project-management",
        "delivery-coordination",
        "dispatch-authority",
    ),
    OrganizationRole.PRODUCT: ("product-discovery", "requirements"),
    OrganizationRole.DESIGNER: ("architecture", "technical-design"),
    OrganizationRole.PLANNER: ("planning", "scheduler-preview", "model-router-preview"),
    OrganizationRole.CODER: DELIVERY_CAPABILITIES,
    OrganizationRole.QA: DELIVERY_CAPABILITIES,
    OrganizationRole.REVIEWER: DELIVERY_CAPABILITIES,
}
ORGANIZATION_CAPABILITIES = tuple(
    dict.fromkeys(
        capability for capabilities in _ROLE_CAPABILITIES.values() for capability in capabilities
    )
)


def production_organization_team(
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
                capabilities=ORGANIZATION_CAPABILITIES,
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


def _display_name(role: OrganizationRole) -> str:
    return {
        OrganizationRole.PROJECT_MANAGER: "Project Manager",
        OrganizationRole.PRODUCT: "Product Agent",
        OrganizationRole.DESIGNER: "Solution Designer",
        OrganizationRole.PLANNER: "Planner Agent",
        # Preserve the already-persisted v0.1 identities for the original delivery trio.
        OrganizationRole.CODER: "Team Coder",
        OrganizationRole.QA: "Team Qa",
        OrganizationRole.REVIEWER: "Team Reviewer",
    }[role]


def _metadata(role: OrganizationRole) -> dict[str, JsonValue]:
    if role in {OrganizationRole.CODER, OrganizationRole.QA, OrganizationRole.REVIEWER}:
        return {}
    return {"ownership": "organization", "member_type": "model_agent"}


__all__ = [
    "DELIVERY_CAPABILITIES",
    "ORGANIZATION_CAPABILITIES",
    "production_organization_team",
]
