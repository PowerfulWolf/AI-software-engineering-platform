"""Normal serial role verification authority, independent of recovery Tasks."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.engineering_authority import EngineeringPolicy, EngineeringScope
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr


def role_verification_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class NativeRoleVerificationClaim(DomainModel):
    work_item_id: NonEmptyStr
    lease_id: NonEmptyStr
    assignment_id: NonEmptyStr
    agent_id: NonEmptyStr
    checkpoint_sequence: Annotated[StrictInt, Field(ge=0)]
    dispatch_sequence: Annotated[StrictInt, Field(ge=0)]


class NativeRoleVerificationPlan(DomainModel):
    kind: Literal["native_role_verification_plan_v1"] = "native_role_verification_plan_v1"
    scope: EngineeringScope
    requirement_id: NonEmptyStr
    task_id: NonEmptyStr
    task_intent_sha256: Sha256
    run_id: NonEmptyStr
    role: Literal[AgentRole.QA, AgentRole.REVIEWER]
    attempt: Annotated[StrictInt, Field(ge=1)]
    work_attempt: Annotated[StrictInt, Field(ge=1)]
    candidate_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    workspace_root: NonEmptyStr
    context_manifest_id: NonEmptyStr
    request_sha256: Sha256
    permissions_sha256: Sha256
    plan_artifact_id: NonEmptyStr
    plan_artifact_sha256: Sha256
    implementation_artifact_id: NonEmptyStr
    implementation_artifact_sha256: Sha256
    requirements_sha256: Sha256
    capability_sha256: Sha256
    policy_sha256: Sha256
    claim: NativeRoleVerificationClaim
    created_at: AwareDatetime
    plan_sha256: Sha256

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "plan_sha256": "0" * 64})
        return value.model_copy(update={"plan_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return role_verification_digest(
            self.model_dump(
                mode="json",
                exclude={"plan_sha256", "created_at"},
            )
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.plan_sha256 != self.recompute_sha256():
            raise ValueError("native role verification plan changed")


class NativeRoleVerificationAdmission(DomainModel):
    """Uses the existing role budget; never consumes a recovery admission."""

    kind: Literal["native_role_verification_admission_v1"] = "native_role_verification_admission_v1"
    authorization_source: Literal["frozen_task_role_authorization"] = (
        "frozen_task_role_authorization"
    )
    task_id: NonEmptyStr
    task_intent_sha256: Sha256
    run_id: NonEmptyStr
    role: Literal[AgentRole.QA, AgentRole.REVIEWER]
    plan_sha256: Sha256
    request_sha256: Sha256
    policy: EngineeringPolicy
    policy_sha256: Sha256
    work_attempt: Annotated[StrictInt, Field(ge=1)]
    admitted_at: AwareDatetime
    admission_sha256: Sha256

    @model_validator(mode="after")
    def bound_policy(self) -> Self:
        if self.policy_sha256 != self.policy.policy_sha256:
            raise ValueError("normal role admission policy changed")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "admission_sha256": "0" * 64})
        return value.model_copy(update={"admission_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return role_verification_digest(
            self.model_dump(
                mode="json",
                exclude={"admission_sha256", "admitted_at"},
            )
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.admission_sha256 != self.recompute_sha256():
            raise ValueError("native role verification admission changed")


class NativeVerificationWaitReason(StrEnum):
    LEGACY_AUTHORITY = "LEGACY_VERIFICATION_AUTHORITY_REQUIRED"
    UNSUPPORTED_ENTRYPOINT = "CONTROLLED_VERIFICATION_ENTRYPOINT_UNSUPPORTED"
    UNSUPPORTED_SWIFT_FILTER = "CONTROLLED_SWIFT_FILTER_UNSUPPORTED"
    NATIVE_UI_PREREQUISITE = "CONTROLLED_NATIVE_UI_PREREQUISITE_REQUIRED"
    CAPABILITY_UNAVAILABLE = "CONTROLLED_VERIFICATION_CAPABILITY_UNAVAILABLE"
    FACTS_CHANGED = "CONTROLLED_VERIFICATION_FACTS_CHANGED"
    EXECUTION_UNCERTAIN = "CONTROLLED_VERIFICATION_EXECUTION_UNCERTAIN"
    COMMAND_TIMEOUT = "CONTROLLED_VERIFICATION_COMMAND_TIMEOUT"
    COMMAND_START_FAILED = "CONTROLLED_VERIFICATION_COMMAND_START_FAILED"


class NativeVerificationWaiting(RuntimeError):
    def __init__(
        self,
        reason: NativeVerificationWaitReason,
        *,
        record_sha256: str | None = None,
    ) -> None:
        self.reason, self.record_sha256 = reason, record_sha256
        messages = {
            NativeVerificationWaitReason.LEGACY_AUTHORITY: (
                "任务没有冻结的受控验证授权。需工程负责人处理。"
            ),
            NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT: (
                "验证入口不受当前精确增量执行器支持。需工程负责人处理。"
            ),
            NativeVerificationWaitReason.UNSUPPORTED_SWIFT_FILTER: (
                "当前 Swift 受控执行器尚不能执行计划中的增量筛选。需工程负责人处理。"
            ),
            NativeVerificationWaitReason.NATIVE_UI_PREREQUISITE: (
                "原生界面验证前提尚未建立。需工程负责人处理。"
            ),
            NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE: (
                "受控验证工具或隔离环境尚不可用。需工程负责人处理。"
            ),
            NativeVerificationWaitReason.FACTS_CHANGED: (
                "验证输入、工作区、权限或当前执行归属发生变化。已保留交付检查点。"
            ),
            NativeVerificationWaitReason.EXECUTION_UNCERTAIN: (
                "上次验证启动后的结果不确定。已保留证据。不会重放原执行。"
            ),
            NativeVerificationWaitReason.COMMAND_TIMEOUT: (
                "受控增量验证超过本轮时间窗口。已保留交付检查点。"
            ),
            NativeVerificationWaitReason.COMMAND_START_FAILED: (
                "受控增量验证未能正常启动或清理。需工程负责人处理。"
            ),
        }
        super().__init__(messages[reason])
