"""Collect a positively refused knowledge preparation without inventing a main stop."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast

from ai_software_engineer.agents.structured_observation import StructuredNativeStopReceipt
from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.knowledge_preparation_pause import (
    KnowledgePreparationPauseEvidence,
)
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    knowledge_pause_proof_mode,
    read_paused_preparation,
)
from ai_software_engineer.knowledge.legacy_scope import require_delivery_requirement_scope
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.capacity_input_reader import (
    CapacityInputReader,
    UninvokedClaimBoundary,
)
from ai_software_engineer.manager.knowledge_invocation_proof import (
    _knowledge_lanes,
    require_knowledge_claim_context,
)
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.work_queue.claim_snapshot import require_claim_snapshot
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem


class KnowledgePauseQueue(Protocol):
    def original_claim(self, lease_id: str) -> QueueClaim: ...
    def claims_for_work_item(self, work_item_id: str) -> tuple[QueueClaim, ...]: ...
    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]: ...
    def step_for_invocation(
        self, work_item_id: str, baseline_sha256: str | None
    ) -> QueuedRoleStep: ...


def knowledge_preparation_pause_evidence(
    *,
    outcome: KnowledgeInvocationOutcome,
    task: Task,
    item: QueuedWorkItem,
    step: QueuedRoleStep,
    scope: EngineeringScope,
    state: Path,
    route_root: Path,
    queue: KnowledgePauseQueue,
    artifacts: ArtifactStore,
    delivery_requirement_id: str,
) -> KnowledgePreparationPauseEvidence:
    """Independently reread current ownership, full preparation and main-call absence."""
    records_root = state.parent / "knowledge/runs"
    if read_paused_preparation(records_root, outcome.outcome_sha256) != outcome:
        raise ValueError("知识暂停原结果与独立封存事实已变化")
    intent = outcome.intent
    original = intent.claim
    if original is None:
        raise ValueError("知识暂停缺少原真实 claim")
    historical = queue.original_claim(original.lease.id)
    require_claim_snapshot(original, historical)
    bound = intent.binding
    expected_status = {
        AgentRole.CODER: TaskStatus.IMPLEMENTING,
        AgentRole.QA: TaskStatus.QA,
        AgentRole.REVIEWER: TaskStatus.REVIEW,
    }.get(item.role)
    claims = tuple(
        sorted(queue.claims_for_work_item(item.id), key=lambda v: v.work_item.dispatch_sequence)
    )
    if (
        expected_status is None
        or task.status is not expected_status
        or bound.task_id != task.id
        or bound.role.value != item.role.value
        or (bound.team_id, bound.project_id, bound.repository_ids)
        != (scope.team_id, scope.project_id, (scope.repository_id,))
        or task.repository != scope.repository_root
        or item.repository_id != scope.repository_id
        or bound.source_revision != step.boundary.source_revision
        or item.attempt != task.attempts
        or item.checkpoint_sequence != step.boundary.checkpoint_sequence
        or (
            original.work_item.id,
            original.work_item.task_id,
            original.work_item.role,
            original.work_item.attempt,
            original.work_item.checkpoint_sequence,
            original.work_item.dispatch_sequence,
            original.work_item.repository_id,
            original.work_item.repository_scopes,
        )
        != (
            item.id,
            task.id,
            item.role,
            item.attempt,
            item.checkpoint_sequence,
            item.dispatch_sequence,
            item.repository_id,
            item.repository_scopes,
        )
        or not claims
        or len(claims) > 512
        or claims[-1].lease.id != original.lease.id
        or len({value.work_item.dispatch_sequence for value in claims}) != len(claims)
        or any(
            (
                value.work_item.id,
                value.work_item.task_id,
                value.work_item.role,
                value.work_item.attempt,
                value.work_item.checkpoint_sequence,
                value.work_item.repository_id,
                value.work_item.repository_scopes,
            )
            != (
                item.id,
                task.id,
                item.role,
                item.attempt,
                item.checkpoint_sequence,
                item.repository_id,
                item.repository_scopes,
            )
            for value in claims
        )
        or any(record.work_item_id == item.id for record in queue.accepted(task.id))
    ):
        raise ValueError("知识暂停的任务、范围、领取世代或接纳事实已变化")
    records = KnowledgeRecordStore(records_root, read_only=True)
    require_delivery_requirement_scope(bound, delivery_requirement_id, records=records)
    require_knowledge_claim_context(state, task, item, historical, step, intent, records, scope)
    # Read both native Requirement and documented legacy lanes. A different Run,
    # phase or filename cannot conceal an unfinished call for this same claim.
    found = False
    for lane in _knowledge_lanes(
        state=state,
        task=task,
        item=item,
        scope=scope,
        requirement_id=delivery_requirement_id,
    ):
        for other in lane.intents:
            claimed = other.claim
            if claimed is None or claimed.lease.id != original.lease.id:
                continue
            require_claim_snapshot(claimed, historical)
            if other.binding != bound:
                raise ValueError("知识暂停的同一 claim 含不同知识输入")
            sealed = lane.outcome_map.get(other.intent_sha256)
            if sealed is None:
                raise ValueError("知识暂停的同一 claim 仍有未收尾调用")
            KnowledgeInvocationJournal._require_outcome(lane.records, other, sealed)
            actual = tuple(
                value.record_sha256
                for value in lane.observations
                if value.intent_sha256 == other.intent_sha256
            )
            if set(actual) != {value.record_sha256 for value in sealed.executions}:
                raise ValueError("知识暂停的独立执行记录不完整或存在额外路由")
            if other == intent:
                if sealed != outcome or found:
                    raise ValueError("知识暂停的精确原调用存在冲突")
                found = True
                continue
            # An earlier phase is allowed only when its actual independent
            # executions are complete and RETURNED before the refusal began.
            if (
                sealed.state != "RETURNED"
                or not sealed.executions
                or sealed.completed_at > intent.created_at
            ):
                raise ValueError("知识暂停不能覆盖同一 claim 的失败或未知调用")
            for execution in sealed.executions:
                if isinstance(execution.observation, StructuredNativeStopReceipt):
                    NativeCoderContinuation._require_stopped(execution.observation.process_stop)
    if not found:
        raise ValueError("知识暂停调查没有完整原调用")
    reader = CapacityInputReader(
        state=state,
        queue=queue,
        artifacts=artifacts,
        route_root=route_root,
        baselines=None,
    )
    for claimed in claims:
        require_claim_snapshot(claimed, queue.original_claim(claimed.lease.id))
        reader.require_claim_not_started(
            UninvokedClaimBoundary(
                task_id=task.id,
                work_item_id=item.id,
                lease_id=claimed.lease.id,
                role=item.role,
                attempt=item.attempt,
                checkpoint_sequence=item.checkpoint_sequence,
                dispatch_sequence=claimed.work_item.dispatch_sequence,
                observed_at=datetime.now(UTC),
                run_id=bound.run_id,
                context_manifest_id=bound.context_manifest_id,
            )
        )
    return KnowledgePreparationPauseEvidence(
        scope=scope,
        requirement_id=bound.requirement_id,
        delivery_requirement_id=delivery_requirement_id,
        task_id=task.id,
        role=cast(Literal[AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER], item.role),
        work_item_id=item.id,
        original_lease_id=original.lease.id,
        original_claim_sha256=claim_identity_sha256(original),
        original_attempt=original.work_item.attempt,
        original_dispatch_sequence=original.work_item.dispatch_sequence,
        checkpoint_sequence=item.checkpoint_sequence,
        previous_run_id=bound.run_id,
        previous_context_manifest_id=bound.context_manifest_id,
        source_revision=bound.source_revision,
        snapshot_sha256=bound.snapshot_sha256,
        phase=intent.phase,
        intent_sha256=intent.intent_sha256,
        outcome_sha256=outcome.outcome_sha256,
        request_sha256=intent.request_sha256,
        proof_mode=knowledge_pause_proof_mode(outcome),
        pre_admission_pause_sha256=(
            outcome.pre_admission_pause.receipt_sha256 if outcome.pre_admission_pause else None
        ),
        execution_record_sha256s=tuple(value.record_sha256 for value in outcome.executions),
    )
