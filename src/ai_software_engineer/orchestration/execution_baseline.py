"""Trusted append-only baseline and required-body input ports, unavailable to models."""

import hashlib
import json
from typing import Protocol, runtime_checkable

from ai_software_engineer.context.execution_baseline import (
    ExecutionBaselineContext,
    PreservedWorktreeBaselineContext,
    ReappliedBaselineReferenceContext,
    ScheduledBaselineReferenceContext,
    parse_execution_baseline_context,
)
from ai_software_engineer.context.models import ContextBundle, ContextSection, ContextSource
from ai_software_engineer.context.native import validate_native_rule_epoch_context
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
    BaselineInputMode,
    CoderExecutionInput,
    ExecutionBaselineBinding,
)
from ai_software_engineer.domain.execution_native_rules import NativeRuleEpoch
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


@runtime_checkable
class NativeRuleEpochResolver(Protocol):
    def native_rule_epoch(self, source: CoderExecutionInput) -> NativeRuleEpoch | None: ...


class BaselineRunContextBuilder:
    """Append mode-aware verified inputs after ordinary/native/knowledge Context.

    The underlying builder stays unchanged. This required section is atomically
    persisted with a new Context digest and never shortened to fit a token budget.
    """

    def __init__(
        self,
        delegate: RunContextBuilder,
        contexts: ContextStore,
        resolver: CoderExecutionInputResolver,
        *,
        native_sources: tuple[ContextSource, ...] | None = None,
    ) -> None:
        self.delegate, self.contexts, self.resolver = delegate, contexts, resolver
        self.native_sources = native_sources

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
        epoch = (
            self.resolver.native_rule_epoch(source)
            if isinstance(self.resolver, NativeRuleEpochResolver)
            else None
        )
        if epoch is not None:
            if (
                source.baseline is None
                or source.baseline.native_rule_epoch_sha256 != epoch.epoch_sha256
                or (epoch.task_id, epoch.scope.repository_root) != (task.id, task.repository)
            ):
                raise ContextSourceError("执行原生规范版本不属于当前 Task 和工作空间")
            validate_native_rule_epoch_context(context, epoch, expected_sources=self.native_sources)
        elif any(section.name == "source:execution.native_rules" for section in context.sections):
            raise ContextSourceError("当前执行没有可信原生规范版本, 不能接受外加规范批准")
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
        # A finalized historical Context must keep its original complete body,
        # not be rewritten into a new projection after consultation.
        try:
            historical = (
                parse_execution_baseline_context(existing[0].content)
                if len(existing) == 1
                else None
            )
        except ValueError as error:
            raise ContextSourceError("已封存的执行基线上下文与当前可信完整输入不一致") from error
        payload: (
            ExecutionBaselineContext
            | PreservedWorktreeBaselineContext
            | ReappliedBaselineReferenceContext
            | ScheduledBaselineReferenceContext
        ) = (
            value
            if isinstance(historical, ExecutionBaselineContext)
            or source.baseline.input_mode is BaselineInputMode.CODER_REAPPLY
            else PreservedWorktreeBaselineContext.from_complete(value)
        )
        # A recovery dispatch already carries the complete patch in its
        # required ``recovery.patch`` section. Keep that immutable body as the
        # single source for coder_reapply, and retain this section as the typed
        # binding/epoch reference. Other modes and historical contexts keep
        # their original bytes and projection semantics.
        recovery_sections = tuple(
            item for item in context.sections if item.name == "source:recovery.patch"
        )
        schedule_sections = tuple(
            item for item in context.sections if item.name == "source:recovery.input_schedule"
        )
        if source.baseline.input_mode is BaselineInputMode.CODER_REAPPLY and schedule_sections:
            from ai_software_engineer.recovery.bounded_input import RecoveryInputManifest

            if len(schedule_sections) != 1 or schedule_sections[0].truncated:
                raise ContextSourceError("分轮重应用缺少唯一完整的输入调度清单")
            manifest = RecoveryInputManifest.model_validate_json(schedule_sections[0].content)
            current_refs = tuple(
                ref for ref in manifest.sources if ref.source_id == "recovery.patch"
            )
            if (
                len(current_refs) != 1
                or current_refs[0].sha256 != source.baseline.retained_patch.sha256
                or current_refs[0].bytes != source.baseline.retained_patch.bytes
                or hashlib.sha256(schedule_sections[0].content.encode()).hexdigest()
                != schedule_sections[0].sha256
            ):
                raise ContextSourceError("分轮重应用清单与完整执行基线补丁不一致")
            payload = ScheduledBaselineReferenceContext(
                binding=source.baseline,
                retained_patch=source.baseline.retained_patch,
                schedule_sha256=manifest.decision_sha256,
                complete_patch_uri=current_refs[0].uri,
                instructions=(
                    "平台已验证当前目标基线和完整旧补丁, 并按获批工程决定逐轮提供完整来源。"
                    "本轮只能按调度清单适配所选完整来源; 其他来源必须由后续 Coder 轮次读取。"
                    "原历史不等于候选或验收, 最终候选仍须独立 QA 和 Review。"
                ),
            )
        if (
            source.baseline.input_mode is BaselineInputMode.CODER_REAPPLY
            and not schedule_sections
            and not isinstance(historical, ExecutionBaselineContext)
            and len(recovery_sections) == 1
            and not recovery_sections[0].truncated
            and recovery_sections[0].content == value.complete_patch
            and recovery_sections[0].sha256 == source.baseline.retained_patch.sha256
        ):
            payload = ReappliedBaselineReferenceContext(
                binding=source.baseline,
                retained_patch=source.baseline.retained_patch,
                complete_patch_uri=recovery_sections[0].uri,
                instructions=(
                    "平台已校验当前目标基线、原生规范版本和完整旧补丁。"
                    "完整旧补丁只在 recovery.patch 输入中提供; 本引用不重复携带正文,"
                    "Coder 必须读取该唯一正文并在当前基线上适配。"
                    "旧执行结果不是候选或验收通过证明, 新候选仍须独立 QA 和 Review."
                ),
            )
        content = json.dumps(payload.to_wire(), ensure_ascii=False, sort_keys=True)
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
