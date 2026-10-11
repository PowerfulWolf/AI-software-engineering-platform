"""Read exact sealed knowledge stops and finite consumed-window lineage."""

from __future__ import annotations

from pathlib import Path

from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured_observation import StructuredNativeStopReceipt
from ai_software_engineer.domain.delivery_resolution import KnowledgePreparationRetryEvidence
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationIntent,
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem


class KnowledgeWindowExhausted(ValueError):
    """The frozen two-extension window has no safe next local execution."""


def claim_identity_sha256(claim: QueueClaim) -> str:
    """Heartbeat expiry and mutable queue status cannot change original ownership."""
    item = claim.work_item
    return digest(
        {
            "work_item": item.model_dump(
                mode="json",
                exclude={"status", "updated_at", "available_at", "wait_reason", "wait_disposition"},
            ),
            "assignment": claim.assignment.to_wire(),
            "lease": claim.lease.model_dump(mode="json", exclude={"expires_at"}),
            "model_selection": claim.model_selection.to_wire(),
            "worker_id": claim.worker_id,
            "claimed_at": claim.claimed_at.isoformat(),
        }
    )


def read_local_limit(records_root: Path, outcome_sha256: str) -> KnowledgeInvocationOutcome:
    records = KnowledgeRecordStore(records_root, read_only=True)
    intent = records.get("knowledge-local-limit-intents", outcome_sha256, KnowledgeInvocationIntent)
    intent.validate_integrity()
    lane = KnowledgeRecordStore(
        records_root / "invocations" / invocation_lane_sha256(intent.binding), read_only=True
    )
    key = intent.binding.run_id + ":" + intent.phase
    if lane.get("knowledge-invocation-intents", key, KnowledgeInvocationIntent) != intent:
        raise KnowledgeError("KNOWLEDGE_LIMIT_INTENT_CHANGED")
    outcome = lane.get("knowledge-invocation-outcomes", key, KnowledgeInvocationOutcome)
    KnowledgeInvocationJournal._require_outcome(lane, intent, outcome)
    failure = outcome.failure
    if (
        outcome.outcome_sha256 != outcome_sha256
        or outcome.state != "FAILED"
        or failure is None
        or failure.code is not AgentErrorCode.TIMEOUT
        or failure.timeout_kind != "local_execution_limit"
        or failure.transient
    ):
        raise KnowledgeError("KNOWLEDGE_LIMIT_OUTCOME_CHANGED")
    stops = tuple(
        record.observation
        for record in outcome.executions
        if isinstance(record.observation, StructuredNativeStopReceipt)
    )
    if not stops or stops[-1].process_stop.kind != "local_execution_limit":
        raise KnowledgeError("KNOWLEDGE_LIMIT_NATIVE_STOP_REQUIRED")
    for stopped in stops:
        NativeCoderContinuation._require_stopped(stopped.process_stop)
    return outcome


def preparation_retry_evidence(
    *,
    outcome: KnowledgeInvocationOutcome,
    task: Task,
    item: QueuedWorkItem,
    source_revision: str,
    scope: EngineeringScope,
    historical_claim: QueueClaim,
    previous: KnowledgePreparationRetryEvidence | None,
    delivery_requirement_id: str | None = None,
) -> KnowledgePreparationRetryEvidence:
    intent, bound = outcome.intent, outcome.intent.binding
    claimed = intent.claim
    if claimed is None or (
        claim_identity_sha256(claimed) != claim_identity_sha256(historical_claim)
        or (
            claimed.work_item.id,
            claimed.work_item.task_id,
            claimed.work_item.repository_id,
            claimed.work_item.role,
            claimed.work_item.attempt,
            claimed.work_item.checkpoint_sequence,
        )
        != (item.id, task.id, item.repository_id, item.role, item.attempt, item.checkpoint_sequence)
        or (
            bound.team_id,
            bound.project_id,
            bound.repository_ids,
            bound.task_id,
            bound.role.value,
            bound.source_revision,
        )
        != (
            scope.team_id,
            scope.project_id,
            (scope.repository_id,),
            task.id,
            item.role.value,
            source_revision,
        )
        or scope.repository_root != task.repository
        or item.repository_id != scope.repository_id
        or claimed.work_item.repository_scopes != (task.repository,)
        or item.repository_scopes != (task.repository,)
    ):
        raise KnowledgeError("KNOWLEDGE_LIMIT_CLAIM_OR_SCOPE_CHANGED")
    initial = intent.timeout_seconds
    root = intent.intent_sha256
    expansion = 1
    if previous is not None:
        if (
            previous.scope != scope
            or previous.task_id != task.id
            or previous.role is not item.role
            or previous.requirement_id != bound.requirement_id
            or (previous.delivery_requirement_id or previous.requirement_id)
            != (delivery_requirement_id or bound.requirement_id)
            or previous.source_revision != source_revision
            or previous.snapshot_sha256 != bound.snapshot_sha256
            or previous.next_timeout_seconds != intent.timeout_seconds
        ):
            raise KnowledgeError("KNOWLEDGE_LIMIT_WINDOW_LINEAGE_CHANGED")
        initial, root = previous.initial_timeout_seconds, previous.root_intent_sha256
        expansion = previous.expansion_number + 1
    maximum = min(initial * 4, 86_400)
    if expansion > 2 or intent.timeout_seconds >= maximum:
        raise KnowledgeWindowExhausted("知识准备已达到冻结的扩窗上限, 不再重复执行。")
    return KnowledgePreparationRetryEvidence(
        scope=scope,
        requirement_id=bound.requirement_id,
        delivery_requirement_id=delivery_requirement_id,
        task_id=task.id,
        role=item.role,
        work_item_id=item.id,
        original_lease_id=claimed.lease.id,
        original_claim_sha256=claim_identity_sha256(claimed),
        original_attempt=claimed.work_item.attempt,
        original_dispatch_sequence=claimed.work_item.dispatch_sequence,
        checkpoint_sequence=item.checkpoint_sequence,
        previous_run_id=bound.run_id,
        previous_context_manifest_id=bound.context_manifest_id,
        source_revision=source_revision,
        snapshot_sha256=bound.snapshot_sha256,
        phase=intent.phase,
        intent_sha256=intent.intent_sha256,
        outcome_sha256=outcome.outcome_sha256,
        request_sha256=intent.request_sha256,
        execution_record_sha256s=tuple(record.record_sha256 for record in outcome.executions),
        root_intent_sha256=root,
        initial_timeout_seconds=initial,
        current_timeout_seconds=intent.timeout_seconds,
        next_timeout_seconds=min(intent.timeout_seconds * 2, maximum),
        maximum_timeout_seconds=maximum,
        expansion_number=expansion,
    )
