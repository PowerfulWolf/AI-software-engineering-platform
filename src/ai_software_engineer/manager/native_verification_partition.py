"""Lossless prerequisite diagnostics, never an executor registration or verdict."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import model_validator

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.execution_window import PlannedVerificationRequirement
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.native_verification import (
    NativeVerificationCapabilityDetail,
    NativeVerificationWaiting,
    NativeVerificationWaitReason,
    role_verification_digest,
)
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightScope,
    DiscoveredControlledCapability,
    Sha256,
)
from ai_software_engineer.manager.python_verification import PytestSelection
from ai_software_engineer.manager.python_verification_runner import MAX_PYTEST_SELECTIONS

PYTHON_MYSQL_CAPABILITY_KIND = "codex_sandbox_pytest_mysql_v1"
_PYTHON_CAPABILITY = PYTHON_MYSQL_CAPABILITY_KIND
VerifierRole = Literal[AgentRole.QA, AgentRole.REVIEWER]


class NativeEntrypointDiagnosticHint(DomainModel):
    """Code-owned exact semantics hint. It cannot grant capability or readiness."""

    argv: tuple[NonEmptyStr, ...]
    verification_levels: tuple[NonEmptyStr, ...] | None
    detail: Literal[
        NativeVerificationCapabilityDetail.BROWSER_EXECUTOR_UNREGISTERED,
        NativeVerificationCapabilityDetail.LIVE_EXECUTOR_UNREGISTERED,
        NativeVerificationCapabilityDetail.REQUIREMENT_EXECUTOR_UNREGISTERED,
    ]
    hint_sha256: Sha256

    @classmethod
    def create(
        cls,
        *,
        argv: tuple[str, ...],
        verification_levels: tuple[str, ...] | None,
        detail: NativeVerificationCapabilityDetail,
    ) -> NativeEntrypointDiagnosticHint:
        return cls.model_validate(
            {
                "argv": argv,
                "verification_levels": verification_levels,
                "detail": detail,
                "hint_sha256": role_verification_digest(
                    {"argv": argv, "verification_levels": verification_levels, "detail": detail}
                ),
            }
        )

    def validate_integrity(self) -> None:
        if not self.argv or self.hint_sha256 != role_verification_digest(
            self.model_dump(mode="json", exclude={"hint_sha256"})
        ):
            raise ValueError("diagnostic hint changed")


class NativeRequirementPrerequisite(DomainModel):
    effective_role: VerifierRole
    requirement_id: NonEmptyStr
    requirement_sha256: Sha256
    argv_sha256: Sha256
    criterion_ids_sha256: Sha256
    verification_levels_sha256: Sha256
    reason: NativeVerificationWaitReason
    detail: NativeVerificationCapabilityDetail | None = None

    @model_validator(mode="after")
    def validate_detail(self) -> NativeRequirementPrerequisite:
        if (
            self.detail is not None
            and self.reason is not NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE
        ):
            raise ValueError("capability detail requires unavailable prerequisite")
        return self

    @classmethod
    def for_requirement(
        cls,
        requirement: PlannedVerificationRequirement,
        *,
        effective_role: VerifierRole,
        reason: NativeVerificationWaitReason,
        detail: NativeVerificationCapabilityDetail | None = None,
    ) -> NativeRequirementPrerequisite:
        return cls(
            effective_role=effective_role,
            requirement_id=requirement.id,
            requirement_sha256=role_verification_digest(requirement.to_wire()),
            argv_sha256=role_verification_digest(requirement.argv),
            criterion_ids_sha256=role_verification_digest(requirement.criterion_ids),
            verification_levels_sha256=role_verification_digest(requirement.verification_levels),
            reason=reason,
            detail=detail,
        )

    def validate_requirement(
        self, requirement: PlannedVerificationRequirement, *, effective_role: VerifierRole
    ) -> None:
        expected = self.for_requirement(
            requirement, effective_role=effective_role, reason=self.reason, detail=self.detail
        )
        if self != expected:
            raise ValueError("prerequisite original requirement identity changed")


class NativeVerificationRequirementPartition(DomainModel):
    effective_role: VerifierRole
    requirements: tuple[PlannedVerificationRequirement, ...]
    requirements_sha256: Sha256
    python_v1_requirements: tuple[PlannedVerificationRequirement, ...]
    inspection_requirements: tuple[PlannedVerificationRequirement, ...]
    unavailable_requirements: tuple[NativeRequirementPrerequisite, ...]

    def validate_integrity(self) -> None:
        ensure_unique((item.id for item in self.requirements), "partition requirement IDs")
        if self.requirements_sha256 != role_verification_digest(
            [item.to_wire() for item in self.requirements]
        ):
            raise ValueError("partition original requirement group changed")
        originals = {item.id: item for item in self.requirements}
        members = [
            item.id for item in (*self.python_v1_requirements, *self.inspection_requirements)
        ]
        members.extend(item.requirement_id for item in self.unavailable_requirements)
        ensure_unique(members, "partition members")
        if set(members) != set(originals):
            raise ValueError("partition must retain every original requirement")
        for item in (*self.python_v1_requirements, *self.inspection_requirements):
            if originals.get(item.id) != item:
                raise ValueError("partition original requirement identity changed")
        for fact in self.unavailable_requirements:
            fact.validate_requirement(
                originals[fact.requirement_id], effective_role=self.effective_role
            )


class NativeVerificationPartitionDiscovery(DomainModel):
    scope: DeliveryPreflightScope
    task_id: NonEmptyStr
    source_revision: NonEmptyStr
    plan_sha256: Sha256
    policy_sha256: Sha256 | None
    requirements_sha256: Sha256
    partitions: tuple[NativeVerificationRequirementPartition, ...]
    capabilities: tuple[DiscoveredControlledCapability, ...]
    prerequisites: tuple[NativeRequirementPrerequisite, ...]

    def original_prerequisites(
        self, requirements: tuple[PlannedVerificationRequirement, ...]
    ) -> tuple[NativeRequirementPrerequisite, ...]:
        """Old preflight has original row IDs only; never flatten Reviewer fallback."""
        if self.requirements_sha256 != role_verification_digest(
            [item.to_wire() for item in requirements]
        ):
            raise ValueError("discovery original requirement group changed")
        ensure_unique(
            (group.effective_role for group in self.partitions), "discovery effective roles"
        )
        if {group.effective_role for group in self.partitions} != {
            AgentRole.QA,
            AgentRole.REVIEWER,
        }:
            raise ValueError("discovery effective roles changed")
        rows_by_role = {}
        for group in self.partitions:
            group.validate_integrity()
            direct = tuple(item for item in requirements if item.role is group.effective_role)
            expected = (
                direct
                if direct
                else tuple(item for item in requirements if item.role is AgentRole.QA)
            )
            if group.requirements != expected:
                raise ValueError("discovery effective role requirement identity changed")
            rows_by_role[group.effective_role] = {item.id: item for item in group.requirements}
        for fact in self.prerequisites:
            original = rows_by_role.get(fact.effective_role, {}).get(fact.requirement_id)
            if original is None or (
                original.inspection is not None
                and original.inspection.kind in {"source", "document"}
            ):
                raise ValueError("foreign discovery prerequisite identity")
            fact.validate_requirement(original, effective_role=fact.effective_role)
            if any(
                capability.role is fact.effective_role
                and fact.requirement_id in capability.requirement_ids
                for capability in self.capabilities
            ):
                raise ValueError("contradictory discovery prerequisite identity")
        indexed = {(item.effective_role, item.requirement_id): item for item in self.prerequisites}
        if len(indexed) != len(self.prerequisites):
            raise ValueError("duplicate discovery prerequisites")
        ensure_unique(
            ((item.kind, item.role) for item in self.capabilities), "discovery capabilities"
        )
        for group in self.partitions:
            for missing in group.unavailable_requirements:
                if indexed.get((group.effective_role, missing.requirement_id)) != missing:
                    raise ValueError("discovery omitted or changed a partition prerequisite")
            python_ids = {item.id for item in group.python_v1_requirements}
            role_capabilities = tuple(
                item for item in self.capabilities if item.role is group.effective_role
            )
            for capability in role_capabilities:
                if (
                    capability.kind != PYTHON_MYSQL_CAPABILITY_KIND
                    or capability.source_revision != self.source_revision
                    or set(capability.requirement_ids) != python_ids
                ):
                    raise ValueError("discovery capability requirement identity changed")
            if not role_capabilities and any(
                (group.effective_role, item.id) not in indexed
                for item in group.python_v1_requirements
            ):
                raise ValueError("discovery omitted a Python prerequisite")
        selected = []
        for requirement in requirements:
            item = indexed.get((requirement.role, requirement.id))
            if item is not None:
                item.validate_requirement(requirement, effective_role=requirement.role)
                selected.append(item)
        return tuple(selected)


def exact_python_selections(
    requirements: tuple[PlannedVerificationRequirement, ...],
) -> tuple[PytestSelection, ...]:
    nodes: dict[str, set[str]] = {}
    for requirement in requirements:
        if requirement.inspection is not None:
            if requirement.inspection.kind == "native_ui":
                raise NativeVerificationWaiting(NativeVerificationWaitReason.NATIVE_UI_PREREQUISITE)
            continue
        argv = requirement.argv
        assert argv is not None
        normalized = (Path(argv[0]).name, *argv[1:])
        if normalized[0] == "swift":
            reason = (
                NativeVerificationWaitReason.UNSUPPORTED_SWIFT_FILTER
                if "--filter" in normalized
                else NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT
            )
            raise NativeVerificationWaiting(reason)
        # Older immutable Plans predate the explicit capability field.  A
        # precise Python pytest argv is enough to derive the same registered
        # capability for compatibility; new Plans are rejected earlier by the
        # Planning feasibility gate unless they declare it explicitly.
        if requirement.controlled_capability_kind not in {None, _PYTHON_CAPABILITY}:
            raise NativeVerificationWaiting(NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT)
        if normalized[:3] in (
            ("python", "-m", "pytest"),
            ("python3", "-m", "pytest"),
        ) or normalized[:3] == ("uv", "run", "pytest"):
            arguments = normalized[3:]
        elif normalized[0] == "pytest":
            arguments = normalized[1:]
        else:
            raise NativeVerificationWaiting(NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT)
        selected = tuple(value for value in arguments if value not in {"-q", "--disable-warnings"})
        if not selected:
            raise NativeVerificationWaiting(NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT)
        for node in selected:
            try:
                selection = PytestSelection(node_id=node, criterion_ids=requirement.criterion_ids)
            except ValueError:
                raise NativeVerificationWaiting(
                    NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT
                ) from None
            nodes.setdefault(selection.node_id, set()).update(selection.criterion_ids)
    if len(nodes) > MAX_PYTEST_SELECTIONS:
        raise NativeVerificationWaiting(NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT)
    return tuple(
        PytestSelection(node_id=node, criterion_ids=tuple(sorted(criteria)))
        for node, criteria in nodes.items()
    )


def validate_verification_requirement_scope(
    requirements: tuple[PlannedVerificationRequirement, ...],
    *,
    effective_role: VerifierRole,
    criterion_ids: tuple[str, ...],
) -> None:
    """Validate the original complete scope before choosing either execution mode."""
    ensure_unique((item.id for item in requirements), "verification requirement IDs")
    expected = set(criterion_ids)
    covered = {criterion for item in requirements for criterion in item.criterion_ids}
    roles = {item.role for item in requirements}
    if (
        effective_role not in (AgentRole.QA, AgentRole.REVIEWER)
        or roles
        not in (
            {effective_role},
            {AgentRole.QA} if effective_role is AgentRole.REVIEWER else {effective_role},
        )
        or covered != expected
    ):
        raise ValueError("verification requirement role or acceptance scope changed")
    for item in requirements:
        PlannedVerificationRequirement.model_validate(item.to_wire())


def partition_verification_requirements(
    requirements: tuple[PlannedVerificationRequirement, ...],
    *,
    effective_role: VerifierRole,
    criterion_ids: tuple[str, ...],
    hints: tuple[NativeEntrypointDiagnosticHint, ...] = (),
) -> NativeVerificationRequirementPartition:
    """Classify complete original rows without guessing e2e semantics or probing a host."""
    validate_verification_requirement_scope(
        requirements, effective_role=effective_role, criterion_ids=criterion_ids
    )
    for hint in hints:
        hint.validate_integrity()
    ensure_unique(((hint.argv, hint.verification_levels) for hint in hints), "diagnostic hints")
    python_rows = []
    inspections = []
    unavailable = []
    for item in requirements:
        if item.inspection is not None and item.inspection.kind in {"source", "document"}:
            inspections.append(item)
            continue
        detail: NativeVerificationCapabilityDetail | None = next(
            (
                hint.detail
                for hint in hints
                if hint.argv == item.argv and hint.verification_levels == item.verification_levels
            ),
            NativeVerificationCapabilityDetail.REQUIREMENT_EXECUTOR_UNREGISTERED,
        )
        reason = NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE
        if item.inspection is not None:
            reason, detail = NativeVerificationWaitReason.NATIVE_UI_PREREQUISITE, None
        elif item.argv is not None and Path(item.argv[0]).name == "swift":
            reason = (
                NativeVerificationWaitReason.UNSUPPORTED_SWIFT_FILTER
                if "--filter" in item.argv
                else NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT
            )
            detail = None
        elif item.controlled_capability_kind in {None, PYTHON_MYSQL_CAPABILITY_KIND} and not (
            item.controlled_capability_kind is None
            and any(
                level.casefold() in {"e2e", "acceptance"}
                for level in item.verification_levels or ()
            )
        ):
            try:
                selections = exact_python_selections((item,))
            except NativeVerificationWaiting as error:
                # A precise registered Python request with unsupported flags/selectors
                # keeps its old reason; unrelated commands remain unregistered.
                if item.controlled_capability_kind == PYTHON_MYSQL_CAPABILITY_KIND:
                    reason, detail = error.reason, error.detail_code
            else:
                if selections:
                    python_rows.append(item)
                    continue
        unavailable.append(
            NativeRequirementPrerequisite.for_requirement(
                item, effective_role=effective_role, reason=reason, detail=detail
            )
        )
    # Preserve the exact v1 global bound. In a mixed group, retain every
    # independently known prerequisite even when its Python subset exceeds it.
    if python_rows:
        try:
            exact_python_selections(tuple(python_rows))
        except NativeVerificationWaiting as error:
            if not unavailable:
                raise
            unavailable.extend(
                NativeRequirementPrerequisite.for_requirement(
                    item,
                    effective_role=effective_role,
                    reason=error.reason,
                    detail=error.detail_code,
                )
                for item in python_rows
            )
            python_rows = []
    partition = NativeVerificationRequirementPartition(
        effective_role=effective_role,
        requirements=requirements,
        requirements_sha256=role_verification_digest([item.to_wire() for item in requirements]),
        python_v1_requirements=tuple(python_rows),
        inspection_requirements=tuple(inspections),
        unavailable_requirements=tuple(unavailable),
    )
    partition.validate_integrity()
    return partition
