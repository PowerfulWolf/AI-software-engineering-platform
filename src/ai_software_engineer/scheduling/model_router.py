"""Deterministic per-Run model route selection."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from ai_software_engineer.domain.enums import BrainTier, ModelRouteReason
from ai_software_engineer.domain.workforce import (
    AgentProfile,
    ModelPolicy,
    ModelSelection,
    RunDemand,
)
from ai_software_engineer.scheduling.models import (
    ModelRejectionCode,
    ModelRoutingDecision,
    ModelRoutingDecisionStatus,
    ModelRoutingRefusal,
)

_TIER_ORDER: tuple[BrainTier, ...] = (
    BrainTier.ECONOMY,
    BrainTier.STANDARD,
    BrainTier.REASONING,
    BrainTier.CRITICAL,
)
_TIER_RANK = {tier: index for index, tier in enumerate(_TIER_ORDER)}


def _next_tier(tier: BrainTier) -> BrainTier:
    return _TIER_ORDER[min(_TIER_RANK[tier] + 1, len(_TIER_ORDER) - 1)]


def _route_name(provider: str, model: str) -> str:
    return f"{provider}/{model}"


@dataclass(frozen=True, slots=True)
class ModelRouter:
    """Select the least powerful policy route satisfying objective demand constraints.

    ``route_context_capacities`` is deliberately supplied by composition code rather than stored
    on an Agent or provider SDK object. A route without declared capacity can only serve an empty
    context; non-empty context demand fails closed instead of assuming an unlimited window.
    """

    route_context_capacities: Mapping[tuple[str, str], int] = field(default_factory=dict)
    complexity_file_threshold: int = 8
    complexity_layer_threshold: int = 3
    complexity_context_threshold: int = 32_000

    def __post_init__(self) -> None:
        if any(capacity < 0 for capacity in self.route_context_capacities.values()):
            raise ValueError("route context capacities cannot be negative")
        if self.complexity_file_threshold < 1:
            raise ValueError("complexity_file_threshold must be positive")
        if self.complexity_layer_threshold < 1:
            raise ValueError("complexity_layer_threshold must be positive")
        if self.complexity_context_threshold < 1:
            raise ValueError("complexity_context_threshold must be positive")
        object.__setattr__(
            self, "route_context_capacities", MappingProxyType(dict(self.route_context_capacities))
        )

    def route(
        self,
        demand: RunDemand,
        agent: AgentProfile,
        policy: ModelPolicy,
        *,
        now: datetime,
    ) -> ModelRoutingDecision:
        """Return a typed selection or refusal without calling any model provider."""
        self._require_aware(now)
        if not agent.active:
            return self._reject(
                demand,
                agent,
                now,
                ModelRoutingRefusal(
                    code=ModelRejectionCode.INACTIVE_AGENT,
                    message=f"Agent {agent.id} is inactive",
                ),
            )
        if demand.role not in agent.eligible_roles:
            return self._reject(
                demand,
                agent,
                now,
                ModelRoutingRefusal(
                    code=ModelRejectionCode.ROLE_NOT_ELIGIBLE,
                    message=f"Agent {agent.id} is not eligible for role {demand.role.value}",
                ),
            )
        missing = tuple(sorted(set(demand.required_capabilities) - set(agent.capabilities)))
        if missing:
            return self._reject(
                demand,
                agent,
                now,
                ModelRoutingRefusal(
                    code=ModelRejectionCode.CAPABILITY_MISMATCH,
                    message=f"Agent {agent.id} lacks required capabilities: {', '.join(missing)}",
                    missing_capabilities=missing,
                ),
            )
        if agent.default_model_policy_id != policy.id:
            return self._reject(
                demand,
                agent,
                now,
                ModelRoutingRefusal(
                    code=ModelRejectionCode.POLICY_MISMATCH,
                    message=(
                        f"Agent {agent.id} defaults to {agent.default_model_policy_id}, "
                        f"not policy {policy.id}"
                    ),
                ),
            )

        floors = {floor.risk: floor.minimum_tier for floor in policy.risk_floors}
        risk_floor = floors[demand.risk]
        complexity = self._is_complex(demand)
        objective_escalation = self._has_objective_escalation(demand)
        target = max(
            (_TIER_RANK[policy.default_tier], _TIER_RANK[risk_floor]),
            default=_TIER_RANK[BrainTier.ECONOMY],
        )
        target_tier = _TIER_ORDER[target]
        if complexity or objective_escalation:
            target_tier = _next_tier(target_tier)

        routes = tuple(
            sorted(
                policy.routes,
                key=lambda route: (_TIER_RANK[route.tier], route.provider, route.model),
            )
        )
        capacity_routes = tuple(
            route
            for route in routes
            if self._fits_context(route.provider, route.model, demand.context_tokens)
        )
        if not capacity_routes:
            return self._reject(
                demand,
                agent,
                now,
                ModelRoutingRefusal(
                    code=ModelRejectionCode.NO_CONTEXT_CAPACITY,
                    message=f"No policy route can hold {demand.context_tokens} context tokens",
                    required_tier=target_tier,
                    considered_routes=tuple(
                        _route_name(route.provider, route.model) for route in routes
                    ),
                ),
            )
        eligible = tuple(
            route for route in capacity_routes if _TIER_RANK[route.tier] >= _TIER_RANK[target_tier]
        )
        if not eligible:
            return self._reject(
                demand,
                agent,
                now,
                ModelRoutingRefusal(
                    code=ModelRejectionCode.NO_ELIGIBLE_ROUTE,
                    message=f"No route satisfies minimum BrainTier {target_tier.value}",
                    required_tier=target_tier,
                    considered_routes=tuple(
                        _route_name(route.provider, route.model) for route in capacity_routes
                    ),
                ),
            )

        selected = eligible[0]
        reasons: list[ModelRouteReason] = []
        if not complexity and not objective_escalation and selected.tier is policy.default_tier:
            reasons.append(ModelRouteReason.DEFAULT)
        if _TIER_RANK[risk_floor] >= _TIER_RANK[policy.default_tier]:
            reasons.append(ModelRouteReason.RISK_FLOOR)
        if complexity:
            reasons.append(ModelRouteReason.TASK_COMPLEXITY)
        if objective_escalation:
            reasons.append(ModelRouteReason.OBJECTIVE_ESCALATION)
        if len(capacity_routes) != len(routes):
            reasons.append(ModelRouteReason.CONTEXT_CAPACITY)
        if not reasons:
            reasons.append(ModelRouteReason.DEFAULT)
        selection = ModelSelection(
            policy_id=policy.id,
            policy_version=policy.version,
            provider=selected.provider,
            model=selected.model,
            tier=selected.tier,
            reasons=tuple(reasons),
            selected_at=now,
        )
        return ModelRoutingDecision(
            status=ModelRoutingDecisionStatus.SELECTED,
            task_id=demand.task_id,
            agent_id=agent.id,
            role=demand.role,
            selection=selection,
            decided_at=now,
        )

    def select(
        self,
        demand: RunDemand,
        agent: AgentProfile,
        policy: ModelPolicy,
        *,
        now: datetime,
    ) -> ModelSelection:
        """Convenience API returning only a selection; refusals raise a typed exception."""
        decision = self.route(demand, agent, policy, now=now)
        if decision.selection is None:
            assert decision.refusal is not None
            raise ModelRoutingRejected(decision.refusal)
        return decision.selection

    def _is_complex(self, demand: RunDemand) -> bool:
        return (
            demand.planned_files >= self.complexity_file_threshold
            or len(demand.affected_layers) >= self.complexity_layer_threshold
            or demand.context_tokens >= self.complexity_context_threshold
        )

    @staticmethod
    def _has_objective_escalation(demand: RunDemand) -> bool:
        return (
            demand.failed_runs > 0
            or demand.qa_failures > 0
            or demand.review_rejections > 0
            or demand.touches_critical_paths
        )

    def _fits_context(self, provider: str, model: str, context_tokens: int) -> bool:
        limit = self.route_context_capacities.get((provider, model))
        return context_tokens == 0 if limit is None else context_tokens <= limit

    @staticmethod
    def _require_aware(now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("model routing time must be timezone-aware")

    @staticmethod
    def _reject(
        demand: RunDemand,
        agent: AgentProfile,
        now: datetime,
        refusal: ModelRoutingRefusal,
    ) -> ModelRoutingDecision:
        return ModelRoutingDecision(
            status=ModelRoutingDecisionStatus.REJECTED,
            task_id=demand.task_id,
            agent_id=agent.id,
            role=demand.role,
            refusal=refusal,
            decided_at=now,
        )


class ModelRoutingRejected(ValueError):
    """Typed exception used by the selection-only convenience API."""

    def __init__(self, refusal: ModelRoutingRefusal) -> None:
        self.refusal = refusal
        super().__init__(refusal.message)


__all__ = ["ModelRouter", "ModelRoutingRejected"]
