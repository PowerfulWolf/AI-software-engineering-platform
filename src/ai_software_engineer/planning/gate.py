"""Pure Manager-owned planning complexity policy and immutable audit facts."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StrictInt

from ai_software_engineer.domain.enums import RiskTier
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import (
    DesignComplexityFacts,
    ProductSpec,
    StageSha256,
    TechnicalDesign,
)


class PlanningMode(StrEnum):
    SIMPLE = "SIMPLE"
    COMPLEX = "COMPLEX"


class PlanningFacts(DomainModel):
    product_spec_sha256: StageSha256
    technical_design_sha256: StageSha256
    repository_count: Annotated[StrictInt, Field(ge=1)]
    component_count: Annotated[StrictInt, Field(ge=1)]
    integration_group_count: Annotated[StrictInt, Field(ge=0)] = 0
    technical_risk: RiskTier = RiskTier.LOW
    design_facts: DesignComplexityFacts = DesignComplexityFacts()

    @classmethod
    def from_design(cls, product: ProductSpec, design: TechnicalDesign) -> PlanningFacts:
        product.validate_integrity()
        design.validate_integrity()
        facts = design.complexity_facts or DesignComplexityFacts()
        return cls(
            product_spec_sha256=product.product_spec_sha256,
            technical_design_sha256=design.technical_design_sha256,
            repository_count=1,
            component_count=len(design.components),
            integration_group_count=len(set(facts.integration_groups)),
            technical_risk=max(
                (risk.tier for risk in design.risks), key=risk_rank, default=RiskTier.LOW
            ),
            design_facts=facts,
        )

    def digest(self) -> str:
        return _digest(self.to_wire())


class HumanPlanningUpgrade(DomainModel):
    input_sha256: StageSha256
    operator_id: NonEmptyStr
    rationale: NonEmptyStr
    decided_at: AwareDatetime


class PlanningDecision(DomainModel):
    kind: Literal["planning_gate_decision"] = "planning_gate_decision"
    rules_version: Literal["planning-gate-v1"] = "planning-gate-v1"
    facts: PlanningFacts
    input_sha256: StageSha256
    mode: PlanningMode
    reason_codes: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    human_upgrade: HumanPlanningUpgrade | None = None
    decision_sha256: StageSha256

    def validate_integrity(self) -> None:
        expected = PlanningGate().classify(self.facts, upgrade=self.human_upgrade)
        if self != expected:
            raise ValueError("PlanningDecision does not match deterministic policy")


class PlanningGate:
    """No Agent, provider, I/O, or user-controlled downgrade seam."""

    def classify(
        self, facts: PlanningFacts, *, upgrade: HumanPlanningUpgrade | None = None
    ) -> PlanningDecision:
        reasons: list[str] = []
        if facts.repository_count > 1:
            reasons.append("MULTIPLE_REPOSITORIES")
        if facts.component_count > 1:
            reasons.append("MULTIPLE_MODULES")
        for name in (
            "database_migration",
            "interface_compatibility",
            "data_backfill",
            "security",
            "performance",
            "concurrency",
            "work_package_dependencies",
        ):
            if getattr(facts.design_facts, name):
                reasons.append(name.upper())
        if facts.integration_group_count > 1:
            reasons.append("MULTIPLE_INTEGRATION_GROUPS")
        if risk_rank(facts.technical_risk) >= risk_rank(RiskTier.NORMAL):
            reasons.append("TECHNICAL_RISK")
        if upgrade is not None:
            if upgrade.input_sha256 != facts.digest():
                raise ValueError("human planning upgrade must bind exact input")
            reasons.append("HUMAN_UPGRADE")
        provisional = PlanningDecision(
            facts=facts,
            input_sha256=facts.digest(),
            mode=PlanningMode.COMPLEX if reasons else PlanningMode.SIMPLE,
            reason_codes=tuple(reasons) or ("SIMPLE_CHANGE",),
            human_upgrade=upgrade,
            decision_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={
                "decision_sha256": _digest(
                    provisional.model_dump(
                        mode="json",
                        exclude={"decision_sha256"},
                        exclude_none=True,
                    )
                ),
            }
        )


def risk_rank(risk: RiskTier) -> int:
    return (RiskTier.LOW, RiskTier.NORMAL, RiskTier.HIGH, RiskTier.CRITICAL).index(risk)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()
