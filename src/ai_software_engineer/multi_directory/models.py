"""Typed joint artifacts; repository-level artifacts retain their native contracts."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Self

from pydantic import AwareDatetime, Field, model_validator

from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.execution import CommandResult
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryId,
    DeliveryStage,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.preparation import PrepareProjectResult
from ai_software_engineer.manager.production_agents import (
    ExecutionPlanDraft,
    ProductDraft,
    TechnicalDesignDraft,
)
from ai_software_engineer.multi_directory.scope import Digest, DirectoryScope, UnitId


def digest(model: DomainModel) -> str:
    return hashlib.sha256(
        json.dumps(
            model.to_wire(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


class JointStage(StrEnum):
    PREPARING = "PREPARING"
    READY_FOR_DISCUSSION = "READY_FOR_DISCUSSION"
    PRODUCT_DISCOVERY = "PRODUCT_DISCOVERY"
    WAITING_PRODUCT_REPLY = "WAITING_PRODUCT_REPLY"
    WAITING_PRODUCT_APPROVAL = "WAITING_PRODUCT_APPROVAL"
    DESIGNING = "DESIGNING"
    PLANNING = "PLANNING"
    DELIVERING = "DELIVERING"
    INTEGRATING = "INTEGRATING"
    DONE = "DONE"
    WAITING_HUMAN = "WAITING_HUMAN"
    BLOCKED = "BLOCKED"


class PreparedUnit(DomainModel):
    unit_id: UnitId
    result: PrepareProjectResult
    context_sources: tuple[ContextSource, ...] = ()
    commands: tuple[NonEmptyStr, ...] = ()


class DialogueMessage(DomainModel):
    speaker: str
    text: NonEmptyStr


class JointProductSpec(DomainModel):
    scope_sha256: Digest
    version: Annotated[int, Field(ge=1)]
    product: ProductDraft

    def acceptance_ids(self) -> tuple[str, ...]:
        """The authoritative global identifiers shared by context and validation."""
        return tuple(
            f"ac_{i:03d}_{j:03d}"
            for i, requirement in enumerate(self.product.requirements, 1)
            for j, _ in enumerate(requirement.acceptance, 1)
        )

    @model_validator(mode="after")
    def ready_only(self) -> Self:
        if self.product.action != "ready":
            raise ValueError("a ProductSpec must be ready for human review")
        return self


class JointApproval(DomainModel):
    product_spec_sha256: Digest
    checkpoint_sha256: Digest
    reference: NonEmptyStr
    approved_at: AwareDatetime


class UnitDesign(DomainModel):
    unit_id: UnitId
    requirement_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    design: TechnicalDesignDraft


class InterfaceContract(DomainModel):
    id: NonEmptyStr
    producer: UnitId
    consumers: Annotated[tuple[UnitId, ...], Field(min_length=1)]
    specification: NonEmptyStr
    compatibility: NonEmptyStr


class DesignInterfaceConsumersError(ValueError):
    """Safe duplicate-consumer diagnostic; never echo model-authored prose."""

    def __init__(self, *, interface_index: int) -> None:
        super().__init__(f"interface consumers must be unique; interface index: {interface_index}")


class DesignWritePathsError(ValueError):
    """Locate rejected write proposals without echoing untrusted paths."""

    def __init__(self, *, unit_index: int, component_index: int, path_index: int) -> None:
        super().__init__(
            "design write paths exceed the selected directories; "
            f"unit index: {unit_index}; component index: {component_index}; "
            f"path index: {path_index}. Use canonical repository-relative paths within "
            "selected_paths; no absolute paths, dot segments, backslashes, control "
            "characters, .git segments or trailing slashes"
        )


class JointTechnicalDesign(DomainModel):
    product_spec_sha256: Digest
    summary: NonEmptyStr
    units: Annotated[tuple[UnitDesign, ...], Field(min_length=1)]
    reference_only: tuple[UnitId, ...] = ()
    interfaces: tuple[InterfaceContract, ...] = ()

    def validate_for(self, scope: DirectoryScope, product: JointProductSpec) -> None:
        if self.product_spec_sha256 != digest(product):
            raise ValueError("joint design does not bind the approved ProductSpec")
        ensure_unique((u.unit_id for u in self.units), "design units")
        ensure_unique(self.reference_only, "reference units")
        ensure_unique((i.id for i in self.interfaces), "interface IDs")
        known = {u.id: u for u in scope.units}
        modified = {u.unit_id for u in self.units}
        if modified & set(self.reference_only) or modified | set(self.reference_only) != set(known):
            raise ValueError("design must classify every input unit exactly once")
        expected = {f"req_{i:03d}": r for i, r in enumerate(product.product.requirements, 1)}
        covered: set[str] = set()
        for unit_index, item in enumerate(self.units, 1):
            ensure_unique(item.requirement_ids, "unit requirement IDs")
            ensure_unique(
                (m.requirement_id for m in item.design.requirement_mappings), "requirement mappings"
            )
            ensure_unique(
                (m.acceptance_criterion_id for m in item.design.acceptance_mappings),
                "acceptance mappings",
            )
            ensure_unique((s.key for s in item.design.implementation_steps), "implementation steps")
            if not set(item.requirement_ids) <= set(expected):
                raise ValueError("design introduces an unapproved requirement")
            covered.update(item.requirement_ids)
            if set(m.requirement_id for m in item.design.requirement_mappings) != set(
                item.requirement_ids
            ):
                raise ValueError("unit design requirement coverage differs")
            criteria = {
                f"ac_{rid.removeprefix('req_')}_{i:03d}"
                for rid in item.requirement_ids
                for i, _ in enumerate(expected[rid].acceptance, 1)
            }
            if set(m.acceptance_criterion_id for m in item.design.acceptance_mappings) != criteria:
                raise ValueError("unit design acceptance coverage differs")
            ensure_unique((c.key for c in item.design.components), "component keys")
            keys = {c.key for c in item.design.components}
            component_groups = [m.component_keys for m in item.design.requirement_mappings]
            component_groups.extend(
                step.component_keys for step in item.design.implementation_steps
            )
            for component_keys in component_groups:
                if not set(component_keys) <= keys:
                    raise ValueError("design references an unknown component")
            for component_index, component in enumerate(item.design.components, 1):
                for path_index, path in enumerate(component.affected_paths, 1):
                    if not known[item.unit_id].permits(path):
                        raise DesignWritePathsError(
                            unit_index=unit_index,
                            component_index=component_index,
                            path_index=path_index,
                        )
        if covered != set(expected):
            raise ValueError("joint design does not cover the approved product")
        for index, interface in enumerate(self.interfaces, 1):
            if interface.producer not in known or not set(interface.consumers) <= set(known):
                raise ValueError("interface references a directory outside this request")
            if len(set(interface.consumers)) != len(interface.consumers):
                raise DesignInterfaceConsumersError(interface_index=index)


class UnitPlan(DomainModel):
    unit_id: UnitId
    depends_on: tuple[UnitId, ...] = ()
    plan: ExecutionPlanDraft


class IntegrationCheck(DomainModel):
    id: NonEmptyStr
    unit_id: UnitId
    consumes: Annotated[tuple[UnitId, ...], Field(min_length=1)]
    acceptance_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    interface_ids: tuple[NonEmptyStr, ...] = ()
    argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    timeout_seconds: Annotated[int, Field(ge=1, le=600)] = 120


class PlanCoverageError(ValueError):
    """Only trusted expected IDs, never model prose or provider errors, form feedback."""

    def __init__(self, *, missing_acceptance: set[str], missing_units: set[str]) -> None:
        super().__init__(
            "integration checks must cover all acceptance criteria and write units; "
            f"missing acceptance IDs: {', '.join(sorted(missing_acceptance)) or 'none'}; "
            f"missing write unit IDs: {', '.join(sorted(missing_units)) or 'none'}"
        )


class IntegrationCommandError(ValueError):
    """Safe preflight feedback without echoing untrusted argv or check names."""

    def __init__(self, *, check_index: int, argv: tuple[str, ...]) -> None:
        command_sha = hashlib.sha256(json.dumps(argv, separators=(",", ":")).encode()).hexdigest()
        super().__init__(
            "integration requires a supported test command, not inspection/install/inline code; "
            f"check index: {check_index}; argv sha256: {command_sha}. "
            "Use integration_command_policy intersected with prepared project commands"
        )


class JointExecutionPlan(DomainModel):
    design_sha256: Digest
    units: Annotated[tuple[UnitPlan, ...], Field(min_length=1)]
    integration_checks: Annotated[tuple[IntegrationCheck, ...], Field(min_length=1)]

    def validate_for(
        self, scope: DirectoryScope, product: JointProductSpec, design: JointTechnicalDesign
    ) -> None:
        if self.design_sha256 != digest(design):
            raise ValueError("joint plan is not bound to the technical design")
        ensure_unique((u.unit_id for u in self.units), "plan unit IDs")
        ensure_unique((c.id for c in self.integration_checks), "integration check IDs")
        modified = {u.unit_id for u in design.units}
        if {u.unit_id for u in self.units} != modified:
            raise ValueError("plan must execute every write unit exactly once")
        completed = set(design.reference_only)
        for unit in self.units:
            ensure_unique(unit.depends_on, "unit dependencies")
            if not set(unit.depends_on) <= completed:
                raise ValueError("dependency must precede its consumer in the serial plan")
            completed.add(unit.unit_id)
        known = {u.id for u in scope.units}
        expected = set(product.acceptance_ids())
        covered: set[str] = set()
        consumed: set[str] = set()
        interfaces: set[str] = set()
        for check in self.integration_checks:
            if check.unit_id not in known or not set(check.consumes) <= known:
                raise ValueError("integration check references an unknown directory")
            if check.unit_id not in check.consumes or not set(check.acceptance_ids) <= expected:
                raise ValueError("integration check has invalid acceptance/consumer scope")
            covered.update(check.acceptance_ids)
            consumed.update(check.consumes)
            interfaces.update(check.interface_ids)
        if covered != expected or not modified <= consumed:
            raise PlanCoverageError(
                missing_acceptance=expected - covered, missing_units=modified - consumed
            )
        if interfaces != {i.id for i in design.interfaces}:
            raise ValueError("integration checks must cover the shared interfaces")


class ChildDelivery(DomainModel):
    unit_id: UnitId
    checkpoint: ProjectDeliveryCheckpoint


class Candidate(DomainModel):
    unit_id: UnitId
    revision: NonEmptyStr


class IntegrationEvidence(DomainModel):
    plan_sha256: Digest
    candidates: tuple[Candidate, ...]
    checks: tuple[CommandResult, ...]


class JointCheckpoint(DomainModel):
    delivery_id: DeliveryId
    team_id: TeamId
    team_manifest_sha256: Digest
    project_id: ProjectId
    project_manifest_sha256: Digest
    sequence: Annotated[int, Field(ge=1)]
    previous_checkpoint_sha256: Digest | None = None
    stage: JointStage
    scope: DirectoryScope
    title: NonEmptyStr
    requirement: NonEmptyStr | None = None
    submitted_at: AwareDatetime
    preparations: tuple[PreparedUnit, ...] = ()
    dialogue: tuple[DialogueMessage, ...] = ()
    product_spec: JointProductSpec | None = None
    approval: JointApproval | None = None
    design: JointTechnicalDesign | None = None
    plan: JointExecutionPlan | None = None
    children: tuple[ChildDelivery, ...] = ()
    integration: IntegrationEvidence | None = None
    attempts: dict[str, int] = Field(default_factory=dict)
    next_action: NonEmptyStr
    checkpoint_sha256: Digest

    @model_validator(mode="after")
    def validate_chain(self) -> Self:
        if (self.sequence == 1) != (self.previous_checkpoint_sha256 is None):
            raise ValueError("joint checkpoint sequence/parent mismatch")
        ensure_unique((p.unit_id for p in self.preparations), "prepared units")
        ensure_unique((c.unit_id for c in self.children), "child units")
        if self.product_spec is not None and self.product_spec.scope_sha256 != digest(self.scope):
            raise ValueError("ProductSpec scope drift")
        if self.approval is not None and (
            self.product_spec is None
            or self.approval.product_spec_sha256 != digest(self.product_spec)
        ):
            raise ValueError("human approval ProductSpec drift")
        if self.design is not None:
            if self.approval is None or self.product_spec is None:
                raise ValueError("joint design requires exact human approval")
            self.design.validate_for(self.scope, self.product_spec)
        if self.plan is not None:
            if self.design is None or self.product_spec is None:
                raise ValueError("joint planning requires a technical design")
            self.plan.validate_for(self.scope, self.product_spec, self.design)
        if self.stage is JointStage.DONE:
            if self.plan is None or self.integration is None:
                raise ValueError("joint DONE requires integration evidence")
            if {c.unit_id for c in self.children} != {u.unit_id for u in self.plan.units}:
                raise ValueError("partial repository success is not joint DONE")
            if any(c.checkpoint.stage != DeliveryStage.DONE for c in self.children):
                raise ValueError("every child must have completed independent QA and Review")
            expected_candidates = tuple(
                Candidate(
                    unit_id=u.id,
                    revision=next(
                        (
                            c.checkpoint.candidate_revision
                            for c in self.children
                            if c.unit_id == u.id
                        ),
                        u.base_revision,
                    )
                    or "missing",
                )
                for u in self.scope.units
            )
            if self.integration.candidates != expected_candidates:
                raise ValueError("integration evidence refers to a different candidate set")
            if self.integration.plan_sha256 != digest(self.plan):
                raise ValueError("integration evidence plan mismatch")
            if len(self.integration.checks) != len(self.plan.integration_checks):
                raise ValueError("missing integration command evidence")
            for result, check in zip(
                self.integration.checks, self.plan.integration_checks, strict=True
            ):
                if result.argv != check.argv or result.returncode != 0:
                    raise ValueError("integration command did not pass")
        return self

    def validate_integrity(self) -> None:
        payload = self.model_dump(mode="json", exclude={"checkpoint_sha256"}, exclude_none=True)
        actual = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if actual != self.checkpoint_sha256:
            raise ValueError("joint checkpoint digest mismatch")

    @classmethod
    def seal(cls, values: dict[str, object]) -> JointCheckpoint:
        provisional = cls.model_validate({**values, "checkpoint_sha256": "0" * 64})
        payload = provisional.model_dump(
            mode="json", exclude={"checkpoint_sha256"}, exclude_none=True
        )
        sha = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return provisional.model_copy(update={"checkpoint_sha256": sha})


class JointDeliveryResult(DomainModel):
    checkpoint: JointCheckpoint
