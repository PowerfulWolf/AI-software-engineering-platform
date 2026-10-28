"""Exact engineering schedule for complete, serial recovery patch inputs.

This record is an authorization for input selection only. It is not an Agent
result, a patch application, a candidate or a QA/Review verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self

from pydantic import AwareDatetime, Field, StrictInt, StringConstraints, model_validator

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, model_route_root
from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
)
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal, OperatorDuty
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import Task, task_matches_dispatch
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.recovery.bounded_input import (
    RecoveryInputSourceRef,
    complete_reapply_source_refs,
)
from ai_software_engineer.recovery.models import RecoveryAuthorization, RecoveryPlan
from ai_software_engineer.recovery.records import RecoverySeedRecord, RecoveryTaskRecord
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem

_MAX_NEGATIVE_FACT_RECORDS = 4096
ConsoleOperationAuthorizationReference = Annotated[
    str,
    StringConstraints(
        pattern=r"^web-console-operation:operation_[a-f0-9]{32}:[a-f0-9]{64}:[a-f0-9]{64}$"
    ),
]


@dataclass(frozen=True, slots=True)
class RecoveryInputPlanFacts:
    """Already sealed Plan and allocation, read through trusted Host composition."""

    plan: RecoveryPlan
    authorization: RecoveryAuthorization
    task_record: RecoveryTaskRecord
    dispatch: RecoveryDispatchRecord
    seed: RecoverySeedRecord


class RecoveryInputQueue(Protocol):
    def claims_for_work_item(self, work_item_id: str) -> tuple[QueueClaim, ...]: ...
    def original_claim(self, lease_id: str) -> QueueClaim: ...
    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]: ...


class RecoveryInputResolutionReader(Protocol):
    def consumed_recovery_input_resolution(self, task_id: str) -> DeliveryResolution | None: ...


class RecoveryInputScheduleDecision(DomainModel):
    """Immutable one-source-per-accepted-Run authority for an existing Task."""

    kind: Literal["recovery_input_schedule"] = "recovery_input_schedule"
    schema_version: Literal["v1"] = "v1"
    mode: Literal["one_complete_source_per_accepted_coder_run"] = (
        "one_complete_source_per_accepted_coder_run"
    )
    plan_sha256: StageSha256
    task_id: NonEmptyStr
    task_intent_sha256: StageSha256
    target_base_revision: NonEmptyStr
    authorization_sha256: StageSha256
    task_record_sha256: StageSha256
    dispatch_sha256: StageSha256
    seed_record_sha256: StageSha256
    work_item_id: NonEmptyStr
    disposition_sha256: StageSha256
    task_revision: StrictInt = Field(ge=0)
    task_snapshot_sha256: StageSha256
    step_sha256: StageSha256
    original_claim_sha256: StageSha256
    original_lease_id: NonEmptyStr
    # The current recovery plan always contains the two inherited patches and
    # the current full capture.  Keeping this cardinality exact prevents a
    # malformed schedule from being persisted successfully and failing only
    # when the next Coder Context is assembled.
    sources: tuple[RecoveryInputSourceRef, ...] = Field(min_length=3, max_length=3)
    engineering_actor: LocalOperatorPrincipal
    authorization_reference: ConsoleOperationAuthorizationReference
    decided_at: AwareDatetime
    schedule_sha256: StageSha256

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        self.engineering_actor.require_duty(OperatorDuty.ENGINEERING)
        if len(self.sources) != 3:
            raise ValueError("recovery input schedule requires exactly three complete sources")
        if len({source.source_id for source in self.sources}) != len(self.sources) or len(
            {source.uri for source in self.sources}
        ) != len(self.sources):
            raise ValueError("recovery input schedule has duplicate complete sources")
        if self.task_id != f"task_recovery_{self.plan_sha256[:32]}":
            raise ValueError("recovery input schedule changed the approved Task")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"schedule_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.schedule_sha256 != self.recompute_sha256():
            raise ValueError("recovery input schedule digest mismatch")


def get_recovery_input_schedule(
    records: KnowledgeRecordStore, plan_sha256: str
) -> RecoveryInputScheduleDecision | None:
    """Read the immutable schedule; a missing record grants no source selection."""
    schedule = records.find("recovery-input-schedules", plan_sha256, RecoveryInputScheduleDecision)
    if schedule is not None:
        schedule.validate_integrity()
        if schedule.plan_sha256 != plan_sha256:
            raise ValueError("recovery input schedule key changed")
    return schedule


def require_consumed_recovery_input_schedule(
    queue: RecoveryInputResolutionReader,
    records: KnowledgeRecordStore,
    plan: RecoveryPlan,
    dispatch: RecoveryDispatchRecord,
    task: Task,
) -> RecoveryInputScheduleDecision | None:
    """Activate bounded input only after the original wait's SQL consumption.

    A dangling decision file is an unconsumed proposal. A consumed decision with
    missing or changed files is corruption and must stop provider admission.
    """
    plan.validate_integrity()
    dispatch.validate_integrity()
    decision = queue.consumed_recovery_input_resolution(task.id)
    if decision is None:
        return None
    decision.validate_integrity()
    schedule = get_recovery_input_schedule(records, plan.plan_sha256)
    original = decision.pre_context_recovery_input
    if (
        schedule is None
        or original is None
        or decision.resolution_kind is not DeliveryResolutionKind.SCHEDULE_RECOVERY_INPUT
        or decision.recovery_input_schedule_sha256 != schedule.schedule_sha256
        or decision.authorization_reference != schedule.authorization_reference
        or decision.operator_principal != schedule.engineering_actor
        or decision.task_id != schedule.task_id
        or decision.work_item_id != schedule.work_item_id
        or decision.expected_disposition_sha256 != schedule.disposition_sha256
        or decision.expected_task_intent_sha256 != schedule.task_intent_sha256
        or decision.expected_source_revision != schedule.target_base_revision
        or decision.task_revision != schedule.task_revision
        or decision.task_snapshot_sha256 != schedule.task_snapshot_sha256
        or decision.step_sha256 != schedule.step_sha256
        or original.plan_sha256 != plan.plan_sha256
        or original.authorization_sha256 != schedule.authorization_sha256
        or original.task_record_sha256 != schedule.task_record_sha256
        or original.dispatch_sha256 != dispatch.dispatch_sha256
        or original.seed_record_sha256 != schedule.seed_record_sha256
        or original.original_claim_sha256 != schedule.original_claim_sha256
        or original.original_lease_id != schedule.original_lease_id
        or original.source_inventory_sha256
        != digest(tuple(source.to_wire() for source in schedule.sources))
        or schedule.plan_sha256 != plan.plan_sha256
        or schedule.task_id != task.id
        or schedule.task_intent_sha256 != task_intent_sha256(task)
        or schedule.target_base_revision != plan.target_base_revision
        or task.base_ref != plan.target_base_revision
        or task.metadata.get("recovery_plan_sha256") != plan.plan_sha256
        or dispatch.recovery_plan_sha256 != plan.plan_sha256
        or dispatch.task_id != task.id
        or not task_matches_dispatch(task, dispatch.task)
        or schedule.dispatch_sha256 != dispatch.dispatch_sha256
        or schedule.sources != complete_reapply_source_refs(plan)
    ):
        raise ValueError("已消费的预 Context 恢复输入决定与当前完整来源或 Task 不一致")
    return schedule


def inspect_pre_context_recovery_input(
    *,
    item: QueuedWorkItem,
    step: QueuedRoleStep,
    task: Task,
    task_revision: int,
    state: Path,
    queue: RecoveryInputQueue,
    artifacts: ArtifactStore,
    git: GitWorktreeManager,
    facts: RecoveryInputPlanFacts,
) -> tuple[QueueClaim, tuple[RecoveryInputSourceRef, ...]]:
    """Prove the exact capacity wait stopped before any Coder Context or model start.

    This is a fresh read-side observation under the caller's Task process lock.
    Missing or corrupt stores fail closed; no historical record is rewritten.
    """
    plan, authorization, sealed, dispatch, seed = (
        facts.plan,
        facts.authorization,
        facts.task_record,
        facts.dispatch,
        facts.seed,
    )
    plan.validate_integrity()
    authorization.validate_integrity()
    dispatch.validate_integrity()
    seed.validate_integrity()
    sources = complete_reapply_source_refs(plan)
    disposition = item.wait_disposition
    if (
        len(sources) != 3
        or disposition is None
        or disposition.facts.classification != "CONTEXT_CAPACITY"
        or any(value.startswith("context-capacity://") for value in disposition.facts.evidence_ids)
        or item.role is not AgentRole.CODER
        or disposition.facts.task_intent_sha256 != task_intent_sha256(task)
        or task.status is not TaskStatus.IMPLEMENTING
        or task.attempts != item.attempt
        or task.work_budget_exhausted
        or task_revision != item.checkpoint_sequence
        or step.boundary.checkpoint_sequence != task_revision
        or step.boundary.source_revision != plan.target_base_revision
        or task.base_ref != plan.target_base_revision
        or task.id != plan.new_task_id
        or task.metadata.get("recovery_plan_sha256") != plan.plan_sha256
        or not authorization.decision.approved
        or authorization.command.plan_sha256 != plan.plan_sha256
        or sealed.authorization_sha256 != authorization.authorization_sha256
        or sealed.record_sha256 != dispatch.recovery_task_record_sha256
        or not task_matches_dispatch(task, sealed.task)
        or dispatch.recovery_plan_sha256 != plan.plan_sha256
        or dispatch.task_id != task.id
        or dispatch.task != sealed.task
        or seed.recovery_plan_sha256 != plan.plan_sha256
        or seed.dispatch_sha256 != dispatch.dispatch_sha256
    ):
        raise ValueError("预 Context 恢复输入不属于当前已批准的完整 Task 和容量等待")
    claims = queue.claims_for_work_item(item.id)
    if len(claims) != 1:
        raise ValueError("预 Context 容量等待缺少唯一真实 Coder claim")
    claim = claims[0]
    original = queue.original_claim(claim.lease.id)
    if original != claim or (
        claim.work_item.id,
        claim.work_item.task_id,
        claim.work_item.role,
        claim.work_item.attempt,
        claim.work_item.dispatch_sequence,
        claim.work_item.checkpoint_sequence,
        claim.work_item.repository_id,
    ) != (
        item.id,
        task.id,
        AgentRole.CODER,
        item.attempt,
        item.dispatch_sequence,
        item.checkpoint_sequence,
        item.repository_id,
    ):
        raise ValueError("预 Context 容量等待的原 claim 与当前队列世代不一致")
    if any(accepted.work_item_id == item.id for accepted in queue.accepted(task.id)) or any(
        artifact.producer.role is AgentRole.CODER for artifact in artifacts.list_for_task(task.id)
    ):
        raise ValueError("预 Context 容量等待已有 Coder 产出")
    _require_no_coder_start(state, task, item.attempt)
    worktree = seed.capture.to_capture().worktree
    if worktree.task_id != task.id or worktree.head_revision != task.base_ref:
        raise ValueError("预 Context 容量等待的 seed 与原 Coder worktree 不一致")
    snapshot = git.inspect(worktree)
    current = git.capture_mutations(
        worktree,
        plan.effective_target_permissions,
        denied_paths=plan.denied_paths,
        include_ignored=True,
    )
    if snapshot.head_revision != task.base_ref or snapshot.dirty or current.changed_paths:
        raise ValueError("预 Context 容量等待的原 Coder 工作区已有未接纳改动")
    return claim, sources


def _require_no_coder_start(state: Path, task: Task, attempt: int) -> None:
    task_id = task.id
    context_root = state.parent / "contexts"
    if context_root.exists():
        if context_root.is_symlink() or not context_root.is_dir():
            raise ValueError("预 Context 容量调查的 Context store 不可验证")
        contexts = FileContextStore(context_root, read_only=True)
        context_paths = tuple(islice(context_root.glob("*.json"), _MAX_NEGATIVE_FACT_RECORDS + 1))
        if len(context_paths) > _MAX_NEGATIVE_FACT_RECORDS:
            raise ValueError("预 Context 容量调查的 Context 记录超过有界观察上限")
        for path in context_paths:
            if path.is_symlink() or not path.is_file() or not path.name.startswith("ctx_"):
                raise ValueError("预 Context 容量调查发现无法验证的 Context 记录")
            context = contexts.get(path.stem)
            if context.task_id == task_id and not (
                context.role is AgentRole.ORCHESTRATOR
                and context.attempt == attempt
                and context.source_revision == task.base_ref
            ):
                raise ValueError(
                    "原 Task 已封存非本次编排准备的 Context, 不属于预 Context 容量恢复"
                )
    invocation_root = state / "invocations"
    if invocation_root.exists():
        invocations = KnowledgeRecordStore(invocation_root, read_only=True)
        starts = invocations.list(
            "invocation-starts", DeliveryInvocationStart, limit=_MAX_NEGATIVE_FACT_RECORDS
        )
        outcomes = invocations.list(
            "invocation-outcomes", DeliveryInvocationOutcome, limit=_MAX_NEGATIVE_FACT_RECORDS
        )
        if len(starts) + len(outcomes) > _MAX_NEGATIVE_FACT_RECORDS:
            raise ValueError("预 Context 容量调查的调用记录超过有界观察上限")
        for start in starts:
            start.validate_integrity()
            if start.request.task_id == task_id:
                raise ValueError("原 Task 已有模型调用开始记录")
        for outcome in outcomes:
            outcome.validate_integrity()
            if outcome.start.request.task_id == task_id:
                raise ValueError("原 Task 已有模型调用结果记录")
    routes_root = model_route_root(state.parent)
    if routes_root.exists():
        if routes_root.is_symlink() or not routes_root.is_dir():
            raise ValueError("预 Context 容量调查的模型路由 store 不可验证")
        routes = FileModelRouteAttemptStore(routes_root, read_only=True)
        directories = tuple(islice(routes_root.iterdir(), _MAX_NEGATIVE_FACT_RECORDS + 1))
        if len(directories) > _MAX_NEGATIVE_FACT_RECORDS:
            raise ValueError("预 Context 容量调查的路由记录超过有界观察上限")
        for directory in directories:
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError("预 Context 容量调查发现无法验证的模型路由目录")
            if any(attempt.task_id == task_id for attempt in routes.list_for_run(directory.name)):
                raise ValueError("原 Task 已有模型路由执行记录")
