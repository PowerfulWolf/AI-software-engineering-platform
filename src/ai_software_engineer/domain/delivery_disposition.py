"""One deterministic explanation and next action for a delivery failure.

These records do not authorize an invocation: specialized admissions still verify
source, role permissions, remaining budget, stopped execution and ownership.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr

DispositionSha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class DeliveryResponsibility(StrEnum):
    PRODUCT = "product"
    TEAM = "team"
    ENGINEERING = "engineering"


class DeliveryNextAction(StrEnum):
    RETRY = "RETRY"
    REMEDIATE_CANDIDATE = "REMEDIATE_CANDIDATE"
    REQUEST_PRODUCT_DECISION = "REQUEST_PRODUCT_DECISION"
    REQUEST_ENGINEERING_AUTHORIZATION = "REQUEST_ENGINEERING_AUTHORIZATION"
    WAIT_DEPENDENCY = "WAIT_DEPENDENCY"
    INVESTIGATE_EXECUTION = "INVESTIGATE_EXECUTION"
    RESUME_EXECUTION_BASELINE = "RESUME_EXECUTION_BASELINE"
    TERMINATE = "TERMINATE"


class DeliveryFailureFacts(DomainModel):
    """Facts from trusted application services, never model routing suggestions."""

    task_id: NonEmptyStr
    work_item_id: NonEmptyStr | None = None
    role: AgentRole
    classification: Literal[
        "TRANSIENT_INFRA",
        "NONTRANSIENT_INFRA",
        "INVALID_OUTPUT",
        "QA_FINDING",
        "VERIFICATION_INCONCLUSIVE",
        "REVIEW_FINDING",
        "POLICY_VIOLATION",
        "REQUIREMENT_AMBIGUITY",
        "BUDGET_EXHAUSTED",
        "CONTEXT_CAPACITY",
        "PLATFORM_BUG",
        "EXECUTION_UNCERTAIN",
        "ENVIRONMENT_UNAVAILABLE",
        "ENGINEERING_AUTHORIZATION",
        "SOURCE_PREPARATION_DRIFT",
        "EXECUTION_BASELINE_PAUSED",
        "KNOWLEDGE_PREPARATION_LIMIT",
        "SERVICE_PAUSED",
    ]
    source_revision: NonEmptyStr
    task_intent_sha256: DispositionSha256
    checkpoint_sequence: Annotated[StrictInt, Field(ge=0)]
    budget_available: StrictBool
    retry_authorized: StrictBool = False
    evidence_ids: tuple[NonEmptyStr, ...] = ()
    execution_baseline_sha256: DispositionSha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_baseline_pause(self) -> Self:
        if (self.classification == "EXECUTION_BASELINE_PAUSED") != (
            self.execution_baseline_sha256 is not None
        ):
            raise ValueError("baseline pause must bind its exact execution baseline")
        if self.classification == "EXECUTION_BASELINE_PAUSED" and (
            self.role is not AgentRole.CODER or self.work_item_id is None or self.retry_authorized
        ):
            raise ValueError("baseline pause requires an exact Coder item without automatic retry")
        return self

    @property
    def facts_sha256(self) -> str:
        return _digest(self.to_wire())


class DeliveryDisposition(DomainModel):
    kind: Literal["delivery_disposition"] = "delivery_disposition"
    schema_version: Literal["v1"] = "v1"
    facts: DeliveryFailureFacts
    source_facts_sha256: DispositionSha256
    responsibility: DeliveryResponsibility
    action: DeliveryNextAction
    reason: NonEmptyStr
    next_action: NonEmptyStr
    detail: NonEmptyStr | None = None
    resume_condition: Literal[
        "fresh_role_claim",
        "product_resolution",
        "engineering_authorization",
        "verified_prerequisites",
        "verified_execution_resolution",
        "explicit_baseline_continuation",
        "none",
    ]

    @model_validator(mode="after")
    def validate_facts_binding(self) -> Self:
        if self.source_facts_sha256 != self.facts.facts_sha256:
            raise ValueError("delivery disposition does not bind its exact facts")
        if self.action is DeliveryNextAction.TERMINATE and self.resume_condition != "none":
            raise ValueError("terminated work cannot advertise a resume condition")
        if (
            self.action is DeliveryNextAction.REQUEST_PRODUCT_DECISION
            and self.responsibility is not DeliveryResponsibility.PRODUCT
        ):
            raise ValueError("product decision requires product responsibility")
        if self.facts.classification == "EXECUTION_BASELINE_PAUSED" and (
            self.action is not DeliveryNextAction.RESUME_EXECUTION_BASELINE
            or self.responsibility is not DeliveryResponsibility.ENGINEERING
            or self.resume_condition != "explicit_baseline_continuation"
        ):
            raise ValueError("baseline pause can only request exact explicit continuation")
        if self.facts.classification != "EXECUTION_BASELINE_PAUSED" and (
            self.action is DeliveryNextAction.RESUME_EXECUTION_BASELINE
            or self.resume_condition == "explicit_baseline_continuation"
        ):
            raise ValueError("explicit baseline continuation requires a preserved baseline pause")
        return self

    @property
    def disposition_sha256(self) -> str:
        return _digest(self.to_wire())


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def decide_delivery_disposition(facts: DeliveryFailureFacts) -> DeliveryDisposition:
    """Choose responsibility and action once from typed facts, with no I/O."""
    reason_code = facts.classification
    responsibility = DeliveryResponsibility.ENGINEERING
    action = DeliveryNextAction.WAIT_DEPENDENCY
    condition: Literal[
        "fresh_role_claim",
        "product_resolution",
        "engineering_authorization",
        "verified_prerequisites",
        "verified_execution_resolution",
        "explicit_baseline_continuation",
        "none",
    ] = "verified_prerequisites"
    reason = "当前工程前提尚未满足, 交付已暂停, 工作现场和执行历史保留。"
    next_action = "工程授权者需核验所列前提, 记录处理结果; 事实满足后平台继续原交付。"
    if reason_code == "SERVICE_PAUSED":
        action = DeliveryNextAction.INVESTIGATE_EXECUTION
        condition = "verified_execution_resolution"
        reason = "服务重启已受控暂停本次执行。原交付阶段、审批和工作现场保留。"
        next_action = "工程团队核验真实停止和完整现场后, 按原授权继续; 未完成产物不视为交付结果。"
    elif reason_code == "EXECUTION_BASELINE_PAUSED":
        action, condition = (
            DeliveryNextAction.RESUME_EXECUTION_BASELINE,
            "explicit_baseline_continuation",
        )
        reason = "开发进度已保留, 交付按工程决定暂停, 尚未启动新的执行。"
        next_action = "可先检查并更新源码和工程规范; 确认当前输入后, 明确批准继续原需求。"
    elif reason_code == "POLICY_VIOLATION":
        action, condition = DeliveryNextAction.TERMINATE, "none"
        reason = "执行违反已冻结的权限, 当前交付已停止, 违规证据和现场保留。"
        next_action = "工程授权者需查看违规证据; 原授权不能用于接纳违规改动。"
    elif reason_code == "CONTEXT_CAPACITY":
        reason = "本次交付角色的输入上下文超过配置容量, 模型调用未启动, 交付进度和历史已保留。"
        next_action = (
            "由 ASE 工程处理核验完整输入和配置容量; 输入满足冻结权限与容量后, "
            "再通过受控流程继续原需求。当前等待不要求修改业务目标或验收标准。"
        )
    elif reason_code == "BUDGET_EXHAUSTED" or (
        not facts.budget_available
        and reason_code
        in {
            "TRANSIENT_INFRA",
            "NONTRANSIENT_INFRA",
            "QA_FINDING",
            "REVIEW_FINDING",
            "INVALID_OUTPUT",
        }
    ):
        action, condition = DeliveryNextAction.TERMINATE, "none"
        reason = "已授权执行额度耗尽, 当前交付停止, 草稿、候选和失败记录保留。"
        next_action = "资源授权者需决定追加额度或结束交付; 平台不会无限重试。"
    elif reason_code == "REQUIREMENT_AMBIGUITY":
        responsibility = DeliveryResponsibility.PRODUCT
        action, condition = DeliveryNextAction.REQUEST_PRODUCT_DECISION, "product_resolution"
        reason = "业务目标或验收标准需要确认, 工程执行已暂停。"
        next_action = "产品负责人需回答记录中的具体业务问题, 平台按确认结果继续。"
    elif reason_code == "TRANSIENT_INFRA" and facts.retry_authorized:
        responsibility = DeliveryResponsibility.TEAM
        action, condition = DeliveryNextAction.RETRY, "fresh_role_claim"
        reason = "模型服务发生临时故障, 平台按已授权额度安排新的执行。"
        next_action = "等待 ASE 团队重新调度; 无需产品审批。"
    elif reason_code in {"QA_FINDING", "REVIEW_FINDING"} and facts.retry_authorized:
        responsibility = DeliveryResponsibility.TEAM
        action, condition = DeliveryNextAction.REMEDIATE_CANDIDATE, "fresh_role_claim"
        reason = "独立验收发现问题, 原始反馈已保存并交给 Coder 修改。"
        next_action = "Coder 按原始反馈返工, 随后重新进行独立 QA 和 Review。"
    elif reason_code == "KNOWLEDGE_PREPARATION_LIMIT":
        action, condition = (
            DeliveryNextAction.INVESTIGATE_EXECUTION,
            "verified_execution_resolution",
        )
        reason = "知识准备达到本次执行时限, 交付已暂停, 原执行与知识记录保留。"
        next_action = (
            "点击“让平台处理知识准备”; ASE 核验原执行结束和剩余额度后, "
            "按原授权扩大下一次知识准备窗口。缺少工程授权时由工程授权者确认。"
        )
    elif reason_code == "NONTRANSIENT_INFRA":
        action, condition = (
            DeliveryNextAction.INVESTIGATE_EXECUTION,
            "verified_execution_resolution",
        )
        reason = "本次执行失败, 尚无可信的临时故障事实, 不能自动重试; 现场和原失败记录保留。"
        next_action = "让平台核验原执行、输出和保留进度; 按检查结果准备精确恢复方案后再确认继续。"
    elif reason_code in {"EXECUTION_UNCERTAIN", "PLATFORM_BUG", "INVALID_OUTPUT"}:
        action, condition = (
            DeliveryNextAction.INVESTIGATE_EXECUTION,
            "verified_execution_resolution",
        )
        reason = "当前执行结果无法安全接纳, 交付暂停, 现场和证据保留。"
        next_action = "工程授权者需核验原执行、输出和现场, 并记录精确恢复决定。"
    elif reason_code in {"ENGINEERING_AUTHORIZATION", "SOURCE_PREPARATION_DRIFT"}:
        action, condition = (
            DeliveryNextAction.REQUEST_ENGINEERING_AUTHORIZATION,
            "engineering_authorization",
        )
        reason = "当前工程输入或执行能力需要重新核验授权, 原交付现场保留。"
        next_action = "工程授权者需核验精确变更; 业务范围变化时另交产品负责人确认。"
    return DeliveryDisposition(
        facts=facts,
        source_facts_sha256=facts.facts_sha256,
        responsibility=responsibility,
        action=action,
        reason=reason,
        next_action=next_action,
        resume_condition=condition,
    )
