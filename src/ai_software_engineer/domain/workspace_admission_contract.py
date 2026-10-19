"""Current engineering testimony about one historical adapter deployment.

This is supplied evidence, never an original native invocation or stop receipt.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from ai_software_engineer.domain.engineering_authority import (
    EngineeringScope,
    EngineeringSha256,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.model import DomainModel, ensure_unique

type ContractIdentity = Annotated[str, StringConstraints(min_length=1, max_length=200)]
type PlatformRevision = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40}$")]


class WorkspaceAdmissionAdapterSource(DomainModel):
    path: Annotated[str, StringConstraints(pattern=r"^src/ai_software_engineer/[a-z_/]+\.py$")]
    sha256: EngineeringSha256


class WorkspaceAdmissionAdapterContract(DomainModel):
    """Operator input; principal and time come only from trusted composition."""

    kind: Literal["historical_workspace_admission_deployment"] = (
        "historical_workspace_admission_deployment"
    )
    scope: EngineeringScope
    requirement_id: ContractIdentity
    task_id: ContractIdentity
    work_item_id: ContractIdentity
    lease_id: ContractIdentity
    claim_sha256: EngineeringSha256
    run_id: ContractIdentity
    source_revision: PlatformRevision
    invocation_start_sha256: EngineeringSha256
    invocation_outcome_sha256: EngineeringSha256
    route_attempt_sha256: EngineeringSha256
    platform_revision: PlatformRevision
    adapter_sources: Annotated[
        tuple[WorkspaceAdmissionAdapterSource, ...], Field(min_length=7, max_length=7)
    ]
    deployment_evidence_id: ContractIdentity
    deployment_evidence_sha256: EngineeringSha256
    service_instance_id: ContractIdentity
    service_process_birth: ContractIdentity
    deployment_observed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        paths = tuple(source.path for source in self.adapter_sources)
        ensure_unique(paths, "adapter source paths")
        if paths != tuple(sorted(paths)):
            raise ValueError("adapter source manifest must be sorted")
        return self


class WorkspaceAdmissionAdapterContractRecord(DomainModel):
    kind: Literal["workspace_admission_deployment_declaration"] = (
        "workspace_admission_deployment_declaration"
    )
    schema_version: Literal["v1"] = "v1"
    declaration: WorkspaceAdmissionAdapterContract
    operator_principal: LocalOperatorPrincipal
    submitted_at: AwareDatetime
    attribution: Literal["current_operator_supplied_historical_deployment_evidence"] = (
        "current_operator_supplied_historical_deployment_evidence"
    )
    contract_sha256: EngineeringSha256

    @model_validator(mode="after")
    def validate_operator(self) -> Self:
        self.operator_principal.require_duty(OperatorDuty.ENGINEERING)
        if self.submitted_at < self.declaration.deployment_observed_at:
            raise ValueError("deployment testimony predates its observation")
        return self

    def recompute_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json", exclude={"contract_sha256"}),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.contract_sha256 != self.recompute_sha256():
            raise ValueError("workspace adapter deployment testimony integrity mismatch")

    @classmethod
    def create(cls, **values: object) -> Self:
        record = cls.model_validate({**values, "contract_sha256": "0" * 64})
        return record.model_copy(update={"contract_sha256": record.recompute_sha256()})
