"""Manager Leader incident recovery with explicit Skill/MCP authority.

The public interface is deliberately small: callers report one typed incident and
receive one auditable disposition.  Capability selection, retry budgets, and the
distinction between direct environment repair and repository-changing delivery
work remain inside this module.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Protocol, Self

from pydantic import Field, StrictBool, StringConstraints, field_validator, model_validator

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique

CapabilityId = Annotated[
    str,
    StringConstraints(pattern=r"^manager_capability_[a-z0-9][a-z0-9_-]{2,63}$"),
]
IncidentId = Annotated[
    str,
    StringConstraints(pattern=r"^manager_incident_[a-z0-9][a-z0-9_-]{2,95}$"),
]
RepairTaskId = Annotated[
    str,
    StringConstraints(pattern=r"^task_[a-z0-9][a-z0-9_-]{2,95}$"),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class ManagerIncidentKind(StrEnum):
    """Stable incident classes used for recovery policy."""

    ENVIRONMENT = "ENVIRONMENT"
    WORKFLOW = "WORKFLOW"
    PROVIDER = "PROVIDER"
    POLICY = "POLICY"
    PERMISSION = "PERMISSION"
    BUSINESS = "BUSINESS"


class ManagerCapabilityKind(StrEnum):
    """How an explicitly registered Manager capability is implemented."""

    BUILTIN = "BUILTIN"
    SKILL = "SKILL"
    MCP = "MCP"


class ManagerRepairMode(StrEnum):
    """Whether repair may run directly or must use normal delivery controls."""

    DIRECT = "DIRECT"
    CANDIDATE_DELIVERY = "CANDIDATE_DELIVERY"


class ManagerRepairDisposition(StrEnum):
    """Exclusive outcome returned to the Team Host."""

    RETRY_DELIVERY = "RETRY_DELIVERY"
    REPAIR_TASK_SUBMITTED = "REPAIR_TASK_SUBMITTED"
    WAITING_HUMAN = "WAITING_HUMAN"


class ManagerIncident(DomainModel):
    """Safe evidence supplied to the Manager Leader recovery interface."""

    id: IncidentId
    kind: ManagerIncidentKind
    summary: NonEmptyStr
    delivery_id: NonEmptyStr
    repository_root: NonEmptyStr
    recovery_attempt: int = Field(default=0, ge=0, le=100)

    @field_validator("repository_root")
    @classmethod
    def require_absolute_repository_root(cls, value: str) -> str:
        if not Path(value).is_absolute() or any(ord(character) < 32 for character in value):
            raise ValueError("repository_root must be absolute and contain no controls")
        return value


class ManagerRepairCapability(DomainModel):
    """One pre-approved built-in, Skill, or MCP repair capability."""

    id: CapabilityId
    kind: ManagerCapabilityKind
    incident_kinds: tuple[ManagerIncidentKind, ...]
    mode: ManagerRepairMode
    automatic: StrictBool = True
    max_attempts: int = Field(default=1, ge=1, le=5)
    can_expand_permissions: StrictBool = False
    destructive: StrictBool = False

    @model_validator(mode="after")
    def validate_automatic_authority(self) -> Self:
        ensure_unique(self.incident_kinds, "Manager repair incident kinds")
        if not self.incident_kinds:
            raise ValueError("Manager repair capability must handle at least one incident kind")
        if self.automatic and (self.can_expand_permissions or self.destructive):
            raise ValueError("automatic Manager repair cannot expand permissions or be destructive")
        if self.automatic and any(
            kind
            in {
                ManagerIncidentKind.POLICY,
                ManagerIncidentKind.PERMISSION,
                ManagerIncidentKind.BUSINESS,
            }
            for kind in self.incident_kinds
        ):
            raise ValueError("policy, permission, and business incidents require a human")
        return self


class ManagerRepairExecution(DomainModel):
    """Result returned by a direct environment/workflow repair adapter."""

    repaired: StrictBool
    summary: NonEmptyStr
    evidence_sha256: Sha256

    @classmethod
    def create(cls, *, repaired: bool, summary: str, evidence: str) -> Self:
        digest = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        return cls(repaired=repaired, summary=summary, evidence_sha256=digest)


class ManagerRepairSubmission(DomainModel):
    """Repository-changing repair submitted through Coder/QA/Reviewer."""

    task_id: RepairTaskId
    summary: NonEmptyStr


class ManagerRepairResult(DomainModel):
    """Auditable result of one Manager Leader recovery decision."""

    disposition: ManagerRepairDisposition
    summary: NonEmptyStr
    capability_id: CapabilityId | None = None
    evidence_sha256: Sha256 | None = None
    repair_task_id: RepairTaskId | None = None

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        if self.disposition is ManagerRepairDisposition.RETRY_DELIVERY:
            if self.capability_id is None or self.evidence_sha256 is None:
                raise ValueError("retry disposition requires capability and evidence")
            if self.repair_task_id is not None:
                raise ValueError("direct repair cannot also submit a repair Task")
        elif self.disposition is ManagerRepairDisposition.REPAIR_TASK_SUBMITTED:
            if self.capability_id is None or self.repair_task_id is None:
                raise ValueError("repair Task disposition requires capability and Task")
            if self.evidence_sha256 is not None:
                raise ValueError("repair Task submission has no direct execution evidence")
        elif any(
            value is not None
            for value in (self.capability_id, self.evidence_sha256, self.repair_task_id)
        ):
            raise ValueError("human wait cannot claim an executed repair")
        return self


class ManagerRepairExecutor(Protocol):
    """Adapter seam for a pre-approved built-in, Skill, or MCP capability."""

    def execute(self, incident: ManagerIncident) -> ManagerRepairExecution: ...


class ManagerRepairTaskSubmitter(Protocol):
    """Submit repository changes through the ordinary delivery pipeline."""

    def submit(
        self,
        incident: ManagerIncident,
        capability: ManagerRepairCapability,
    ) -> ManagerRepairSubmission: ...


class ManagerLeaderRecovery:
    """Select and execute one bounded Manager repair without unsafe authority growth."""

    def __init__(
        self,
        *,
        capabilities: tuple[ManagerRepairCapability, ...],
        executors: Mapping[CapabilityId, ManagerRepairExecutor],
        task_submitter: ManagerRepairTaskSubmitter,
    ) -> None:
        ensure_unique((capability.id for capability in capabilities), "Manager capability IDs")
        self._capabilities = capabilities
        self._executors = dict(executors)
        self._task_submitter = task_submitter
        for capability in capabilities:
            if capability.mode is ManagerRepairMode.DIRECT and capability.id not in self._executors:
                raise ValueError(f"direct Manager capability {capability.id} has no executor")

    def recover(self, incident: ManagerIncident) -> ManagerRepairResult:
        """Repair safe incidents or submit a normal repair Task; otherwise fail closed."""

        if incident.kind in {
            ManagerIncidentKind.POLICY,
            ManagerIncidentKind.PERMISSION,
            ManagerIncidentKind.BUSINESS,
        }:
            return self._waiting_human("incident requires a policy or business decision")
        capability = next(
            (
                candidate
                for candidate in self._capabilities
                if candidate.automatic and incident.kind in candidate.incident_kinds
            ),
            None,
        )
        if capability is None:
            return self._waiting_human("no pre-approved Manager repair capability is available")
        if incident.recovery_attempt >= capability.max_attempts:
            return self._waiting_human("Manager repair budget is exhausted")
        if capability.mode is ManagerRepairMode.CANDIDATE_DELIVERY:
            submission = self._task_submitter.submit(incident, capability)
            return ManagerRepairResult(
                disposition=ManagerRepairDisposition.REPAIR_TASK_SUBMITTED,
                capability_id=capability.id,
                repair_task_id=submission.task_id,
                summary=submission.summary,
            )
        execution = self._executors[capability.id].execute(incident)
        if not execution.repaired:
            return self._waiting_human(execution.summary)
        return ManagerRepairResult(
            disposition=ManagerRepairDisposition.RETRY_DELIVERY,
            capability_id=capability.id,
            evidence_sha256=execution.evidence_sha256,
            summary=execution.summary,
        )

    @staticmethod
    def _waiting_human(summary: str) -> ManagerRepairResult:
        return ManagerRepairResult(
            disposition=ManagerRepairDisposition.WAITING_HUMAN,
            summary=summary,
        )


__all__ = [
    "ManagerCapabilityKind",
    "ManagerIncident",
    "ManagerIncidentKind",
    "ManagerLeaderRecovery",
    "ManagerRepairCapability",
    "ManagerRepairDisposition",
    "ManagerRepairExecution",
    "ManagerRepairExecutor",
    "ManagerRepairMode",
    "ManagerRepairResult",
    "ManagerRepairSubmission",
    "ManagerRepairTaskSubmitter",
]
