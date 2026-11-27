"""Rejected QA/Reviewer output rerun proof (``RETRY_REJECTED_VERIFIER_OUTPUT``).

The proof binds facts the platform already sealed: the original claimed verifier
invocation, its nontransient contract-rejected FAILED outcome, a typed execution
stop, the unchanged Coder candidate, the frozen Plan and accepted inputs. It never
accepts the rejected output, grants a verdict, refunds work or schedules Coder.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from ai_software_engineer.agents.execution import ExecutionStop
from ai_software_engineer.agents.models import AgentErrorCode, AgentRunStatus
from ai_software_engineer.artifacts import ArtifactStore, artifact_digest
from ai_software_engineer.domain.artifact import ImplementationReportArtifact, QaReportArtifact
from ai_software_engineer.domain.delivery_resolution import RejectedVerifierOutputEvidence
from ai_software_engineer.domain.enums import AgentRole, QaReportStatus, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard

VERIFIER_STAGES: dict[AgentRole, TaskStatus] = {
    AgentRole.QA: TaskStatus.QA,
    AgentRole.REVIEWER: TaskStatus.REVIEW,
}

# Trusted reader of the original Run's typed stop. It must return only an actual
# NativeProcessStop or synchronous completion receipt; lease expiry is never a stop.
VerifierStopReader = Callable[
    [Task, QueuedRoleStep, DeliveryInvocationStart, WorkerExecutionGuard], ExecutionStop | None
]


class VerifierStopUncertain(ValueError):
    """The original verifier execution may still be live or its stop is unknown."""


class VerifierRerunQueue(Protocol):
    def original_claim(self, lease_id: str) -> QueueClaim: ...
    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]: ...


def rejected_verifier_output_candidate(
    item: QueuedWorkItem,
    task: Task,
    start: DeliveryInvocationStart,
    outcome: DeliveryInvocationOutcome,
) -> bool:
    """Exact wait shape only; complete independent facts are still required."""
    disposition = item.wait_disposition
    error = outcome.result.error
    return (
        disposition is not None
        and item.role in VERIFIER_STAGES
        and task.status is VERIFIER_STAGES[item.role]
        and disposition.facts.role is item.role
        and disposition.facts.classification == "INVALID_OUTPUT"
        and not any(
            value.startswith("knowledge-assessment-rejection://")
            for value in disposition.facts.evidence_ids
        )
        and outcome.start == start
        and outcome.service_pause is None
        and outcome.result.status is AgentRunStatus.FAILED
        and outcome.result.artifact is None
        and error is not None
        and error.code is AgentErrorCode.INVALID_OUTPUT
        and not error.transient
    )


def _require_stopped(stop: ExecutionStop | None, start: DeliveryInvocationStart) -> ExecutionStop:
    if stop is None:
        raise ValueError("original verifier execution has no typed stop receipt")
    try:
        stop.validate_integrity()
        NativeCoderContinuation._require_stopped(stop, start.request)
    except (ContinuationRejected, ValueError) as error:
        raise VerifierStopUncertain("original verifier execution stop is not proven") from error
    if stop.stopped_at < start.started_at:
        raise VerifierStopUncertain("verifier stop predates its original invocation")
    return stop


def rejected_verifier_output_evidence(
    *,
    item: QueuedWorkItem,
    step: QueuedRoleStep,
    task: Task,
    start: DeliveryInvocationStart,
    outcome: DeliveryInvocationOutcome,
    queue: VerifierRerunQueue,
    artifacts: ArtifactStore,
    events: Sequence[StateEvent],
    stop: ExecutionStop | None,
) -> RejectedVerifierOutputEvidence:
    """Independently derive the rerun proof or raise; never mutates any record."""
    if not rejected_verifier_output_candidate(item, task, start, outcome):
        raise ValueError("wait is not a rejected QA/Reviewer output")
    request = start.request
    candidate = step.boundary.source_revision
    if (
        start.work_item_id != item.id
        or start.checkpoint_sequence != item.checkpoint_sequence
        or start.checkpoint_sequence != step.boundary.checkpoint_sequence
        or (request.task_id, request.role, request.attempt, request.source_revision)
        != (task.id, item.role, item.attempt, candidate)
        or request.attempt != task.attempts
    ):
        raise ValueError("original verifier invocation does not bind this wait")
    claim = queue.original_claim(start.lease_id)
    if (
        claim.work_item.id,
        claim.work_item.task_id,
        claim.work_item.repository_id,
        claim.work_item.role,
        claim.work_item.attempt,
        claim.work_item.checkpoint_sequence,
        claim.work_item.dispatch_sequence,
    ) != (
        item.id,
        task.id,
        item.repository_id,
        item.role,
        item.attempt,
        item.checkpoint_sequence,
        item.dispatch_sequence,
    ):
        raise ValueError("original verifier claim does not bind this wait")
    accepted = queue.accepted(task.id)
    if any(
        record.work_item_id == item.id or record.run_id == request.run_id for record in accepted
    ):
        raise ValueError("original verifier work already has an accepted publication")
    handoffs = [
        event
        for event in events
        if event.from_status is TaskStatus.IMPLEMENTING and event.to_status is TaskStatus.QA
    ]
    if not handoffs:
        raise ValueError("candidate has no durable IMPLEMENTING to QA handoff")
    implementations: list[tuple[ImplementationReportArtifact, AcceptedRoleArtifact]] = []
    for record in accepted:
        if record.receipt.artifact_id not in handoffs[-1].artifact_ids:
            continue
        artifact = artifacts.get(record.receipt.artifact_id)
        if (
            isinstance(artifact, ImplementationReportArtifact)
            and artifact.content.commit_sha == candidate
            and artifact_digest(artifact) == record.receipt.sha256
        ):
            implementations.append((artifact, record))
    if len(implementations) != 1:
        raise ValueError("candidate has no unique accepted implementation report")
    implementation, implementation_record = implementations[0]
    frozen_plan_ids = {
        artifact_id
        for event in events
        if event.from_status is TaskStatus.PLANNING and event.to_status is TaskStatus.IMPLEMENTING
        for artifact_id in event.artifact_ids
    }
    plans = [
        plan
        for plan in (
            artifacts.get(parent)
            for parent in implementation.parent_artifact_ids
            if parent in frozen_plan_ids
        )
        if plan.kind == "plan"
    ]
    if len(plans) != 1:
        raise ValueError("implementation does not bind one frozen Plan")
    plan = plans[0]
    qa_artifact_id: str | None = None
    qa_artifact_sha256: str | None = None
    if item.role is AgentRole.REVIEWER:
        passes = [
            event
            for event in events
            if event.from_status is TaskStatus.QA
            and event.to_status is TaskStatus.REVIEW
            and event.reason == "qa_passed"
        ]
        if not passes:
            raise ValueError("Reviewer rerun has no durable qa_passed handoff")
        qa_reports: list[AcceptedRoleArtifact] = []
        for record in accepted:
            if record.receipt.artifact_id not in passes[-1].artifact_ids:
                continue
            report = artifacts.get(record.receipt.artifact_id)
            if (
                isinstance(report, QaReportArtifact)
                and report.content.status is QaReportStatus.PASS
                and report.source_revision == candidate
                and artifact_digest(report) == record.receipt.sha256
            ):
                qa_reports.append(record)
        if len(qa_reports) != 1:
            raise ValueError("Reviewer rerun has no unique accepted QA PASS")
        qa_artifact_id = qa_reports[0].receipt.artifact_id
        qa_artifact_sha256 = qa_reports[0].receipt.sha256
    verified_stop = _require_stopped(stop, start)
    return RejectedVerifierOutputEvidence.model_validate(
        {
            "task_id": task.id,
            "work_item_id": item.id,
            "role": item.role,
            "candidate_revision": candidate,
            "plan_artifact_id": plan.artifact_id,
            "plan_artifact_sha256": artifact_digest(plan),
            "implementation_artifact_id": implementation.artifact_id,
            "implementation_artifact_sha256": implementation_record.receipt.sha256,
            "accepted_qa_artifact_id": qa_artifact_id,
            "accepted_qa_artifact_sha256": qa_artifact_sha256,
            "original_lease_id": start.lease_id,
            "original_claim_sha256": digest(claim.to_wire()),
            "original_attempt": request.attempt,
            "original_dispatch_sequence": claim.work_item.dispatch_sequence,
            "checkpoint_sequence": start.checkpoint_sequence,
            "previous_run_id": request.run_id,
            "previous_context_manifest_id": request.context_manifest_id,
            "invocation_start_sha256": start.start_sha256,
            "invocation_outcome_sha256": outcome.outcome_sha256,
            "execution_stop_sha256": verified_stop.stop_sha256,
        }
    )


class VerifierRerunAdmissionRejected(ValueError):
    """A consumed verifier rerun decision no longer matches the current claim facts."""


def verify_rejected_verifier_rerun_claim(
    *,
    evidence: RejectedVerifierOutputEvidence,
    claim: QueueClaim,
    task: Task,
    accepted: Sequence[AcceptedRoleArtifact],
    run_id: str | None = None,
    context_manifest_id: str | None = None,
) -> RejectedVerifierOutputEvidence:
    """Fail closed before any model call unless the successor claim is exactly bound.

    The rerun keeps the same Coder candidate and accepted inputs; it never schedules
    Coder, never reruns QA for a Reviewer rerun and never reuses the old identity.
    """
    item = claim.work_item
    if (
        item.role is not evidence.role
        or item.task_id != evidence.task_id
        or task.id != evidence.task_id
        or item.id == evidence.work_item_id
        or item.parent_work_item_id != evidence.work_item_id
        or claim.lease.id == evidence.original_lease_id
        or item.attempt != evidence.original_attempt + 1
        or task.attempts != item.attempt
        or item.checkpoint_sequence != evidence.checkpoint_sequence
        or task.status is not VERIFIER_STAGES[evidence.role]
    ):
        raise VerifierRerunAdmissionRejected("审查角色重跑的当前领取不属于已消费决定")
    if run_id is not None and run_id == evidence.previous_run_id:
        raise VerifierRerunAdmissionRejected("审查角色重跑不能复用原执行身份")
    if (
        context_manifest_id is not None
        and context_manifest_id == evidence.previous_context_manifest_id
    ):
        raise VerifierRerunAdmissionRejected("审查角色重跑不能复用原上下文")
    if any(
        record.work_item_id in {item.id, evidence.work_item_id}
        or record.run_id == evidence.previous_run_id
        for record in accepted
    ):
        raise VerifierRerunAdmissionRejected("审查角色重跑的原执行或当前工作项已有接纳产物")
    required = [(evidence.implementation_artifact_id, evidence.implementation_artifact_sha256)]
    if evidence.role is AgentRole.REVIEWER:
        if evidence.accepted_qa_artifact_id is None or evidence.accepted_qa_artifact_sha256 is None:
            raise VerifierRerunAdmissionRejected("Reviewer 重跑缺少原已接纳 QA PASS")
        required.append((evidence.accepted_qa_artifact_id, evidence.accepted_qa_artifact_sha256))
    for artifact_id, sha256 in required:
        if (
            sum(
                record.receipt.artifact_id == artifact_id and record.receipt.sha256 == sha256
                for record in accepted
            )
            != 1
        ):
            raise VerifierRerunAdmissionRejected("审查角色重跑的候选或已接纳输入已变化")
    return evidence
