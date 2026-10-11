"""Read exact trusted execution baseline inputs without granting model authority."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Literal, Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from ai_software_engineer.context.models import ContextBundle
from ai_software_engineer.domain.execution_baseline import (
    BaselineInputMode,
    ExecutionBaselineBinding,
    RetainedExecutionPatch,
)
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.task import Task

if TYPE_CHECKING:
    from ai_software_engineer.agents.models import AgentRequest


class ExecutionBaselineContext(DomainModel):
    binding: ExecutionBaselineBinding
    instructions: NonEmptyStr
    complete_patch: str = Field(max_length=8_000_000)

    @model_validator(mode="after")
    def validate_body(self) -> Self:
        self.binding.validate_integrity()
        body = self.complete_patch.encode("utf-8")
        if (
            len(body) != self.binding.retained_patch.bytes
            or hashlib.sha256(body).hexdigest() != self.binding.retained_patch.sha256
        ):
            raise ValueError("完整执行基线旧补丁与已封存记录不一致")
        return self

    @classmethod
    def from_required_context(cls, binding: ExecutionBaselineBinding, content: str) -> Self:
        instructions, marker, patch = content.partition("完整旧补丁:\n")
        if not marker:
            raise ValueError("执行基线上下文缺少完整旧补丁正文")
        return cls(binding=binding, instructions=instructions, complete_patch=patch)


class PreservedWorktreeBaselineContext(DomainModel):
    """Reading projection; complete evidence remains in the trusted baseline store."""

    schema_version: Literal["v2"] = "v2"
    binding: ExecutionBaselineBinding
    instructions: NonEmptyStr
    patch_input: Literal["preserved_worktree"] = "preserved_worktree"
    retained_patch: RetainedExecutionPatch

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        self.binding.validate_integrity()
        if (
            self.binding.input_mode is not BaselineInputMode.PRESERVE_DRAFT
            or self.retained_patch != self.binding.retained_patch
        ):
            raise ValueError("保留工作区投影与完整旧补丁引用或执行模式不一致")
        return self

    @classmethod
    def from_complete(cls, complete: ExecutionBaselineContext) -> Self:
        # Validate the actual complete body before projecting it. A reference
        # alone is never enough to create a role's execution input.
        ExecutionBaselineContext.model_validate(complete.to_wire())
        binding = complete.binding
        return cls(
            binding=binding,
            retained_patch=binding.retained_patch,
            instructions=(
                "平台已完整校验封存的执行基线、授权历史和旧补丁, 并保留既有开发进度。"
                "当前角色使用已核验的隔离工作区或由其产生的候选。"
                "请在原需求范围和本角色权限内检查并继续。不要清空或重建工作区。"
                "本阅读投影不授予执行或写入权限, 不证明原调用结果、实际停止或验收通过。"
                "完整旧补丁仍由平台按所列 URI、SHA-256 和字节数校验保存; "
                "当前模式从保留工作区继续, 无需将其重复作为补丁重新应用。"
                "新候选仍须独立 QA 和 Review 使用同一候选版本验收。"
            ),
        )


@runtime_checkable
class ExecutionBaselineContextVerifier(Protocol):
    """Trusted complete-store validation, never a model-supplied permission."""

    def require_current(self, binding: ExecutionBaselineBinding, task: Task) -> None: ...


def parse_execution_baseline_context(
    content: str,
) -> ExecutionBaselineContext | PreservedWorktreeBaselineContext:
    """Read v1 unchanged and v2 explicitly; an invalid version never falls back."""
    value = json.loads(content)
    if isinstance(value, dict) and value.get("schema_version") == "v2":
        return PreservedWorktreeBaselineContext.model_validate(value)
    return ExecutionBaselineContext.model_validate(value)


def execution_baseline_from_context(
    context: ContextBundle,
    request: AgentRequest,
    task: Task,
    *,
    verifier: ExecutionBaselineContextVerifier | None = None,
) -> ExecutionBaselineBinding | None:
    """Only a sealed required section matching the exact typed request selects a base."""
    if (
        context.context_id,
        context.task_id,
        context.role,
        context.attempt,
        context.source_revision,
    ) != (
        request.context_manifest_id,
        request.task_id,
        request.role,
        request.attempt,
        request.source_revision,
    ):
        raise ValueError("执行基线上下文与本次角色请求身份不一致")
    sections = tuple(
        section for section in context.sections if section.name == "execution.baseline"
    )
    if request.execution_baseline_sha256 is None:
        if sections or request.execution_base_ref is not None:
            raise ValueError("执行基线上下文与本次请求绑定不一致")
        return None
    if len(sections) != 1:
        raise ValueError("本次请求缺少唯一完整的执行基线上下文")
    section = sections[0]
    if section.truncated or hashlib.sha256(section.content.encode()).hexdigest() != section.sha256:
        raise ValueError("执行基线上下文不完整或内容摘要不一致")
    value = parse_execution_baseline_context(section.content)
    baseline = value.binding
    baseline.require_task(task)
    if (
        section.uri,
        baseline.binding_sha256,
        baseline.execution_base_ref,
    ) != (
        "baseline://" + request.execution_baseline_sha256,
        request.execution_baseline_sha256,
        request.execution_base_ref,
    ):
        raise ValueError("执行基线上下文与精确工程绑定不一致")
    if isinstance(value, PreservedWorktreeBaselineContext) and verifier is None:
        raise ValueError("保留工作区投影缺少完整执行基线证据校验")
    if verifier is not None:
        verifier.require_current(baseline, task)
    return baseline
