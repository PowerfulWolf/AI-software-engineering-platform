"""Read complete failed knowledge preparation without inventing a main-call stop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, JsonValue, TypeAdapter

from ai_software_engineer.agents.structured_observation import StructuredNativeStopReceipt
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import TaskStatus, TeamRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.task import Task, task_matches_dispatch
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord,
    KnowledgeInvocationIntent,
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
    invocation_scope_lane_sha256,
)
from ai_software_engineer.knowledge.models import KnowledgeSnapshot, digest
from ai_software_engineer.knowledge.preparation_retry import claim_identity_sha256
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.capacity_input_reader import (
    CapacityInputReader,
    PriorInvocationFence,
    UninvokedClaimBoundary,
)
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.team_workspace import _reject_symlinks
from ai_software_engineer.work_queue.claim_snapshot import (
    OriginalClaimRecord,
    require_claim_snapshot,
)
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem


class KnowledgeOnlyClaimProof(DomainModel):
    """Quiescence summary, never a verdict, refund or remote process-stop receipt."""

    lease_id: NonEmptyStr
    claim_sha256: Sha256
    intent_sha256s: tuple[Sha256, ...] = Field(min_length=1)
    outcome_sha256s: tuple[Sha256, ...] = Field(min_length=1)
    execution_record_sha256s: tuple[Sha256, ...] = Field(min_length=1)


class ReplayGuardedClaimObservation(KnowledgeOnlyClaimProof):
    """Current deduction from a prior write-once start, never a backdated event."""

    kind: Literal["replay_guarded_claim_observation"] = "replay_guarded_claim_observation"
    blocking_start_sha256: Sha256
    context_sha256s: tuple[Sha256, ...] = Field(min_length=1)
    observation_sha256: Sha256

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.observation_sha256 != digest(
            self.model_dump(mode="json", exclude={"observation_sha256"})
        ):
            raise ValueError("replay guarded claim observation integrity mismatch")


class KnowledgeProofQueue(Protocol):
    def original_claim(self, lease_id: str) -> QueueClaim: ...

    def step_for_claim(self, claim: QueueClaim) -> QueuedRoleStep: ...

    def original_claim_record(self, lease_id: str) -> OriginalClaimRecord: ...


def read_failed_knowledge_claims(
    *,
    state: Path,
    task: Task,
    item: QueuedWorkItem,
    claims: tuple[QueueClaim, ...],
    scope: EngineeringScope,
    requirement_id: str,
    queue: KnowledgeProofQueue,
    require_step: Callable[[QueuedWorkItem, QueuedRoleStep], None],
    no_start_reader: CapacityInputReader,
    isolated_lease_ids: frozenset[str] = frozenset(),
) -> tuple[KnowledgeOnlyClaimProof, ...]:
    """Cover only exact failed read-only preparations; unknown claims stay unknown."""
    if not claims:
        return ()
    by_lease = {claim.lease.id: claim for claim in claims}
    if len(by_lease) != len(claims):
        raise ValueError("知识准备调查含重复历史 claim")
    lanes = _knowledge_lanes(
        state=state, task=task, item=item, scope=scope, requirement_id=requirement_id
    )
    # A returned-only preparation is not this proof family. Leave its claims to
    # their actual main/preflight/capacity facts instead of inventing failure.
    if not any(
        value.state == "FAILED"
        and value.intent.claim is not None
        and value.intent.claim.lease.id in by_lease
        for lane in lanes
        for value in lane.outcomes
    ):
        return ()
    grouped: dict[str, list[KnowledgeInvocationOutcome]] = {}
    for value in _validated_knowledge_invocations(
        state=state,
        task=task,
        scope=scope,
        lanes=lanes,
        queue=queue,
        require_step=require_step,
        isolated_lease_ids=isolated_lease_ids,
    ):
        historical, outcome = value.historical, value.outcome
        if historical.lease.id not in by_lease:
            continue
        require_claim_snapshot(by_lease[historical.lease.id], historical)
        grouped.setdefault(historical.lease.id, []).append(outcome)
    result = []
    for lease_id in sorted(grouped):
        values = sorted(grouped[lease_id], key=lambda v: (v.intent.created_at, v.intent.phase))
        if not any(value.state == "FAILED" for value in values):
            raise ValueError("知识准备只有返回结果, 没有可验证的失败边界")
        if len({digest(value.intent.binding.to_wire()) for value in values}) != 1:
            raise ValueError("同一历史 claim 的知识准备输入存在不同版本")
        bound = values[0].intent.binding
        claim = by_lease[lease_id]
        no_start_reader.require_claim_not_started(
            UninvokedClaimBoundary(
                task_id=task.id,
                work_item_id=item.id,
                lease_id=lease_id,
                role=item.role,
                attempt=item.attempt,
                checkpoint_sequence=item.checkpoint_sequence,
                dispatch_sequence=claim.work_item.dispatch_sequence,
                observed_at=max(value.completed_at for value in values),
                run_id=bound.run_id,
                context_manifest_id=bound.context_manifest_id,
            ),
            allow_later_claims=True,
        )
        result.append(
            KnowledgeOnlyClaimProof(
                lease_id=lease_id,
                claim_sha256=claim_identity_sha256(claim),
                intent_sha256s=tuple(value.intent.intent_sha256 for value in values),
                outcome_sha256s=tuple(value.outcome_sha256 for value in values),
                execution_record_sha256s=tuple(
                    record.record_sha256 for value in values for record in value.executions
                ),
            )
        )
    return tuple(result)


def read_replay_guarded_claims(
    *,
    state: Path,
    task: Task,
    item: QueuedWorkItem,
    claims: tuple[QueueClaim, ...],
    scope: EngineeringScope,
    requirement_id: str,
    queue: KnowledgeProofQueue,
    require_step: Callable[[QueuedWorkItem, QueuedRoleStep], None],
    no_start_reader: CapacityInputReader,
    fence: PriorInvocationFence,
    isolated_lease_ids: frozenset[str] = frozenset(),
) -> tuple[ReplayGuardedClaimObservation, ...]:
    """Observe complete returned preparation behind an earlier mandatory call fence.

    This records no historical refusal and grants no execution or refund authority.
    The caller separately proves the old call was contained and retains its UNKNOWN.
    """
    if not claims:
        return ()
    by_lease = {claim.lease.id: claim for claim in claims}
    if len(by_lease) != len(claims):
        raise ValueError("重领观察包含重复 claim")
    lanes = _knowledge_lanes(
        state=state, task=task, item=item, scope=scope, requirement_id=requirement_id
    )
    grouped: dict[str, list[_CompletedKnowledgeInvocation]] = {}
    for value in _validated_knowledge_invocations(
        state=state,
        task=task,
        scope=scope,
        lanes=lanes,
        queue=queue,
        require_step=require_step,
        isolated_lease_ids=isolated_lease_ids,
    ):
        historical = value.historical
        if historical.lease.id not in by_lease:
            continue
        require_claim_snapshot(by_lease[historical.lease.id], historical)
        grouped.setdefault(historical.lease.id, []).append(value)
    result = []
    for lease_id in sorted(grouped):
        completed = sorted(
            grouped[lease_id], key=lambda v: (v.outcome.intent.created_at, v.outcome.intent.phase)
        )
        values = tuple(value.outcome for value in completed)
        if any(value.state != "RETURNED" for value in values):
            continue
        if len({digest(value.intent.binding.to_wire()) for value in values}) != 1:
            raise ValueError("同一重领 claim 的知识输入存在不同版本")
        bound = values[0].intent.binding
        claim = by_lease[lease_id]
        step = queue.step_for_claim(claim)
        require_step(item, step)
        if bound.source_revision != fence.start.request.source_revision:
            raise ValueError("重领观察改变原调用的源版本")
        no_start_reader.require_claim_not_started(
            UninvokedClaimBoundary(
                task_id=task.id,
                work_item_id=item.id,
                lease_id=lease_id,
                role=item.role,
                attempt=item.attempt,
                checkpoint_sequence=item.checkpoint_sequence,
                dispatch_sequence=claim.work_item.dispatch_sequence,
                observed_at=max(value.completed_at for value in values),
                run_id=bound.run_id,
                context_manifest_id=bound.context_manifest_id,
            ),
            prior_invocation_fence=fence,
        )
        observation = ReplayGuardedClaimObservation(
            lease_id=lease_id,
            claim_sha256=claim_identity_sha256(claim),
            blocking_start_sha256=fence.start.start_sha256,
            intent_sha256s=tuple(value.intent.intent_sha256 for value in values),
            outcome_sha256s=tuple(value.outcome_sha256 for value in values),
            execution_record_sha256s=tuple(
                record.record_sha256 for value in values for record in value.executions
            ),
            context_sha256s=tuple(value.context_sha256 for value in completed),
            observation_sha256="0" * 64,
        )
        result.append(
            observation.model_copy(
                update={
                    "observation_sha256": digest(
                        observation.model_dump(mode="json", exclude={"observation_sha256"})
                    )
                }
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class _KnowledgeLane:
    records: KnowledgeRecordStore
    lane_id: str
    intents: tuple[KnowledgeInvocationIntent, ...]
    outcomes: tuple[KnowledgeInvocationOutcome, ...]
    observations: tuple[KnowledgeExecutionRecord, ...]
    outcome_map: dict[str, KnowledgeInvocationOutcome]


@dataclass(frozen=True)
class _CompletedKnowledgeInvocation:
    historical: QueueClaim
    outcome: KnowledgeInvocationOutcome
    context_sha256: str


def _knowledge_lanes(
    *, state: Path, task: Task, item: QueuedWorkItem, scope: EngineeringScope, requirement_id: str
) -> tuple[_KnowledgeLane, ...]:
    root = state.parent / "knowledge" / "runs"
    lane_root = root / "invocations"
    if not CapacityInputReader._capacity_ledger_exists(lane_root):
        return ()
    lanes: list[_KnowledgeLane] = []
    # Only the native parent and the documented legacy Task scope are eligible.
    for original_requirement in dict.fromkeys((requirement_id, task.id)):
        lane_id = invocation_scope_lane_sha256(
            team_id=scope.team_id,
            project_id=scope.project_id,
            requirement_id=original_requirement,
            repository_ids=(scope.repository_id,),
            task_id=task.id,
            role=TeamRole(item.role.value),
        )
        lane_path = lane_root / lane_id
        if not CapacityInputReader._capacity_ledger_exists(lane_path):
            continue
        records = KnowledgeRecordStore(lane_path, read_only=True)
        intents = records.list("knowledge-invocation-intents", KnowledgeInvocationIntent, limit=512)
        outcomes = records.list(
            "knowledge-invocation-outcomes", KnowledgeInvocationOutcome, limit=512
        )
        observations = records.list(
            "knowledge-execution-records", KnowledgeExecutionRecord, limit=16384
        )
        for namespace, keyed in (
            (
                "knowledge-invocation-intents",
                tuple((v.binding.run_id + ":" + v.phase, v) for v in intents),
            ),
            (
                "knowledge-invocation-outcomes",
                tuple((v.intent.binding.run_id + ":" + v.intent.phase, v) for v in outcomes),
            ),
            ("knowledge-execution-records", tuple((v.record_sha256, v) for v in observations)),
        ):
            CapacityInputReader.require_record_keys(records, namespace, keyed)
        intent_map = {v.intent_sha256: v for v in intents}
        outcome_map = {v.intent.intent_sha256: v for v in outcomes}
        if len(intent_map) != len(intents) or len(outcome_map) != len(outcomes):
            raise ValueError("知识准备调查发现重复调用或结果")
        if not set(outcome_map) <= set(intent_map) or any(
            v.intent_sha256 not in intent_map for v in observations
        ):
            raise ValueError("知识准备调查发现没有原始调用的结果或执行记录")
        lanes.append(_KnowledgeLane(records, lane_id, intents, outcomes, observations, outcome_map))
    return tuple(lanes)


def _validated_knowledge_invocations(
    *,
    state: Path,
    task: Task,
    scope: EngineeringScope,
    lanes: tuple[_KnowledgeLane, ...],
    queue: KnowledgeProofQueue,
    require_step: Callable[[QueuedWorkItem, QueuedRoleStep], None],
    isolated_lease_ids: frozenset[str] = frozenset(),
) -> tuple[_CompletedKnowledgeInvocation, ...]:
    result: list[_CompletedKnowledgeInvocation] = []
    snapshots = KnowledgeRecordStore(state.parent / "knowledge" / "runs", read_only=True)
    for lane in lanes:
        records, lane_id = lane.records, lane.lane_id
        for intent in lane.intents:
            if intent.claim is not None and intent.claim.lease.id in isolated_lease_ids:
                continue
            intent.validate_integrity()
            if invocation_lane_sha256(intent.binding) != lane_id:
                raise ValueError("知识准备原调用不属于精确组织、项目和需求")
            outcome = lane.outcome_map.get(intent.intent_sha256)
            if outcome is None:
                raise ValueError("知识准备原调用缺少完整结果, 不能证明主岗位未启动")
            KnowledgeInvocationJournal._require_outcome(records, intent, outcome)
            actual = tuple(v for v in lane.observations if v.intent_sha256 == intent.intent_sha256)
            if set(v.record_sha256 for v in actual) != set(
                v.record_sha256 for v in outcome.executions
            ):
                raise ValueError("知识准备原调用的独立执行记录不完整或存在未收尾路由")
            claimed = intent.claim
            if claimed is None:
                raise ValueError("知识准备原调用缺少真实历史 claim")
            historical = queue.original_claim(claimed.lease.id)
            require_claim_snapshot(claimed, historical)
            if not outcome.executions:
                raise ValueError("知识准备原调用缺少独立执行观察, 不能证明主岗位未启动")
            for execution in outcome.executions:
                if isinstance(execution.observation, StructuredNativeStopReceipt):
                    NativeCoderContinuation._require_stopped(execution.observation.process_stop)
            step = queue.step_for_claim(historical)
            require_step(historical.work_item, step)
            context_sha256 = require_knowledge_claim_context(
                state, task, historical.work_item, historical, step, intent, snapshots, scope
            )
            result.append(_CompletedKnowledgeInvocation(historical, outcome, context_sha256))
    return tuple(result)


def read_capacity_claim_snapshot(
    *,
    state: Path,
    task: Task,
    marker: ContextCapacityReceipt,
    historical: QueueClaim,
    scope: EngineeringScope,
    requirement_id: str,
    queue: KnowledgeProofQueue,
    require_step: Callable[[QueuedWorkItem, QueuedRoleStep], None],
    isolated_lease_ids: frozenset[str] = frozenset(),
) -> QueueClaim:
    """Recover exact legacy raw claim bytes; successful knowledge grants no failure authority."""
    marker.validate_integrity()
    record = queue.original_claim_record(historical.lease.id)
    require_claim_snapshot(historical, record.claim)
    if record.has_immutable_snapshot:
        raise ValueError("容量停止摘要与不可变首次 claim 不一致, 禁止用知识快照覆盖真实领取记录")
    lanes = _knowledge_lanes(
        state=state,
        task=task,
        item=historical.work_item,
        scope=scope,
        requirement_id=requirement_id,
    )
    completed = _validated_knowledge_invocations(
        state=state,
        task=task,
        scope=scope,
        lanes=lanes,
        queue=queue,
        require_step=require_step,
        isolated_lease_ids=isolated_lease_ids,
    )
    selected = tuple(
        value.outcome for value in completed if value.historical.lease.id == historical.lease.id
    )
    if not selected or any(value.completed_at > marker.observed_at for value in selected):
        raise ValueError("旧容量记录缺少独立封存且已结束的原 claim 完整快照")
    if len({digest(value.intent.binding.to_wire()) for value in selected}) != 1:
        raise ValueError("旧容量原知识准备存在不同版本的完整输入")
    snapshots = tuple(value.intent.claim for value in selected)
    first = snapshots[0]
    if first is None or any(value != first for value in snapshots):
        raise ValueError("旧容量原 claim 完整快照缺失或存在不同版本")
    return require_claim_snapshot(first, historical, expected_sha256=marker.claim_sha256)


def require_knowledge_claim_context(
    state: Path,
    task: Task,
    item: QueuedWorkItem,
    claim: QueueClaim,
    step: QueuedRoleStep,
    intent: KnowledgeInvocationIntent,
    snapshots: KnowledgeRecordStore,
    scope: EngineeringScope,
) -> str:
    bound = intent.binding
    if (
        bound.source_revision != step.boundary.source_revision
        or intent.created_at < claim.claimed_at
        or intent.claim is None
        or claim.lease.id != intent.claim.lease.id
        or scope.repository_root != task.repository
        or item.repository_scopes != (task.repository,)
        or claim.work_item.repository_scopes != (task.repository,)
    ):
        raise ValueError("知识准备原输入与历史源版本、权限范围或 claim 不一致")
    context_root = state.parent / "contexts"
    _reject_symlinks(context_root / f"{bound.context_manifest_id}.json")
    context = FileContextStore(context_root, read_only=True).get(bound.context_manifest_id)
    frozen = snapshots.get("snapshots", bound.snapshot_sha256, KnowledgeSnapshot)
    frozen.validate_integrity()
    if (
        (context.task_id, context.role, context.attempt, context.source_revision)
        != (task.id, item.role, claim.work_item.attempt, step.boundary.source_revision)
        or (frozen.team_id, frozen.project_id, frozen.requirement_id, frozen.repository_ids)
        != (scope.team_id, scope.project_id, bound.requirement_id, (item.repository_id,))
        or frozen.snapshot_sha256 != bound.snapshot_sha256
        or bound.run_id
        != "run_knowledge_" + digest((context.context_id, frozen.snapshot_sha256))[:32]
    ):
        raise ValueError("知识准备原 Context 或冻结知识快照身份不一致")
    original_tasks = tuple(section for section in context.sections if section.name == "task")
    claimed_sections = tuple(
        section for section in context.sections if section.name == "source:execution.claim"
    )
    if (
        len(original_tasks) != 1
        or original_tasks[0].truncated
        or len(claimed_sections) != 1
        or claimed_sections[0].truncated
    ):
        raise ValueError("知识准备原 Context 缺少完整 Task 或真实 claim")
    original = Task.model_validate_json(original_tasks[0].content)
    sealed = TypeAdapter(dict[str, JsonValue]).validate_json(claimed_sections[0].content)
    if (
        not task_matches_dispatch(original, task)
        or original.attempts != claim.work_item.attempt
        or original.status
        is not {
            TeamRole.CODER: TaskStatus.IMPLEMENTING,
            TeamRole.QA: TaskStatus.QA,
            TeamRole.REVIEWER: TaskStatus.REVIEW,
        }[bound.role]
        or claimed_sections[0].uri != "claim://" + claim.lease.id
        or any(
            sealed.get(field) != expected
            for field, expected in {
                "task_id": task.id,
                "work_item_id": item.id,
                "lease_id": claim.lease.id,
                "assignment_id": claim.assignment.id,
                "dispatch_sequence": claim.work_item.dispatch_sequence,
                "role": item.role.value,
                "attempt": claim.work_item.attempt,
                "checkpoint_sequence": item.checkpoint_sequence,
            }.items()
        )
    ):
        raise ValueError("知识准备原 Context 的 Task 或 claim 与冻结意图不一致")
    return digest(context.to_wire())
