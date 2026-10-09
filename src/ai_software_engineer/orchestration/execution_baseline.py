"""Trusted append-only baseline and required-body input ports, unavailable to models."""

import hashlib
import json
from typing import Protocol

from ai_software_engineer.context.execution_baseline import ExecutionBaselineContext
from ai_software_engineer.context.models import ContextBundle, ContextSection
from ai_software_engineer.context.ports import (
    ContextBudgetExceeded,
    ContextSourceError,
    ContextStore,
)
from ai_software_engineer.domain.agent import AgentDefinition
from ai_software_engineer.domain.artifact import (
    Artifact,
    CoderProgressArtifact,
    ImplementationReportArtifact,
)
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.execution_baseline import (
    CoderExecutionInput,
    ExecutionBaselineBinding,
)
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.orchestration.context import RunContextBuilder
from ai_software_engineer.redaction import patch_secret_occurrences, redact_text


class ExecutionBaselineStore(Protocol):
    """Reads must validate complete sequence/hash/body references, never only latest JSON."""

    def bindings_for_task(self, task_id: TaskId) -> tuple[ExecutionBaselineBinding, ...]: ...

    def put_binding(self, binding: ExecutionBaselineBinding) -> ExecutionBaselineBinding: ...


class CoderExecutionInputResolver(Protocol):
    """Composition must use the same resolver before and inside every owner fence."""

    def current(
        self,
        task: Task,
        *,
        implementation: ImplementationReportArtifact | None,
        progress: CoderProgressArtifact | None,
    ) -> CoderExecutionInput: ...

    def required_context(self, source: CoderExecutionInput) -> str | None:
        """Return the full verified body; never truncate or accept only its digest."""
        ...


class BaselineRunContextBuilder:
    """Append the complete verified patch after ordinary/native/knowledge Context.

    The underlying builder stays unchanged. This required section is atomically
    persisted with a new Context digest and never shortened to fit a token budget.
    """

    def __init__(
        self,
        delegate: RunContextBuilder,
        contexts: ContextStore,
        resolver: CoderExecutionInputResolver,
    ) -> None:
        self.delegate, self.contexts, self.resolver = delegate, contexts, resolver

    def build(
        self,
        task: Task,
        agent: AgentDefinition,
        *,
        attempt: int,
        candidate_revision: str | None = None,
        input_artifacts: tuple[Artifact, ...] = (),
    ) -> ContextBundle:
        context = self.delegate.build(
            task,
            agent,
            attempt=attempt,
            candidate_revision=candidate_revision,
            input_artifacts=input_artifacts,
        )
        if agent.role not in {AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER}:
            return context
        # The runner independently resolves the actual latest candidate and
        # supplies its exact source. Here only the current immutable binding/body
        # is selected; no historical implementation is promoted by Context code.
        source = self.resolver.current(task, implementation=None, progress=None)
        existing = tuple(s for s in context.sections if s.name == "execution.baseline")
        if source.baseline is None:
            if existing:
                raise ContextSourceError("原需求没有可信执行基线, 不能接受外加基线 section")
            return context
        body = self.resolver.required_context(source)
        if body is None:
            raise ContextSourceError("complete execution baseline body is missing or sensitive")
        value = ExecutionBaselineContext.from_required_context(source.baseline, body)
        if redact_text(value.instructions).occurrences or patch_secret_occurrences(
            value.complete_patch
        ):
            raise ContextSourceError("complete execution baseline body is missing or sensitive")
        content = json.dumps(value.to_wire(), ensure_ascii=False, sort_keys=True)
        tokens = (len(content) + 3) // 4
        section = ContextSection(
            name="execution.baseline",
            uri="baseline://" + source.baseline.binding_sha256,
            content=content,
            sha256=hashlib.sha256(content.encode()).hexdigest(),
            tokens=tokens,
            priority=20,
        )
        if existing:
            if existing != (section,):
                raise ContextSourceError("已封存的执行基线上下文与当前可信完整输入不一致")
            # Production inserts this required body before knowledge consultation.
            # An outer runtime guard verifies it without changing that final lineage.
            return context
        used = context.budget.used_input_tokens + tokens
        if used > context.budget.max_input_tokens:
            raise ContextBudgetExceeded("完整执行基线补丁无法放入本次上下文, 需工程调整上下文能力")
        updated = context.model_copy(
            update={
                "sections": (*context.sections, section),
                "budget": context.budget.model_copy(update={"used_input_tokens": used}),
            }
        )
        wire = updated.model_dump(mode="json", exclude={"context_id", "built_at"})
        identity = hashlib.sha256(
            json.dumps(
                wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        return self.contexts.put(updated.model_copy(update={"context_id": "ctx_" + identity}))
