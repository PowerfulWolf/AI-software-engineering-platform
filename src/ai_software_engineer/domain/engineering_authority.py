"""Frozen engineering authority and exact machine admissions, never human verdicts."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique

EngineeringSha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


def _digest(value: DomainModel) -> str:
    return hashlib.sha256(
        json.dumps(
            value.to_wire(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class OperatorDuty(StrEnum):
    PRODUCT = "PRODUCT"
    ENGINEERING = "ENGINEERING"


class LocalOperatorPrincipal(DomainModel):
    """Trusted local composition identity; request/model text cannot add duties."""

    kind: Literal["trusted_local_operator"] = "trusted_local_operator"
    operator_id: NonEmptyStr
    duties: Annotated[tuple[OperatorDuty, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_duties(self) -> Self:
        ensure_unique(self.duties, "operator duties")
        return self

    def require_duty(self, duty: OperatorDuty) -> None:
        if duty not in self.duties:
            raise ValueError(f"当前本机操作主体没有 {duty.value} 职责权限")

    @classmethod
    def trusted_local(cls) -> Self:
        """Installed local Console has both duties; adapters can restrict either duty."""
        return cls(
            operator_id="operator:local-console",
            duties=(OperatorDuty.PRODUCT, OperatorDuty.ENGINEERING),
        )


class EngineeringCapability(StrEnum):
    VERIFICATION_REFRESH = "verification_refresh"
    SWIFT_SANDBOX = "swift_sandbox"
    PYTHON_MYSQL_SANDBOX = "python_mysql_sandbox"
    NATIVE_UI_SANDBOX = "native_ui_sandbox"
    IN_SCOPE_PREREQUISITE_REPAIR = "in_scope_prerequisite_repair"
    PRE_EXECUTION_REBIND = "pre_execution_rebind"
    EXECUTION_BASELINE_REBIND = "execution_baseline_rebind"
    OWNED_MYSQL_CLEANUP = "owned_mysql_cleanup"


class EngineeringScope(DomainModel):
    team_id: NonEmptyStr
    project_id: NonEmptyStr
    repository_id: NonEmptyStr
    repository_root: NonEmptyStr

    @model_validator(mode="after")
    def absolute_repository(self) -> Self:
        root = Path(self.repository_root)
        if (
            not root.is_absolute()
            or ".." in root.parts
            or any(ord(character) < 32 for character in self.repository_root)
        ):
            raise ValueError("engineering repository root must be an absolute canonical path")
        return self


class EngineeringGrant(DomainModel):
    capability: EngineeringCapability
    max_admissions: Annotated[StrictInt, Field(ge=1, le=20)]


class EngineeringPolicy(DomainModel):
    """Versioned organization decision frozen only on newly admitted Tasks."""

    kind: Literal["engineering_policy"] = "engineering_policy"
    schema_version: Literal["v1"] = "v1"
    policy_id: NonEmptyStr = "local-bounded-engineering-v1"
    policy_version: Annotated[StrictInt, Field(ge=1)] = 1
    authorization_source: Literal["organization_engineering_policy"] = (
        "organization_engineering_policy"
    )
    scope: EngineeringScope
    issued_by: LocalOperatorPrincipal
    grants: Annotated[tuple[EngineeringGrant, ...], Field(min_length=1)]
    max_total_admissions: Annotated[StrictInt, Field(ge=1, le=100)] = 12

    @model_validator(mode="after")
    def validate_issuer_and_grants(self) -> Self:
        self.issued_by.require_duty(OperatorDuty.ENGINEERING)
        ensure_unique((grant.capability for grant in self.grants), "engineering capabilities")
        return self

    @property
    def policy_sha256(self) -> str:
        return _digest(self)

    def allowance(self, capability: EngineeringCapability) -> int:
        return next(
            (grant.max_admissions for grant in self.grants if grant.capability is capability), 0
        )

    @classmethod
    def bounded_local(cls, *, scope: EngineeringScope, principal: LocalOperatorPrincipal) -> Self:
        principal.require_duty(OperatorDuty.ENGINEERING)
        return cls(
            scope=scope,
            issued_by=principal,
            grants=tuple(
                EngineeringGrant(capability=capability, max_admissions=3)
                for capability in EngineeringCapability
            ),
        )


class EngineeringAdmission(DomainModel):
    """One exact application of policy, distinct from RecoveryAuthorization."""

    kind: Literal["engineering_admission"] = "engineering_admission"
    schema_version: Literal["v1"] = "v1"
    authorization_source: Literal["organization_engineering_policy"] = (
        "organization_engineering_policy"
    )
    task_id: NonEmptyStr
    task_intent_sha256: EngineeringSha256
    policy: EngineeringPolicy
    policy_sha256: EngineeringSha256
    plan_sha256: EngineeringSha256
    facts_sha256: EngineeringSha256
    capabilities: Annotated[tuple[EngineeringCapability, ...], Field(min_length=1)]
    admission_number: Annotated[StrictInt, Field(ge=1, le=100)]
    admitted_at: AwareDatetime
    admission_sha256: EngineeringSha256

    @model_validator(mode="after")
    def validate_policy_binding(self) -> Self:
        ensure_unique(self.capabilities, "admission capabilities")
        if self.policy_sha256 != self.policy.policy_sha256:
            raise ValueError("engineering admission policy digest differs")
        if self.admission_number > self.policy.max_total_admissions or any(
            self.policy.allowance(capability) == 0 for capability in self.capabilities
        ):
            raise ValueError("engineering admission exceeds policy authority")
        return self

    def recompute_sha256(self) -> str:
        payload = self.to_wire()
        payload.pop("admission_sha256")
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def validate_integrity(self) -> None:
        if self.admission_sha256 != self.recompute_sha256():
            raise ValueError("engineering admission integrity mismatch")

    @classmethod
    def create(cls, **values: object) -> Self:
        record = cls.model_validate({**values, "admission_sha256": "0" * 64})
        return record.model_copy(update={"admission_sha256": record.recompute_sha256()})
