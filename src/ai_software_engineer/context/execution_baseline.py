"""Read exact trusted execution baseline inputs without granting model authority."""

from __future__ import annotations

import hashlib
from typing import Self

from pydantic import Field, model_validator

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.context.models import ContextBundle
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.task import Task


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


def execution_baseline_from_context(
    context: ContextBundle,
    request: AgentRequest,
    task: Task,
) -> ExecutionBaselineBinding | None:
    """Only a sealed required section matching the exact typed request selects a base."""
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
    value = ExecutionBaselineContext.model_validate_json(section.content)
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
    return baseline
