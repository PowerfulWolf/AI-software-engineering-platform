"""Transactional acceptance and immutable inputs for production role Workers.

The queue owns scheduling facts; TaskOrchestrator still owns verdict validation.
Filesystem output becomes recoverable only after an owner-fenced receipt commits.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol, Self, cast, runtime_checkable

from pydantic import JsonValue, TypeAdapter, ValidationError, model_validator
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.models import AgentRunStatus
from ai_software_engineer.artifacts import ArtifactStore, artifact_digest
from ai_software_engineer.artifacts.ports import ArtifactRef
from ai_software_engineer.domain.artifact import Artifact, QaReportArtifact, Sha256
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import DeliveryDisposition
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    KnowledgePreparationRetryEvidence,
    RejectedCoderOutputEvidence,
    RejectedKnowledgePreparationEvidence,
    rejected_knowledge_wait_matches,
)
from ai_software_engineer.domain.engineering_authority import EngineeringCapability
from ai_software_engineer.domain.enums import AgentRole, QaReportStatus, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.identity import ContextId, RepositoryId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.native_verification import NativeVerificationWaitReason
from ai_software_engineer.domain.stopped_budget_settlement import StoppedFailureBudgetSettlement
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.domain.workforce import (
    LeaseId,
    RoleAssignment,
    TaskLease,
    validate_assignment_independence,
)
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGap,
    KnowledgeGapRouting,
    KnowledgeResolution,
)
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.state_machine import apply_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store.mysql_repository import _decode_task, _encode, open_mysql_connection
from ai_software_engineer.work_queue.claim_snapshot import (
    OriginalClaimRecord,
    require_claim_snapshot,
)
from ai_software_engineer.work_queue.models import (
    CheckpointSequence,
    QueueArtifactReceipt,
    QueueClaim,
    QueueCompletion,
    QueuedWorkItem,
    WorkItemId,
)
from ai_software_engineer.work_queue.mysql import MySqlPersistentWorkQueue
from ai_software_engineer.work_queue.ports import (
    QueueConflict,
    QueueCorruption,
    QueueLeaseLost,
    QueueNotFound,
)

if TYPE_CHECKING:
    from ai_software_engineer.agents.models import AgentRequest
    from ai_software_engineer.domain.contained_unknown_budget import (
        ContainedUnknownBudgetSettlement,
    )
    from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
    from ai_software_engineer.domain.stopped_unknown_budget import StoppedUnknownBudgetSettlement
    from ai_software_engineer.manager.baseline_models import BaselineContinueAuthorization
    from ai_software_engineer.manager.rejected_candidate_output import RejectedCandidateOutputProof
    from ai_software_engineer.manager.rejected_candidate_owner import (
        RejectedCandidateExpiredOwnerSettlement,
        TaskProcessLockGuard,
    )
    from ai_software_engineer.manager.verifier_preparation import (
        VerifierPreparationIntent,
        VerifierPreparationObservation,
    )


def record_digest(value: DomainModel) -> str:
    return hashlib.sha256(
        json.dumps(
            value.to_wire(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


class RoleQueueAdmission(DomainModel):
    kind: Literal["role_queue_admission"] = "role_queue_admission"
    task_id: TaskId
    repository_id: RepositoryId
    allocation_sha256: Sha256
    legacy_artifacts: tuple[QueueArtifactReceipt, ...]

    @model_validator(mode="after")
    def unique_receipts(self) -> Self:
        ensure_unique((r.artifact_id for r in self.legacy_artifacts), "legacy Artifact IDs")
        return self


class QueuedRoleStep(DomainModel):
    kind: Literal["queued_role_step"] = "queued_role_step"
    work_item: QueuedWorkItem
    boundary: RoleRunBoundary
    allocation_sha256: Sha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        item, boundary = self.work_item, self.boundary
        if (item.task_id, item.role, item.attempt, item.checkpoint_sequence) != (
            boundary.task_id,
            boundary.role,
            boundary.attempt,
            boundary.checkpoint_sequence,
        ):
            raise ValueError("queued step does not bind its work item")
        return self


class AcceptedRoleArtifact(DomainModel):
    kind: Literal["accepted_role_artifact"] = "accepted_role_artifact"
    task_id: TaskId
    work_item_id: WorkItemId
    lease_id: LeaseId
    dispatch_sequence: CheckpointSequence
    checkpoint_sequence: CheckpointSequence
    run_id: RunId
    context_manifest_id: ContextId
    source_revision: NonEmptyStr
    receipt: QueueArtifactReceipt


@runtime_checkable
class RetiredRejectedOutputReader(Protocol):
    def retired_rejected_outputs(self, task_id: str) -> tuple[RejectedCoderOutputEvidence, ...]: ...


def is_retired_rejected_publication(
    publication: AcceptedRoleArtifact,
    retired: tuple[RejectedCoderOutputEvidence, ...],
    *,
    current_work_item_id: str,
    current_run_id: str | None,
    checkpoint_sequence: int,
) -> bool:
    """Exclude only the exact publication retired by a consumed typed decision."""
    if (
        publication.work_item_id == current_work_item_id
        or current_run_id is None
        or publication.run_id == current_run_id
        or publication.checkpoint_sequence > checkpoint_sequence
    ):
        return False
    return any(
        (
            publication.task_id,
            publication.work_item_id,
            publication.lease_id,
            publication.dispatch_sequence,
            publication.checkpoint_sequence,
            publication.run_id,
            publication.context_manifest_id,
            publication.source_revision,
            publication.receipt.artifact_id,
            publication.receipt.sha256,
        )
        == (
            evidence.task_id,
            evidence.work_item_id,
            evidence.original_lease_id,
            evidence.original_dispatch_sequence,
            evidence.checkpoint_sequence,
            evidence.previous_run_id,
            evidence.previous_context_manifest_id,
            evidence.source_revision,
            evidence.rejected_artifact_id,
            evidence.rejected_artifact_sha256,
        )
        for evidence in retired
    )


class _RejectedOutputResolutionDetail(DomainModel):
    resolution_sha256: Sha256
    next_work_item_id: WorkItemId
    resolution: DeliveryResolution
    budget_refund: Literal[False]


class _RejectedOutputResolutionEvent(DomainModel):
    work_item: QueuedWorkItem
    detail: _RejectedOutputResolutionDetail


@dataclass(frozen=True)
class WorkforceFacts:
    assignments: tuple[RoleAssignment, ...] = ()
    leases: tuple[TaskLease, ...] = ()
    adopted_task_ids: frozenset[str] = frozenset()


CapacityReader = Callable[[DictCursor, datetime], WorkforceFacts]
AuthorityLock = Callable[[DictCursor], None]
_TABLES = (
    "work_queue_admissions",
    "work_queue_steps",
    "work_queue_accepted_artifacts",
    "work_queue_execution_baselines",
    "work_queue_baseline_releases",
)
_CANCELLATION_DIGEST = TypeAdapter(Sha256)
_TERMINAL_TASK_STATUSES = frozenset({TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.DONE})


def read_queue_workforce(cursor: DictCursor, now: datetime) -> WorkforceFacts:
    """Read-only compatibility seam; absence means no queue adoption has occurred."""
    cursor.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='work_queue_admissions'"
    )
    table_row = cursor.fetchone()
    if table_row is None:
        return WorkforceFacts()
    if table_row.get("TABLE_NAME") != "work_queue_admissions":
        raise QueueCorruption("unexpected queue table discovery row")
    cursor.execute("SELECT id,task_id,payload_json,sha256 FROM work_queue_admissions")
    adopted = frozenset(_decode(row, RoleQueueAdmission).task_id for row in cursor.fetchall())
    cursor.execute("SELECT assignment_json,lease_json,state,expires_at FROM work_queue_claims")
    assignments, leases = [], []
    for row in cursor.fetchall():
        assignment = RoleAssignment.model_validate_json(row["assignment_json"])
        lease = TaskLease.model_validate_json(row["lease_json"])
        if lease.assignment_id != assignment.id or lease.agent_id != assignment.agent_id:
            raise QueueCorruption("queue workforce identity mismatch")
        assignments.append(assignment)
        if row["state"] == "ACTIVE" and lease.expires_at > now:
            leases.append(lease)
    return WorkforceFacts(tuple(assignments), tuple(leases), adopted)


class MySqlRoleQueue(MySqlPersistentWorkQueue):
    def consumed_recovery_input_resolution(self, task_id: str) -> DeliveryResolution | None:
        """Return only a genuinely consumed same-Task input schedule decision."""
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT e.payload_json FROM work_queue_events AS e "
                "JOIN work_queue_items AS i ON i.id=e.work_item_id "
                "WHERE i.task_id=%s AND e.event_type='WAIT_RESOLVED' ORDER BY e.sequence",
                (task_id,),
            )
            rows = cursor.fetchall()
        decisions: list[DeliveryResolution] = []
        try:
            for row in rows:
                event = _RejectedOutputResolutionEvent.model_validate_json(str(row["payload_json"]))
                detail, decision = event.detail, event.detail.resolution
                decision.validate_integrity()
                if (
                    detail.resolution_sha256 != decision.resolution_sha256
                    or event.work_item.task_id != task_id
                    or detail.budget_refund
                ):
                    raise ValueError("consumed wait event changed its exact decision")
                if decision.resolution_kind is not DeliveryResolutionKind.SCHEDULE_RECOVERY_INPUT:
                    continue
                if detail.next_work_item_id != event.work_item.id:
                    raise ValueError("consumed recovery schedule changed its WorkItem")
                original = decision.pre_context_recovery_input
                if (
                    original is None
                    or decision.task_id != task_id
                    or decision.work_item_id != event.work_item.id
                    or event.work_item.status is not WorkItemStatus.READY
                    or event.work_item.dispatch_sequence < 1
                ):
                    raise ValueError("consumed recovery schedule changed its original wait")
                claim = self.original_claim(original.original_lease_id)
                if (
                    digest(claim.to_wire()) != original.original_claim_sha256
                    or claim.work_item.id != decision.work_item_id
                    or claim.work_item.dispatch_sequence + 1 != event.work_item.dispatch_sequence
                    or claim.work_item.checkpoint_sequence != event.work_item.checkpoint_sequence
                ):
                    raise ValueError("consumed recovery schedule changed its original claim")
                decisions.append(decision)
        except (ValueError, TypeError, KeyError, ValidationError) as error:
            raise QueueCorruption(
                "recovery input schedule consumption evidence is invalid"
            ) from error
        if len(decisions) > 1:
            raise QueueCorruption("Task has duplicate consumed recovery input schedules")
        return decisions[0] if decisions else None

    def static_qa_resolution_for_wait(
        self,
        item: QueuedWorkItem,
        *,
        knowledge_records: KnowledgeRecordStore | None = None,
        accepted_output: AcceptedRoleArtifact | None = None,
    ) -> DeliveryResolution | None:
        """Read a prior consumed static decision while the same QA item is waiting."""
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            current = self._get_locked(cursor, item.id, lock=False)
            if current != item or current.status not in {
                WorkItemStatus.WAITING_HUMAN,
                WorkItemStatus.WAITING_DEPENDENCY,
            }:
                raise QueueConflict("static QA wait changed during inspection")
            cursor.execute(
                "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
                "AND event_type='WAIT_RESOLVED' ORDER BY sequence LIMIT 3",
                (item.id,),
            )
            rows = cursor.fetchall()
            if len(rows) > 2:
                raise QueueCorruption("static QA wait has excessive consumed decisions")
            decisions = []
            for row in rows:
                event = _RejectedOutputResolutionEvent.model_validate_json(str(row["payload_json"]))
                event.detail.resolution.validate_integrity()
                if event.detail.resolution_sha256 != event.detail.resolution.resolution_sha256:
                    raise QueueCorruption("static QA wait decision digest changed")
                decisions.append(event)
            static = tuple(
                event
                for event in decisions
                if event.detail.resolution.resolution_kind
                is DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY
            )
            if not static:
                return None
            if len(static) != 1 or decisions[0] != static[0]:
                raise QueueCorruption("static QA wait lacks one original decision")
            decision = static[0].detail.resolution
            evidence = decision.static_qa_missing_entry
            step = self.step(item.id)
            if (
                evidence is None
                or static[0].work_item.dispatch_sequence != evidence.wait_dispatch_sequence + 1
                or decision.task_id != item.task_id
                or decision.work_item_id != item.id
                or decision.expected_checkpoint_sequence != item.checkpoint_sequence
                or decision.expected_source_revision != step.boundary.source_revision
                or decision.authorization_source != "engineering_operator_decision"
                or item.role is not AgentRole.QA
                or any(
                    event.detail.resolution.resolution_kind
                    is not DeliveryResolutionKind.RESUME_UNINVOKED
                    for event in decisions[1:]
                )
            ):
                raise QueueCorruption("static QA wait lineage changed")
            cursor.execute("SELECT payload_json,revision FROM tasks WHERE id=%s", (item.task_id,))
            task_row = cursor.fetchone()
            if task_row is None:
                raise QueueCorruption("static QA waiting Task is missing")
            task = _decode_task(item.task_id, str(task_row["payload_json"]))
            if (
                task.status is not TaskStatus.QA
                or task.repository != item.repository_scopes[0]
                or task_intent_sha256(task) != decision.expected_task_intent_sha256
                or digest(task.to_wire()) != decision.task_snapshot_sha256
                or task_row["revision"] != decision.task_revision
                or task.attempts != item.attempt
            ):
                raise QueueConflict("static QA waiting Task or candidate changed")
            if current.dispatch_sequence > evidence.wait_dispatch_sequence + 1:
                if (
                    current.dispatch_sequence != evidence.wait_dispatch_sequence + 3
                    or knowledge_records is None
                    or len(decisions) != 1
                ):
                    raise QueueCorruption(
                        "static QA later wait needs one approved knowledge generation"
                    )
                prior_sequence = current.dispatch_sequence - 1
                cursor.execute(
                    "SELECT event_type,payload_json,lease_id,from_status FROM work_queue_events "
                    "WHERE work_item_id=%s AND event_type IN ('WAITING','READY','LEASE_EXPIRED') "
                    "ORDER BY sequence LIMIT 1025",
                    (item.id,),
                )
                transitions = cursor.fetchall()
                if len(transitions) > 1024:
                    raise QueueCorruption("static QA wait transition history exceeds bound")
                matching_waits = []
                matching_ready = []
                matching_expiry = []
                for transition in transitions:
                    payload = json.loads(str(transition["payload_json"]))
                    changed = QueuedWorkItem.model_validate(payload["work_item"])
                    if changed.id != current.id:
                        raise QueueCorruption("static QA wait changed WorkItem identity")
                    if (
                        transition["event_type"] == "WAITING"
                        and changed.dispatch_sequence == prior_sequence
                        and (changed.wait_reason or "").startswith("KNOWLEDGE_GAP:")
                    ):
                        matching_waits.append((changed, transition))
                    if (
                        transition["event_type"] == "READY"
                        and changed.dispatch_sequence == current.dispatch_sequence
                    ):
                        matching_ready.append((changed, transition))
                    if (
                        transition["event_type"] == "LEASE_EXPIRED"
                        and changed.dispatch_sequence == prior_sequence
                    ):
                        matching_expiry.append((changed, transition))
                if (
                    len(matching_waits) != 1
                    or len(matching_ready) != 1
                    or len(matching_expiry) != 1
                ):
                    raise QueueCorruption("static QA knowledge wait has no unique continuation")
                waiting, wait_event = matching_waits[0]
                _, ready_event = matching_ready[0]
                reason = (waiting.wait_reason or "").split(":")
                if len(reason) != 3:
                    raise QueueCorruption("static QA knowledge wait identity is invalid")
                gap = knowledge_records.get("gaps", reason[1], KnowledgeGap)
                route = knowledge_records.get("gap-routes", reason[1], KnowledgeGapRouting)
                approved = knowledge_records.get("gap-resolutions", reason[1], KnowledgeResolution)
                gap.validate_integrity()
                approved.validate_integrity()
                prior_claim = self.original_claim(str(wait_event["lease_id"]))
                if (
                    route.routing_sha256 != reason[2]
                    or route.routing_sha256
                    != digest(route.model_dump(mode="json", exclude={"routing_sha256"}))
                    or approved.gap_id != gap.gap_id
                    or approved.previous_run_id != gap.binding.run_id
                    or gap.binding.task_id != current.task_id
                    or gap.binding.role.value != current.role.value
                    or gap.binding.repository_ids != (current.repository_id,)
                    or gap.binding.source_revision != decision.expected_source_revision
                    or prior_claim.work_item.dispatch_sequence != prior_sequence
                    or prior_claim.work_item.id != item.id
                    or ready_event["from_status"] != waiting.status.value
                    or matching_expiry[0][1]["from_status"]
                    not in {WorkItemStatus.LEASED.value, WorkItemStatus.RUNNING.value}
                ):
                    raise QueueCorruption("static QA knowledge wait approval changed")
            cursor.execute(
                "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
                "WHERE task_id=%s AND "
                "JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.work_item_id'))=%s LIMIT 2",
                (item.task_id, item.id),
            )
            published = tuple(_decode(row, AcceptedRoleArtifact) for row in cursor.fetchall())
            if accepted_output is None:
                if published:
                    raise QueueCorruption("static QA wait already has accepted output")
            elif len(published) != 1 or published[0] != accepted_output:
                raise QueueCorruption("static QA accepted output differs from exact investigation")
            return decision

    def _rejected_static_qa_parent_decision(
        self,
        cursor: DictCursor,
        current: QueuedWorkItem,
        generations: dict[int, str],
        invocation_records: KnowledgeRecordStore | None,
    ) -> DeliveryResolution | None:
        """Inherit only a consumed, exact static decision through one rejected QA child."""
        parent_id = current.parent_work_item_id
        if parent_id is None:
            return None
        cursor.execute(
            "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
            "AND event_type='WAIT_RESOLVED' ORDER BY sequence LIMIT 4",
            (parent_id,),
        )
        rows = cursor.fetchall()
        if len(rows) > 3:
            raise QueueCorruption("rejected static QA parent has excessive decisions")
        events = tuple(
            _RejectedOutputResolutionEvent.model_validate_json(str(row["payload_json"]))
            for row in rows
        )
        retries = tuple(
            event
            for event in events
            if event.detail.resolution.resolution_kind
            is DeliveryResolutionKind.RETRY_REJECTED_STATIC_QA_OUTPUT
        )
        if not retries:
            parent = self._get_locked(cursor, parent_id, lock=False)
            if (
                parent.role is AgentRole.QA
                and current.role is AgentRole.QA
                and parent.attempt == current.attempt
                and parent.checkpoint_sequence == current.checkpoint_sequence
            ):
                raise QueueCorruption("same-attempt QA child lacks exact recovery decision")
            return None
        if len(retries) != 1 or invocation_records is None:
            raise QueueCorruption("rejected static QA child lacks one sealed parent decision")
        retry_event = retries[0]
        retry = retry_event.detail.resolution
        retry.validate_integrity()
        evidence = retry.rejected_static_qa_output
        parent = self._get_locked(cursor, parent_id, lock=False)
        parent_step = self.step(parent_id)
        step = self.step(current.id)
        original_static = tuple(
            event
            for event in events
            if event.detail.resolution.resolution_kind
            is DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY
        )
        if len(original_static) != 1 or evidence is None:
            raise QueueCorruption("rejected static QA child lost original static authority")
        static_event = original_static[0]
        static_decision = static_event.detail.resolution
        static_decision.validate_integrity()
        if (
            any(
                origin != "LEASE_EXPIRED"
                for sequence, origin in generations.items()
                if sequence > 0
            )
            or current.id != "work_" + retry.resolution_sha256
            or retry_event.detail.next_work_item_id != current.id
            or retry_event.detail.resolution_sha256 != retry.resolution_sha256
            or retry_event.detail.budget_refund
            or retry_event.work_item.status is not WorkItemStatus.CLOSED
            or retry_event.work_item.id != parent.id
            or parent.status is not WorkItemStatus.CLOSED
            or parent.task_id != current.task_id
            or parent.repository_id != current.repository_id
            or parent.repository_scopes != current.repository_scopes
            or parent.role is not AgentRole.QA
            or current.role is not AgentRole.QA
            or parent.attempt != current.attempt
            or parent.checkpoint_sequence != current.checkpoint_sequence
            or current.parent_work_item_id != parent.id
            or step.allocation_sha256 != parent_step.allocation_sha256
            or step.boundary.source_revision != parent_step.boundary.source_revision
            or retry.task_id != current.task_id
            or retry.work_item_id != parent.id
            or retry.expected_source_revision != step.boundary.source_revision
            or evidence.task_id != current.task_id
            or evidence.work_item_id != parent.id
            or evidence.candidate_revision != step.boundary.source_revision
            or evidence.static_resolution_sha256 != static_decision.resolution_sha256
            or static_event.detail.next_work_item_id != parent.id
            or static_event.detail.resolution_sha256 != static_decision.resolution_sha256
            or static_event.detail.budget_refund
            or static_decision.work_item_id != parent.id
            or static_decision.task_id != current.task_id
            or static_decision.expected_source_revision != step.boundary.source_revision
            or static_decision.task_snapshot_sha256 != retry.task_snapshot_sha256
            or static_decision.task_revision != retry.task_revision
        ):
            raise QueueCorruption("rejected static QA child changed parent, Task or candidate")
        cursor.execute("SELECT payload_json,revision FROM tasks WHERE id=%s", (current.task_id,))
        task_row = cursor.fetchone()
        if task_row is None:
            raise QueueCorruption("rejected static QA Task is missing")
        task = _decode_task(current.task_id, str(task_row["payload_json"]))
        if (
            task.status is not TaskStatus.QA
            or task.attempts != current.attempt
            or task.repository != current.repository_scopes[0]
            or task_row["revision"] != retry.task_revision
            or digest(task.to_wire()) != retry.task_snapshot_sha256
            or task_intent_sha256(task) != retry.expected_task_intent_sha256
            or tuple(criterion.id for criterion in task.acceptance_criteria)
            != evidence.all_criterion_ids
        ):
            raise QueueConflict("rejected static QA child changed frozen Task or coverage")
        cursor.execute(
            "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
            "WHERE task_id=%s AND "
            "JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.work_item_id'))=%s LIMIT 2",
            (current.task_id, parent.id),
        )
        published = tuple(_decode(row, AcceptedRoleArtifact) for row in cursor.fetchall())
        if len(published) != 1:
            raise QueueCorruption("rejected static QA parent has no unique old output")
        old = published[0]
        if (
            old.receipt.artifact_id != evidence.previous_qa_artifact_id
            or old.receipt.sha256 != evidence.previous_qa_sha256
            or old.lease_id != evidence.previous_lease_id
            or old.dispatch_sequence != evidence.previous_dispatch_sequence
            or old.run_id != evidence.previous_run_id
            or old.context_manifest_id != evidence.previous_context_manifest_id
            or old.source_revision != evidence.candidate_revision
        ):
            raise QueueCorruption("rejected static QA parent output changed its claim")
        from ai_software_engineer.work_queue.invocation import (
            DeliveryInvocationOutcome,
            DeliveryInvocationStart,
        )

        start = invocation_records.find("invocation-starts", parent.id, DeliveryInvocationStart)
        outcome = invocation_records.find(
            "invocation-outcomes", parent.id, DeliveryInvocationOutcome
        )
        if start is None or outcome is None:
            raise QueueCorruption("rejected static QA parent invocation is missing")
        start.validate_integrity()
        outcome.validate_integrity()
        report = outcome.result.artifact
        if (
            start.start_sha256 != evidence.invocation_start_sha256
            or outcome.outcome_sha256 != evidence.invocation_outcome_sha256
            or outcome.start != start
            or start.work_item_id != parent.id
            or start.lease_id != old.lease_id
            or start.request.run_id != old.run_id
            or start.request.context_manifest_id != old.context_manifest_id
            or start.request.source_revision != old.source_revision
            or outcome.result.status is not AgentRunStatus.SUCCEEDED
            or not isinstance(report, QaReportArtifact)
            or report.artifact_id != old.receipt.artifact_id
            or artifact_digest(report) != old.receipt.sha256
            or report.content.status is not QaReportStatus.FAIL
            or tuple(result.criterion_id for result in report.content.criteria_results)
            != evidence.reported_criterion_ids
        ):
            raise QueueCorruption("rejected static QA invocation or report changed")
        cursor.execute(
            "SELECT event_id FROM state_events WHERE task_id=%s AND "
            "JSON_CONTAINS(JSON_EXTRACT(payload_json,'$.artifact_ids'),"
            "JSON_QUOTE(%s)) LIMIT 1",
            (current.task_id, old.receipt.artifact_id),
        )
        if cursor.fetchone() is not None:
            raise QueueCorruption("rejected static QA report already entered Task history")
        cursor.execute(
            "SELECT id FROM work_queue_accepted_artifacts WHERE task_id=%s AND "
            "JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.work_item_id'))=%s LIMIT 1",
            (current.task_id, current.id),
        )
        if cursor.fetchone() is not None:
            raise QueueCorruption("rejected static QA child already has accepted output")
        cursor.execute(
            "SELECT sequence FROM work_queue_events WHERE work_item_id=%s "
            "AND event_type='COMPLETED' LIMIT 1",
            (current.id,),
        )
        if cursor.fetchone() is not None:
            raise QueueCorruption("rejected static QA child already completed")
        return static_decision

    def static_qa_resolution_for_claim(
        self,
        claim: QueueClaim,
        *,
        knowledge_records: KnowledgeRecordStore | None = None,
        preflight_records: KnowledgeRecordStore | None = None,
        invocation_records: KnowledgeRecordStore | None = None,
        observe_verifier: Callable[[AgentRequest, str], VerifierPreparationObservation]
        | None = None,
    ) -> DeliveryResolution | None:
        """Read only the consumed decision behind this exact active QA claim."""
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            current = self._get_locked(cursor, claim.work_item.id, lock=False)
            cursor.execute(
                "SELECT state,work_item_id,task_id,expires_at,assignment_json,lease_json,"
                "model_selection_json,"
                "worker_id,acquired_at FROM work_queue_claims WHERE lease_id=%s",
                (claim.lease.id,),
            )
            row = cursor.fetchone()
            if row is None or row["state"] != "ACTIVE":
                raise QueueLeaseLost("static QA claim is no longer active")
            try:
                live_lease = TaskLease.model_validate_json(str(row["lease_json"]))
                live_expiry = self._parse_time(str(row["expires_at"]))
            except (ValidationError, ValueError) as error:
                raise QueueCorruption("static QA live Lease failed typed validation") from error
            if live_expiry <= self._clock():
                raise QueueLeaseLost("static QA claim has expired")
            if (
                current.status not in {WorkItemStatus.LEASED, WorkItemStatus.RUNNING}
                or row["work_item_id"] != claim.work_item.id
                or row["task_id"] != claim.work_item.task_id
                or current.model_copy(
                    update={
                        "status": WorkItemStatus.LEASED,
                        "updated_at": claim.work_item.updated_at,
                    }
                ).to_wire()
                != claim.work_item.to_wire()
                or json.loads(str(row["assignment_json"])) != claim.assignment.to_wire()
                or live_lease.model_copy(update={"expires_at": claim.lease.expires_at}).to_wire()
                != claim.lease.to_wire()
                or live_lease.expires_at < claim.lease.expires_at
                or live_lease.expires_at != live_expiry
                or json.loads(str(row["model_selection_json"])) != claim.model_selection.to_wire()
                or row["worker_id"] != claim.worker_id
                or self._parse_time(str(row["acquired_at"])) != claim.claimed_at
            ):
                raise QueueConflict("static QA current claim or queue generation changed")
            cursor.execute(
                "SELECT event_type,payload_json,from_status,lease_id FROM work_queue_events "
                "WHERE work_item_id=%s AND event_type IN "
                "('READY','WAIT_RESOLVED','LEASE_EXPIRED','RETRY_SCHEDULED','WAITING') "
                "ORDER BY sequence ASC LIMIT 1025",
                (current.id,),
            )
            rows = cursor.fetchall()
            if len(rows) > 1024:
                raise QueueCorruption("active QA dispatch history exceeds bounded inspection")
            generations: dict[int, str] = {}
            static_events: list[_RejectedOutputResolutionEvent] = []
            resumed_events: list[_RejectedOutputResolutionEvent] = []
            knowledge_waits: dict[int, tuple[str, str, str]] = {}
            engineering_waits: dict[int, tuple[QueuedWorkItem, str]] = {}
            try:
                for transition in rows:
                    payload = json.loads(str(transition["payload_json"]))
                    transitioned = QueuedWorkItem.model_validate(payload["work_item"])
                    if transitioned.id != current.id:
                        raise QueueCorruption("active QA transition changed WorkItem identity")
                    event_type = str(transition["event_type"])
                    if event_type == "WAITING":
                        reason = transitioned.wait_reason or ""
                        if reason.startswith("KNOWLEDGE_GAP:"):
                            if transitioned.dispatch_sequence in knowledge_waits:
                                raise QueueCorruption("static QA knowledge wait is duplicated")
                            knowledge_waits[transitioned.dispatch_sequence] = (
                                reason,
                                str(transition["lease_id"]),
                                transitioned.status.value,
                            )
                        elif transitioned.wait_disposition is not None:
                            if transitioned.dispatch_sequence in engineering_waits:
                                raise QueueCorruption("static QA engineering wait is duplicated")
                            engineering_waits[transitioned.dispatch_sequence] = (
                                transitioned,
                                str(transition["lease_id"]),
                            )
                        continue
                    if transitioned.status is not (
                        WorkItemStatus.RETRY_SCHEDULED
                        if event_type in {"LEASE_EXPIRED", "RETRY_SCHEDULED"}
                        else WorkItemStatus.READY
                    ):
                        raise QueueCorruption("active QA transition changed expected status")
                    sequence = transitioned.dispatch_sequence
                    if sequence in generations or sequence > current.dispatch_sequence:
                        raise QueueCorruption("active QA generation has duplicate origin")
                    generations[sequence] = event_type
                    if transition["event_type"] == "WAIT_RESOLVED":
                        event = _RejectedOutputResolutionEvent.model_validate(payload)
                        event.detail.resolution.validate_integrity()
                        if (
                            event.detail.resolution_sha256
                            != event.detail.resolution.resolution_sha256
                        ):
                            raise QueueCorruption("active QA wait decision digest changed")
                        if event.detail.resolution.resolution_kind is (
                            DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY
                        ):
                            static_events.append(event)
                        elif event.detail.resolution.resolution_kind is (
                            DeliveryResolutionKind.RESUME_UNINVOKED
                        ):
                            resumed_events.append(event)
            except (KeyError, TypeError, ValueError, ValidationError) as error:
                raise QueueCorruption("active QA transition history is corrupt") from error
            if any(
                sequence not in generations for sequence in range(1, current.dispatch_sequence + 1)
            ):
                raise QueueCorruption(
                    "active QA dispatch generation has no durable transition event"
                )
            if not static_events:
                return self._rejected_static_qa_parent_decision(
                    cursor, current, generations, invocation_records
                )
            if len(static_events) != 1:
                raise QueueCorruption("static QA claim lacks one consumed decision")
            event = static_events[0]
            decision = event.detail.resolution
            step = self.step(current.id)
            static = decision.static_qa_missing_entry
            if (
                event.detail.resolution_sha256 != decision.resolution_sha256
                or event.detail.next_work_item_id != current.id
                or event.detail.budget_refund is not False
                or event.work_item.id != current.id
                or event.work_item.status is not WorkItemStatus.READY
                or decision.work_item_id != current.id
                or decision.resolution_kind is not DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY
                or static is None
                or event.work_item.dispatch_sequence != static.wait_dispatch_sequence + 1
                or current.dispatch_sequence < static.wait_dispatch_sequence + 1
                or current.role is not AgentRole.QA
                or current.task_id != decision.task_id
                or current.checkpoint_sequence != decision.expected_checkpoint_sequence
                or step.boundary.source_revision != decision.expected_source_revision
                or decision.authorization_source != "engineering_operator_decision"
            ):
                raise QueueCorruption("static QA decision changed its exact claim lineage")
            original_wait = engineering_waits.get(static.wait_dispatch_sequence)
            if (
                original_wait is None
                or original_wait[1] != static.wait_lease_id
                or original_wait[0].wait_disposition is None
                or original_wait[0].wait_disposition.disposition_sha256
                != decision.expected_disposition_sha256
                or original_wait[0].wait_disposition.facts.evidence_ids
                != ("verifier-preparation://" + static.preparation_checkpoint_sha256,)
            ):
                raise QueueCorruption("static QA original wait evidence changed")
            stale_marker = None
            if current.dispatch_sequence > static.wait_dispatch_sequence + 2:
                from ai_software_engineer.manager.verifier_preparation import (
                    VerifierPreparationCheckpoint,
                    VerifierPreparationIntent,
                )
                from ai_software_engineer.work_queue.invocation import (
                    DeliveryInvocationOutcome,
                    DeliveryInvocationStart,
                )

                if (
                    preflight_records is None
                    or invocation_records is None
                    or observe_verifier is None
                ):
                    raise QueueCorruption("static QA descendant lacks independent no-start stores")
                intents = tuple(
                    intent
                    for intent in preflight_records.list(
                        "verifier-preparation-intents", VerifierPreparationIntent
                    )
                    if intent.work_item_id == current.id
                    and intent.checkpoint_sequence == current.checkpoint_sequence
                )
                original_intents = tuple(
                    intent
                    for intent in intents
                    if intent.dispatch_sequence == static.wait_dispatch_sequence + 1
                )
                current_intents = tuple(
                    intent
                    for intent in intents
                    if intent.dispatch_sequence == current.dispatch_sequence
                )
                historical_intents = tuple(
                    intent
                    for intent in intents
                    if intent.dispatch_sequence < static.wait_dispatch_sequence + 1
                )
                if (
                    len(original_intents) != 1
                    or len(current_intents) > 1
                    or len(historical_intents) > 1
                    or len(intents)
                    != len(original_intents) + len(current_intents) + len(historical_intents)
                ):
                    raise QueueCorruption("static QA descendant has changed preparation intents")
                prior_intent = original_intents[0]
                prior_intent.validate_integrity()
                current_intent = current_intents[0] if current_intents else None
                if current_intent is not None:
                    current_intent.validate_integrity()
                    if (
                        current_intent.work_item_id != current.id
                        or current_intent.lease_id != claim.lease.id
                        or current_intent.task_id != current.task_id
                        or current_intent.task_snapshot_sha256 != decision.task_snapshot_sha256
                        or current_intent.checkpoint_sequence != current.checkpoint_sequence
                        or current_intent.request_sha256 != digest(current_intent.request.to_wire())
                        or current_intent.request.model_dump(
                            mode="json", exclude={"run_id", "context_manifest_id"}
                        )
                        != prior_intent.request.model_dump(
                            mode="json", exclude={"run_id", "context_manifest_id"}
                        )
                    ):
                        raise QueueCorruption("static QA current preparation changed its claim")
                for historical_intent in historical_intents:
                    historical_intent.validate_integrity()
                    if (
                        historical_intent.dispatch_sequence != static.original_dispatch_sequence
                        or historical_intent.lease_id != static.original_lease_id
                        or historical_intent.task_id != current.task_id
                        or historical_intent.task_snapshot_sha256 != decision.task_snapshot_sha256
                    ):
                        raise QueueCorruption("static QA historical preparation changed its Task")
                markers = tuple(
                    marker
                    for marker in preflight_records.list(
                        "verifier-preparations", VerifierPreparationCheckpoint
                    )
                    if marker.work_item_id == current.id
                    and marker.checkpoint_sequence == current.checkpoint_sequence
                )
                historical_markers = tuple(
                    marker
                    for marker in markers
                    if marker.intent_sha256 in {value.intent_sha256 for value in historical_intents}
                )
                if any(
                    marker.observation.native_execution_state != "NOT_STARTED"
                    for marker in historical_markers
                ):
                    raise QueueCorruption("static QA historical preparation execution is uncertain")
                ready = tuple(
                    marker
                    for marker in markers
                    if marker.result == "READY"
                    and marker.intent_sha256 == prior_intent.intent_sha256
                )
                current_markers = tuple(
                    marker
                    for marker in markers
                    if current_intent is not None
                    and marker.intent_sha256 == current_intent.intent_sha256
                )
                later = tuple(marker for marker in markers if marker not in ready + current_markers)
                later = tuple(marker for marker in later if marker not in historical_markers)
                start = invocation_records.find(
                    "invocation-starts", current.id, DeliveryInvocationStart
                )
                outcome = invocation_records.find(
                    "invocation-outcomes", current.id, DeliveryInvocationOutcome
                )
                if (
                    len(ready) != 1
                    or len(later) > 1
                    or len(current_markers) > 1
                    or prior_intent.dispatch_sequence != static.wait_dispatch_sequence + 1
                    or prior_intent.task_id != current.task_id
                    or prior_intent.task_snapshot_sha256 != decision.task_snapshot_sha256
                    or prior_intent.request.source_revision != decision.expected_source_revision
                    or ready[0].lease_id != prior_intent.lease_id
                    or ready[0].request != prior_intent.request
                    or ready[0].observation.native_execution_state != "NOT_STARTED"
                    or observe_verifier(prior_intent.request, prior_intent.lease_id)
                    != ready[0].observation
                ):
                    raise QueueCorruption("static QA descendant has no complete no-start proof")
                ready[0].validate_integrity()
                if current_markers:
                    current_marker = current_markers[0]
                    current_marker.validate_integrity()
                    if (
                        current_intent is None
                        or current_marker.result != "READY"
                        or current_marker.lease_id != claim.lease.id
                        or current_marker.wait_lease_id != claim.lease.id
                        or current_marker.dispatch_sequence != current.dispatch_sequence
                        or current_marker.wait_dispatch_sequence != current.dispatch_sequence
                        or current_marker.request != current_intent.request
                        or current_marker.observation.native_execution_state != "NOT_STARTED"
                    ):
                        raise QueueCorruption("static QA current preparation marker changed")
                if start is not None:
                    start.validate_integrity()
                    if (
                        current_intent is None
                        or not current_markers
                        or start.work_item_id != current.id
                        or start.checkpoint_sequence != current.checkpoint_sequence
                        or start.lease_id != claim.lease.id
                        or start.request != current_intent.request
                    ):
                        raise QueueCorruption("static QA earlier invocation may have started")
                if outcome is not None:
                    outcome.validate_integrity()
                    if start is None or outcome.start != start:
                        raise QueueCorruption("static QA earlier invocation has an outcome")
                if later:
                    later[0].validate_integrity()
                    if (
                        later[0].result != "WAIT"
                        or later[0].failure_reason is None
                        or later[0].failure_reason is not NativeVerificationWaitReason.FACTS_CHANGED
                        or later[0].observation.native_execution_state != "NOT_STARTED"
                        or later[0].intent_sha256 != prior_intent.intent_sha256
                        or later[0].wait_dispatch_sequence != current.dispatch_sequence - 1
                        or later[0].request != prior_intent.request
                    ):
                        raise QueueCorruption("static QA descendant changed stale-preflight marker")
                    stale_marker = later[0]
            for sequence in range(static.wait_dispatch_sequence + 2, current.dispatch_sequence + 1):
                origin = generations[sequence]
                if origin == "LEASE_EXPIRED":
                    continue
                if origin == "READY" and sequence - 1 in knowledge_waits:
                    if knowledge_records is None:
                        raise QueueCorruption("static QA knowledge continuation lacks records")
                    wait_reason, wait_lease_id, wait_status = knowledge_waits[sequence - 1]
                    parts = wait_reason.split(":")
                    if len(parts) != 3:
                        raise QueueCorruption("static QA knowledge wait has invalid identity")
                    gap = knowledge_records.get("gaps", parts[1], KnowledgeGap)
                    route = knowledge_records.get("gap-routes", parts[1], KnowledgeGapRouting)
                    approved = knowledge_records.get(
                        "gap-resolutions", parts[1], KnowledgeResolution
                    )
                    gap.validate_integrity()
                    approved.validate_integrity()
                    wait_claim = self.original_claim(wait_lease_id)
                    if (
                        route.routing_sha256 != parts[2]
                        or route.routing_sha256
                        != digest(route.model_dump(mode="json", exclude={"routing_sha256"}))
                        or approved.gap_id != gap.gap_id
                        or approved.previous_run_id != gap.binding.run_id
                        or gap.binding.task_id != current.task_id
                        or gap.binding.role.value != current.role.value
                        or gap.binding.repository_ids != (current.repository_id,)
                        or gap.binding.source_revision != decision.expected_source_revision
                        or wait_claim.work_item.id != current.id
                        or wait_claim.work_item.dispatch_sequence != sequence - 1
                        or wait_status != route.waiting_status
                    ):
                        raise QueueCorruption("static QA knowledge approval changed")
                    continue
                if origin == "READY" and generations.get(sequence - 1) == "LEASE_EXPIRED":
                    continue
                if origin == "WAIT_RESOLVED" and len(resumed_events) == 1:
                    resumed = resumed_events[0].detail.resolution
                    proof = resumed.verifier_preparation
                    engineering_wait = engineering_waits.get(sequence - 1)
                    if (
                        resumed.resolution_kind is DeliveryResolutionKind.RESUME_UNINVOKED
                        and resumed_events[0].work_item.dispatch_sequence == sequence
                        and resumed.work_item_id == current.id
                        and resumed.task_id == decision.task_id
                        and resumed.task_snapshot_sha256 == decision.task_snapshot_sha256
                        and resumed.task_revision == decision.task_revision
                        and resumed.expected_checkpoint_sequence
                        == decision.expected_checkpoint_sequence
                        and resumed.expected_source_revision == decision.expected_source_revision
                        and resumed.step_sha256 == decision.step_sha256
                        and proof is not None
                        and stale_marker is not None
                        and engineering_wait is not None
                        and engineering_wait[0].wait_disposition is not None
                        and engineering_wait[1] == stale_marker.wait_lease_id
                        and engineering_wait[0].dispatch_sequence
                        == stale_marker.wait_dispatch_sequence
                        and engineering_wait[0].wait_disposition.facts.evidence_ids
                        == ("verifier-preparation://" + stale_marker.checkpoint_sha256,)
                        and engineering_wait[0].wait_disposition.disposition_sha256
                        == resumed.expected_disposition_sha256
                        and proof.preparation_checkpoint_sha256 == stale_marker.checkpoint_sha256
                        and proof.request_sha256 == stale_marker.request_sha256
                        and proof.previous_run_id == stale_marker.run_id
                        and proof.previous_context_manifest_id == stale_marker.context_manifest_id
                        and proof.native_execution_state == "NOT_STARTED"
                        and proof.context_capacity_receipt_sha256 is None
                        and resumed.static_qa_missing_entry is None
                        and not resumed_events[0].detail.budget_refund
                    ):
                        continue
                raise QueueCorruption("static QA descendant generation has no exact authority")
            cursor.execute(
                "SELECT id FROM work_queue_accepted_artifacts WHERE task_id=%s "
                "AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.work_item_id'))=%s LIMIT 1",
                (current.task_id, current.id),
            )
            if cursor.fetchone() is not None:
                raise QueueCorruption("static QA work item already has accepted output")
            cursor.execute(
                "SELECT payload_json,revision FROM tasks WHERE id=%s", (current.task_id,)
            )
            task_row = cursor.fetchone()
            if task_row is None:
                raise QueueCorruption("static QA Task is missing")
            task = _decode_task(current.task_id, str(task_row["payload_json"]))
            if (
                task.status is not TaskStatus.QA
                or current.repository_scopes != (task.repository,)
                or task_intent_sha256(task) != decision.expected_task_intent_sha256
                or digest(task.to_wire()) != decision.task_snapshot_sha256
                or task_row["revision"] != decision.task_revision
                or task.attempts != current.attempt
            ):
                raise QueueConflict("static QA Task or frozen source changed")
            return decision

    def _static_qa_successor(
        self,
        cursor: DictCursor,
        resolution: DeliveryResolution,
        current: QueuedWorkItem,
        disposition: DeliveryDisposition,
        task: Task,
        step: QueuedRoleStep,
        now: datetime,
    ) -> tuple[QueuedWorkItem, QueuedWorkItem]:
        static = resolution.static_qa_missing_entry
        preparation = resolution.verifier_preparation
        if (
            static is None
            or preparation is None
            or preparation.native_execution_state != "NOT_STARTED"
            or resolution.authorization_source != "engineering_operator_decision"
            or current.role is not AgentRole.QA
            or task.status is not TaskStatus.QA
            or current.attempt != task.attempts
            or static.candidate_revision != step.boundary.source_revision
            or static.preparation_checkpoint_sha256 != preparation.preparation_checkpoint_sha256
            or static.wait_dispatch_sequence != current.dispatch_sequence
            or disposition.facts.evidence_ids
            != ("verifier-preparation://" + static.preparation_checkpoint_sha256,)
        ):
            raise QueueConflict("static QA decision lacks the exact original no-start")
        original = self.original_claim(static.original_lease_id)
        waiting = self.original_claim(static.wait_lease_id)
        if (
            digest(original.to_wire()) != static.original_claim_sha256
            or digest(waiting.to_wire()) != static.wait_claim_sha256
            or original.work_item.dispatch_sequence != static.original_dispatch_sequence
            or waiting.work_item.dispatch_sequence != static.wait_dispatch_sequence
            or original.work_item.id != current.id
            or waiting.work_item.id != current.id
        ):
            raise QueueConflict("static QA historical claims changed")
        cursor.execute(
            "SELECT id FROM work_queue_accepted_artifacts WHERE task_id=%s "
            "AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.work_item_id'))=%s "
            "LIMIT 1 FOR UPDATE",
            (task.id, current.id),
        )
        if cursor.fetchone() is not None:
            raise QueueConflict("static QA original item already has accepted output")
        cursor.execute(
            "SELECT sequence FROM work_queue_events WHERE work_item_id=%s "
            "AND event_type='COMPLETED' LIMIT 1 FOR UPDATE",
            (current.id,),
        )
        if cursor.fetchone() is not None:
            raise QueueConflict("static QA original item already completed")
        next_item = current.model_copy(
            update={
                "status": WorkItemStatus.READY,
                "updated_at": now,
                "wait_reason": None,
                "wait_disposition": None,
                "available_at": None,
                "dispatch_sequence": current.dispatch_sequence + 1,
            }
        )
        return next_item, next_item

    def _rejected_static_qa_successor(
        self,
        cursor: DictCursor,
        resolution: DeliveryResolution,
        current: QueuedWorkItem,
        disposition: DeliveryDisposition,
        task: Task,
        step: QueuedRoleStep,
        now: datetime,
        invocation_records: KnowledgeRecordStore | None,
    ) -> tuple[QueuedWorkItem, QueuedWorkItem]:
        evidence = resolution.rejected_static_qa_output
        if (
            evidence is None
            or current.role is not AgentRole.QA
            or task.status is not TaskStatus.QA
            or current.attempt != task.attempts
            or evidence.task_id != task.id
            or evidence.work_item_id != current.id
            or evidence.candidate_revision != step.boundary.source_revision
            or disposition.facts.classification != "PLATFORM_BUG"
            or resolution.authorization_source != "engineering_operator_decision"
            or invocation_records is None
            or tuple(criterion.id for criterion in task.acceptance_criteria)
            != evidence.all_criterion_ids
            or not evidence.missing_criterion_ids
        ):
            raise QueueConflict("被拒静态 QA 恢复缺少当前精确报告与工程等待")
        cursor.execute(
            "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
            "AND event_type='WAIT_RESOLVED' ORDER BY sequence LIMIT 4 FOR UPDATE",
            (current.id,),
        )
        rows = cursor.fetchall()
        if len(rows) > 3:
            raise QueueConflict("被拒静态 QA 原决议历史超过有界上限")
        prior_decisions = tuple(
            _RejectedOutputResolutionEvent.model_validate_json(str(row["payload_json"]))
            for row in rows
        )
        original_static = tuple(
            event
            for event in prior_decisions
            if event.detail.resolution.resolution_kind
            is DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY
        )
        if len(original_static) != 1:
            raise QueueConflict("被拒静态 QA 恢复缺少唯一原静态决定")
        original_event = original_static[0]
        original_decision = original_event.detail.resolution
        original_decision.validate_integrity()
        if (
            original_event.detail.resolution_sha256 != original_decision.resolution_sha256
            or original_event.detail.next_work_item_id != current.id
            or original_event.detail.budget_refund
            or original_event.work_item.status is not WorkItemStatus.READY
            or original_event.work_item.id != current.id
            or original_decision.resolution_sha256 != evidence.static_resolution_sha256
            or original_decision.task_id != task.id
            or original_decision.work_item_id != current.id
            or original_decision.expected_source_revision != evidence.candidate_revision
            or original_decision.task_snapshot_sha256 != resolution.task_snapshot_sha256
            or original_decision.task_revision != resolution.task_revision
            or any(
                event.detail.resolution.resolution_kind
                not in {
                    DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY,
                    DeliveryResolutionKind.RESUME_UNINVOKED,
                }
                for event in prior_decisions
            )
        ):
            raise QueueConflict("被拒静态 QA 恢复改变了原静态决定")
        prior_claim = self.original_claim(evidence.previous_lease_id)
        if (
            digest(prior_claim.to_wire()) != evidence.previous_claim_sha256
            or prior_claim.work_item.id != current.id
            or prior_claim.work_item.dispatch_sequence != evidence.previous_dispatch_sequence
            or prior_claim.work_item.attempt != current.attempt
            or prior_claim.work_item.checkpoint_sequence != current.checkpoint_sequence
        ):
            raise QueueConflict("被拒静态 QA 恢复改变了原真实 claim")
        cursor.execute(
            "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
            "WHERE task_id=%s FOR UPDATE",
            (task.id,),
        )
        accepted = tuple(_decode(row, AcceptedRoleArtifact) for row in cursor.fetchall())
        matching = tuple(
            value
            for value in accepted
            if value.work_item_id == current.id
            and value.receipt.artifact_id == evidence.previous_qa_artifact_id
            and value.receipt.sha256 == evidence.previous_qa_sha256
            and value.run_id == evidence.previous_run_id
            and value.context_manifest_id == evidence.previous_context_manifest_id
            and value.source_revision == evidence.candidate_revision
        )
        if len(matching) != 1:
            raise QueueConflict("被拒静态 QA 恢复没有唯一旧报告接纳记录")
        if sum(value.work_item_id == current.id for value in accepted) != 1:
            raise QueueConflict("被拒静态 QA 原工作项有多份接纳产物")
        if (
            matching[0].lease_id != evidence.previous_lease_id
            or matching[0].dispatch_sequence != evidence.previous_dispatch_sequence
        ):
            raise QueueConflict("被拒静态 QA 恢复的旧报告不属于原真实领取")
        from ai_software_engineer.work_queue.invocation import (
            DeliveryInvocationOutcome,
            DeliveryInvocationStart,
        )

        assert invocation_records is not None
        start = invocation_records.find("invocation-starts", current.id, DeliveryInvocationStart)
        outcome = invocation_records.find(
            "invocation-outcomes", current.id, DeliveryInvocationOutcome
        )
        if start is None or outcome is None:
            raise QueueConflict("被拒静态 QA 恢复缺少已封存的原调用和结果")
        start.validate_integrity()
        outcome.validate_integrity()
        report = outcome.result.artifact
        if (
            start.start_sha256 != evidence.invocation_start_sha256
            or outcome.outcome_sha256 != evidence.invocation_outcome_sha256
            or outcome.start != start
            or start.work_item_id != current.id
            or start.lease_id != evidence.previous_lease_id
            or start.checkpoint_sequence != current.checkpoint_sequence
            or start.request.run_id != evidence.previous_run_id
            or start.request.context_manifest_id != evidence.previous_context_manifest_id
            or start.request.source_revision != evidence.candidate_revision
            or start.request.attempt != current.attempt
            or outcome.result.status is not AgentRunStatus.SUCCEEDED
            or not isinstance(report, QaReportArtifact)
            or report.artifact_id != evidence.previous_qa_artifact_id
            or artifact_digest(report) != evidence.previous_qa_sha256
            or report.content.status is not QaReportStatus.FAIL
            or tuple(result.criterion_id for result in report.content.criteria_results)
            != evidence.reported_criterion_ids
        ):
            raise QueueConflict("被拒静态 QA 恢复的原调用或报告已变化")
        cursor.execute(
            "SELECT event_id FROM state_events WHERE task_id=%s AND "
            "JSON_CONTAINS(JSON_EXTRACT(payload_json,'$.artifact_ids'),"
            "JSON_QUOTE(%s)) LIMIT 1 FOR UPDATE",
            (task.id, evidence.previous_qa_artifact_id),
        )
        if cursor.fetchone() is not None:
            raise QueueConflict("被拒静态 QA 原报告已经进入 Task 状态历史")
        cursor.execute(
            "SELECT sequence FROM work_queue_events WHERE work_item_id=%s "
            "AND event_type='COMPLETED' LIMIT 1 FOR UPDATE",
            (current.id,),
        )
        if cursor.fetchone() is not None:
            raise QueueConflict("被拒静态 QA 原工作项已经完成推进")
        next_item = current.model_copy(
            update={
                "id": "work_" + resolution.resolution_sha256,
                "status": WorkItemStatus.READY,
                "updated_at": now,
                "wait_reason": None,
                "wait_disposition": None,
                "available_at": None,
                "parent_work_item_id": current.id,
                "dispatch_sequence": 0,
            }
        )
        next_step = QueuedRoleStep(
            work_item=next_item,
            boundary=RoleRunBoundary(
                task.id,
                AgentRole.QA,
                task.attempts,
                resolution.task_revision,
                resolution.expected_source_revision,
            ),
            allocation_sha256=step.allocation_sha256,
        )
        _put(cursor, "work_queue_steps", next_item.id, task.id, next_step)
        next_item = self._enqueue_locked(cursor, next_item, allow_rejected_static_qa_successor=True)
        return next_item, current.model_copy(
            update={
                "status": WorkItemStatus.CLOSED,
                "updated_at": now,
                "wait_reason": None,
                "wait_disposition": None,
            }
        )

    def _rejected_output_decisions(
        self, task_id: str, *, cursor: DictCursor | None = None
    ) -> tuple[DeliveryResolution, ...]:
        return self._rejected_wait_decisions(
            task_id, DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT, cursor=cursor
        )

    def _rejected_wait_decisions(
        self,
        task_id: str,
        resolution_kind: DeliveryResolutionKind,
        *,
        cursor: DictCursor | None = None,
    ) -> tuple[DeliveryResolution, ...]:
        """Read complete consumed decisions; unconsumed filesystem records grant no authority."""
        if cursor is None:
            with (
                closing(open_mysql_connection(self._dsn)) as connection,
                connection.cursor(DictCursor) as owned_cursor,
            ):
                return self._rejected_wait_decisions(task_id, resolution_kind, cursor=owned_cursor)
        cursor.execute(
            "SELECT e.payload_json FROM work_queue_events e JOIN work_queue_items i "
            "ON e.work_item_id=i.id WHERE i.task_id=%s "
            "AND e.event_type='WAIT_RESOLVED' "
            "AND JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,"
            "'$.detail.resolution.resolution_kind'))=%s "
            "ORDER BY e.sequence LIMIT 513",
            (task_id, resolution_kind.value),
        )
        rows = cursor.fetchall()
        if len(rows) > 512:
            raise QueueCorruption("被拒产出恢复历史超过有界读取上限")
        decisions = []
        for row in rows:
            try:
                payload = _RejectedOutputResolutionEvent.model_validate_json(
                    str(row["payload_json"])
                )
                decision = payload.detail.resolution
                decision.validate_integrity()
            except (ValidationError, ValueError) as error:
                raise QueueCorruption("被拒产出恢复历史未通过完整契约校验") from error
            if (
                decision.task_id != task_id
                or decision.work_item_id != payload.work_item.id
                or payload.work_item.status is not WorkItemStatus.CLOSED
                or payload.detail.resolution_sha256 != decision.resolution_sha256
                or payload.detail.next_work_item_id != "work_" + decision.resolution_sha256
                or payload.detail.budget_refund
                or decision.resolution_kind is not resolution_kind
            ):
                raise QueueCorruption("被拒产出恢复决定改变了已消费的原工作项")
            decisions.append(decision)
        return tuple(decisions)

    def rejected_output_retry(self, work_item_id: str) -> RejectedCoderOutputEvidence | None:
        current = self.get(work_item_id)
        matches = tuple(
            decision
            for decision in self._rejected_output_decisions(current.task_id)
            if current.id == "work_" + decision.resolution_sha256
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise QueueCorruption("被拒产出续跑缺少唯一已消费的决定")
        decision = matches[0]
        evidence = decision.rejected_output
        assert evidence is not None
        parent = self.get(evidence.work_item_id)
        step, parent_step = self.step(current.id), self.step(parent.id)
        if (
            current.parent_work_item_id != parent.id
            or current.task_id != evidence.task_id
            or current.repository_id != evidence.scope.repository_id
            or current.repository_scopes != parent.repository_scopes
            or current.role is not AgentRole.CODER
            or current.attempt != evidence.original_attempt + 1
            or current.checkpoint_sequence != evidence.checkpoint_sequence
            or step.boundary.source_revision != evidence.source_revision
            or step.allocation_sha256 != parent_step.allocation_sha256
        ):
            raise QueueCorruption("被拒产出续跑决定不属于当前工作项与原源码")
        return evidence

    def rejected_knowledge_retry(
        self, work_item_id: str
    ) -> RejectedKnowledgePreparationEvidence | None:
        current = self.get(work_item_id)
        matches = tuple(
            decision
            for decision in self._rejected_wait_decisions(
                current.task_id, DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION
            )
            if current.id == "work_" + decision.resolution_sha256
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise QueueCorruption("知识拒绝续跑缺少唯一已消费的精确决定")
        decision = matches[0]
        evidence = decision.rejected_knowledge
        if evidence is None:
            raise QueueCorruption("知识拒绝续跑缺少已消费的完整证明")
        parent = self.get(evidence.work_item_id)
        step, parent_step = self.step(current.id), self.step(parent.id)
        if (
            current.parent_work_item_id != parent.id
            or current.task_id != evidence.task_id
            or current.repository_id != evidence.scope.repository_id
            or current.repository_scopes != parent.repository_scopes
            or current.role is not AgentRole.CODER
            or current.attempt != evidence.original_attempt + 1
            or current.checkpoint_sequence != evidence.checkpoint_sequence
            or step.boundary.source_revision != evidence.source_revision
            or step.allocation_sha256 != parent_step.allocation_sha256
            or (
                evidence.current_draft_sha256 is not None
                and decision.authorization_source != "engineering_operator_decision"
            )
        ):
            raise QueueCorruption("知识拒绝续跑改变了原源码、普通工作额度或精确工程决定")
        return evidence

    def rejected_output_artifact_ids(self, task_id: str) -> frozenset[str]:
        return frozenset(
            decision.rejected_output.rejected_artifact_id
            for decision in self._rejected_output_decisions(task_id)
            if decision.rejected_output is not None
        )

    def rejected_static_qa_artifact_ids(self, task_id: str) -> frozenset[str]:
        return frozenset(
            decision.rejected_static_qa_output.previous_qa_artifact_id
            for decision in self._rejected_wait_decisions(
                task_id, DeliveryResolutionKind.RETRY_REJECTED_STATIC_QA_OUTPUT
            )
            if decision.rejected_static_qa_output is not None
        )

    def retired_rejected_outputs(
        self, task_id: str, *, cursor: DictCursor | None = None
    ) -> tuple[RejectedCoderOutputEvidence, ...]:
        return tuple(
            decision.rejected_output
            for decision in self._rejected_output_decisions(task_id, cursor=cursor)
            if decision.rejected_output is not None
        )

    def pending_baseline_release(
        self,
        binding: ExecutionBaselineBinding,
        authorization: BaselineContinueAuthorization,
        *,
        cursor: DictCursor | None = None,
    ) -> bool:
        from ai_software_engineer.work_queue.baseline import pending_baseline_release

        return pending_baseline_release(self, binding, authorization, cursor=cursor)

    def release_baseline_pause(
        self,
        binding: ExecutionBaselineBinding,
        authorization: BaselineContinueAuthorization,
        *,
        cursor: DictCursor | None = None,
        validate_new_release: Callable[[], None] | None = None,
    ) -> bool:
        from ai_software_engineer.work_queue.baseline import release_baseline_pause

        return release_baseline_pause(
            self,
            binding,
            authorization,
            cursor=cursor,
            validate_new_release=validate_new_release,
        )

    @contextmanager
    def idle_task_scope(self, task_id: str) -> Iterator[DictCursor]:
        """Fence a controlled same-Task Git action against new role claims."""
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self._lock_authority(cursor)
            cursor.execute("SELECT id FROM tasks WHERE id=%s FOR UPDATE", (task_id,))
            if cursor.fetchone() is None:
                raise QueueNotFound(task_id)
            cursor.execute(
                "SELECT lease_id FROM work_queue_claims WHERE task_id=%s "
                "AND state='ACTIVE' FOR UPDATE",
                (task_id,),
            )
            if cursor.fetchone() is not None:
                raise QueueLeaseLost(
                    "baseline action requires all owned role claims to be released"
                )
            yield cursor

    def settle_rejected_candidate_expired_owner(
        self,
        *,
        task_id: str,
        task_lock: TaskProcessLockGuard,
        collect_current: Callable[[], RejectedCandidateOutputProof],
        seal: Callable[[RejectedCandidateExpiredOwnerSettlement], str],
    ) -> bool:
        from ai_software_engineer.work_queue.baseline import settle_rejected_candidate_expired_owner

        return settle_rejected_candidate_expired_owner(
            self, task_id=task_id, task_lock=task_lock, collect_current=collect_current, seal=seal
        )

    def settle_stopped_budget(
        self,
        cursor: DictCursor,
        settlement: StoppedFailureBudgetSettlement
        | StoppedUnknownBudgetSettlement
        | ContainedUnknownBudgetSettlement,
        *,
        validate_current: Callable[[], None] | None = None,
    ) -> None:
        """Append Task/event/queue together inside the caller's idle authority fence."""
        settlement.validate_integrity()
        if (
            settlement.kind
            in {
                "stopped_unknown_budget_settlement",
                "contained_unknown_budget_settlement",
            }
            and validate_current is None
        ):
            raise QueueConflict("未知结果额度收尾缺少最终原执行核验")
        event_type = (
            "CONTAINED_UNKNOWN_BUDGET_SETTLED"
            if settlement.kind == "contained_unknown_budget_settlement"
            else "STOPPED_BUDGET_SETTLED"
        )
        task, proof, event = settlement.task, settlement.investigation, settlement.event
        self._lock_authority(cursor)
        cursor.execute(
            "SELECT id,payload_json,revision,status FROM tasks WHERE id=%s FOR UPDATE", (task.id,)
        )
        row = cursor.fetchone()
        if row is None:
            raise QueueNotFound(task.id)
        current = self._decode_model(row, "payload_json", Task)
        revision = row["revision"]
        if row["id"] != current.id or row["status"] != current.status.value:
            raise QueueCorruption("额度收尾的任务索引与正文不一致")
        cursor.execute(
            "SELECT lease_id FROM work_queue_claims WHERE task_id=%s AND state='ACTIVE' FOR UPDATE",
            (task.id,),
        )
        if cursor.fetchone() is not None:
            raise QueueLeaseLost("额度收尾期间仍有执行权限未释放")
        cursor.execute(
            "SELECT id,payload_json FROM work_queue_items WHERE task_id=%s FOR UPDATE", (task.id,)
        )
        items = tuple(self._decode_item(value) for value in cursor.fetchall())
        item = next((value for value in items if value.id == proof.work_item_id), None)
        if item is None:
            raise QueueNotFound(proof.work_item_id)
        next_task = apply_event(task, event)
        cursor.execute(
            "SELECT payload_json FROM state_events WHERE event_id=%s FOR UPDATE", (event.event_id,)
        )
        previous_event = cursor.fetchone()
        cursor.execute(
            "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
            "WHERE task_id=%s FOR UPDATE",
            (task.id,),
        )
        accepted = tuple(_decode(value, AcceptedRoleArtifact) for value in cursor.fetchall())
        retired = self.retired_rejected_outputs(task.id, cursor=cursor)
        if any(
            publication.work_item_id == proof.work_item_id
            or publication.run_id == proof.original_run_id
            or (
                publication.checkpoint_sequence >= proof.checkpoint_sequence
                and not is_retired_rejected_publication(
                    publication,
                    retired,
                    current_work_item_id=proof.work_item_id,
                    current_run_id=proof.original_run_id,
                    checkpoint_sequence=proof.checkpoint_sequence,
                )
            )
            for publication in accepted
        ):
            raise QueueConflict("原失败调用之后已有接纳产物, 暂不能额度收尾")
        if validate_current is not None:
            validate_current()
        if previous_event is not None:
            cursor.execute(
                "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
                "AND event_type=%s ORDER BY sequence",
                (item.id, event_type),
            )
            publications = cursor.fetchall()
            if (
                json.loads(str(previous_event["payload_json"])) != event.to_wire()
                or current != next_task
                or revision != proof.task_revision + 1
                or item.status is not WorkItemStatus.CLOSED
                or record_digest(item) != settlement.closed_item_sha256
                or any(value.status is not WorkItemStatus.CLOSED for value in items)
                or len(publications) != 1
                or json.loads(str(publications[0]["payload_json"]))["detail"]
                != {
                    "settlement_sha256": settlement.settlement_sha256,
                    "previous_work_item_sha256": settlement.expected_item_sha256,
                    "budget_refund": False,
                }
            ):
                raise QueueConflict("已收尾记录与原精确额度决定不一致")
            return
        if (
            current != task
            or revision != proof.task_revision
            or record_digest(item) != settlement.expected_item_sha256
            or item.wait_disposition != proof.disposition
            or item.status not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
            or any(
                value.id != item.id and value.status is not WorkItemStatus.CLOSED for value in items
            )
            or record_digest(self.step(item.id)) != proof.step_sha256
        ):
            raise QueueConflict("额度收尾的原任务或唯一等待已经变化")
        cursor.execute(
            "INSERT INTO state_events (event_id,task_id,revision,payload_json) "
            "VALUES (%s,%s,%s,%s)",
            (event.event_id, task.id, proof.task_revision + 1, _encode(event.to_wire())),
        )
        cursor.execute(
            "UPDATE tasks SET payload_json=%s,status=%s,revision=%s,updated_at=%s "
            "WHERE id=%s AND revision=%s",
            (
                _encode(next_task.to_wire()),
                next_task.status.value,
                proof.task_revision + 1,
                next_task.updated_at.isoformat(),
                task.id,
                proof.task_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise QueueConflict("额度收尾期间任务版本已变化")
        closed = item.model_copy(
            update={
                "status": WorkItemStatus.CLOSED,
                "wait_reason": None,
                "wait_disposition": None,
                "available_at": None,
                "updated_at": event.occurred_at,
            }
        )
        self._update_item(cursor, closed)
        self._append_event(
            cursor,
            closed,
            from_status=item.status,
            event_type=event_type,
            lease_id=None,
            occurred_at=event.occurred_at,
            detail={
                "settlement_sha256": settlement.settlement_sha256,
                "previous_work_item_sha256": settlement.expected_item_sha256,
                "budget_refund": False,
            },
        )
        self._lock_authority(cursor)

    def original_claim(self, lease_id: str) -> QueueClaim:
        """Read the original CLAIMED event, never reconstruct it from current work."""
        return self.original_claim_record(lease_id).claim

    def original_claim_record(self, lease_id: str) -> OriginalClaimRecord:
        """Retain explicit legacy/new provenance after complete event/allocation checks."""
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT lease_id,work_item_id,task_id,agent_id,assignment_json,lease_json,"
                "model_selection_json,worker_id,capacity_units,acquired_at,expires_at "
                "FROM work_queue_claims WHERE lease_id=%s",
                (lease_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise QueueNotFound(lease_id)
            cursor.execute(
                "SELECT work_item_id,lease_id,from_status,to_status,payload_json,occurred_at "
                "FROM work_queue_events "
                "WHERE lease_id=%s AND event_type='CLAIMED' ORDER BY sequence",
                (lease_id,),
            )
            events = cursor.fetchall()
            if len(events) != 1:
                raise QueueCorruption("原 claim 缺少唯一不可变领取事件")
            event = events[0]
            try:
                payload = TypeAdapter(dict[str, JsonValue]).validate_json(
                    str(event["payload_json"])
                )
                current = QueueClaim.model_validate(
                    {
                        "work_item": payload["work_item"],
                        "assignment": json.loads(str(row["assignment_json"])),
                        "lease": json.loads(str(row["lease_json"])),
                        "model_selection": json.loads(str(row["model_selection_json"])),
                        "worker_id": row["worker_id"],
                        "claimed_at": event["occurred_at"],
                    }
                )
                if (
                    current.lease.id != lease_id
                    or (row["lease_id"], event["lease_id"]) != (lease_id, lease_id)
                    or (row["work_item_id"], event["work_item_id"])
                    != (current.work_item.id, current.work_item.id)
                    or row["task_id"] != current.work_item.task_id
                    or row["agent_id"] != current.lease.agent_id
                    or row["capacity_units"] != current.lease.capacity_units
                    or self._parse_time(str(row["acquired_at"])) != current.lease.acquired_at
                    or self._parse_time(str(row["expires_at"])) != current.lease.expires_at
                    or current.claimed_at != current.lease.acquired_at
                    or current.claimed_at != current.work_item.updated_at
                    or event["from_status"]
                    not in {WorkItemStatus.READY.value, WorkItemStatus.RETRY_SCHEDULED.value}
                    or event["to_status"] != WorkItemStatus.LEASED.value
                ):
                    raise ValueError("原 claim 分配索引与不可变领取事件不一致")
                detail = payload.get("detail", {})
                if not isinstance(detail, dict):
                    raise ValueError("原 claim 领取事件详情无效")
                if "queue_claim" not in detail:
                    # Legacy has no immutable lease expiry. Do not guess the
                    # original raw bytes from TTL or the current heartbeat.
                    return OriginalClaimRecord(current, has_immutable_snapshot=False)
                snapshot = QueueClaim.model_validate(detail["queue_claim"])
                return OriginalClaimRecord(
                    require_claim_snapshot(snapshot, current), has_immutable_snapshot=True
                )
            except (ValidationError, ValueError, KeyError, TypeError) as error:
                raise QueueCorruption("原 claim 记录或不可变完整快照不一致") from error

    def claims_for_work_item(self, work_item_id: str) -> tuple[QueueClaim, ...]:
        """Return exact immutable claim identities, never infer from role/attempt."""
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT lease_id FROM work_queue_claims WHERE work_item_id=%s ORDER BY lease_id",
                (work_item_id,),
            )
            lease_ids = tuple(str(row["lease_id"]) for row in cursor.fetchall())
        return tuple(self.original_claim(identity) for identity in lease_ids)

    def step_for_claim(self, claim: QueueClaim) -> QueuedRoleStep:
        """Resolve the source that preceded the immutable CLAIMED event, by SQL order."""
        original = self.original_claim(claim.lease.id)
        if original != claim:
            raise QueueConflict("historical source request changed its original claim")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT sequence FROM work_queue_events WHERE lease_id=%s AND event_type='CLAIMED'",
                (claim.lease.id,),
            )
            rows = cursor.fetchall()
            if len(rows) != 1:
                raise QueueCorruption("claim source has no unique event sequence")
            cursor.execute(
                "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
                "AND event_type='EXECUTION_BASELINE_REBOUND' AND sequence<%s "
                "ORDER BY sequence DESC LIMIT 1",
                (claim.work_item.id, rows[0]["sequence"]),
            )
            event = cursor.fetchone()
        baseline_sha = None
        if event is not None:
            payload = json.loads(str(event["payload_json"]))
            baseline_sha = str(payload["detail"]["binding_sha256"])
        return self.step_for_invocation(claim.work_item.id, baseline_sha)

    def preparation_resume_consumed(
        self,
        intent: VerifierPreparationIntent,
        claim: QueueClaim,
    ) -> bool:
        from ai_software_engineer.work_queue.preparation_resume import preparation_resume_consumed

        return preparation_resume_consumed(self, self._dsn, intent, claim)

    """T046 plus explicit native-reservation adoption and accepted-output receipts."""

    @staticmethod
    def _require_knowledge_window_predecessor(
        current: KnowledgePreparationRetryEvidence,
        previous: KnowledgePreparationRetryEvidence | None,
    ) -> None:
        if current.expansion_number == 1:
            if previous is not None:
                raise QueueConflict("知识准备不能丢弃已有扩窗历史重新获得额度")
            return
        if previous is None or (
            current.expansion_number != previous.expansion_number + 1
            or current.root_intent_sha256 != previous.root_intent_sha256
            or current.initial_timeout_seconds != previous.initial_timeout_seconds
            or current.current_timeout_seconds != previous.next_timeout_seconds
            or current.maximum_timeout_seconds != previous.maximum_timeout_seconds
            or current.scope != previous.scope
            or current.task_id != previous.task_id
            or current.role is not previous.role
            or current.requirement_id != previous.requirement_id
            or (current.delivery_requirement_id or current.requirement_id)
            != (previous.delivery_requirement_id or previous.requirement_id)
            or current.source_revision != previous.source_revision
            or current.snapshot_sha256 != previous.snapshot_sha256
        ):
            raise QueueConflict("知识准备扩窗不匹配已消费的原决定链")

    def knowledge_preparation_retry(
        self, work_item_id: str, *, _depth: int = 0
    ) -> KnowledgePreparationRetryEvidence | None:
        """Read an already consumed exact decision; current configuration has no say."""
        if _depth >= 512:
            raise QueueCorruption("知识准备工作项历史超过有界读取上限, 需工程核验")
        current = self.get(work_item_id)
        parent_id = current.parent_work_item_id
        if parent_id is None:
            return None
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
                "AND event_type='WAIT_RESOLVED' "
                "AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.detail.next_work_item_id'))=%s "
                "ORDER BY sequence DESC LIMIT 2",
                (parent_id, current.id),
            )
            events = cursor.fetchall()
            cursor.execute("SELECT payload_json FROM tasks WHERE id=%s", (current.task_id,))
            task_row = cursor.fetchone()
            if task_row is None:
                raise QueueCorruption("知识准备决定没有对应任务")
            task = _decode_task(current.task_id, str(task_row["payload_json"]))
        step = self.step(current.id)
        parent = self.get(parent_id)
        parent_step = self.step(parent_id)
        if (
            parent.task_id != current.task_id
            or parent.repository_id != current.repository_id
            or parent.repository_scopes != current.repository_scopes
            or parent_step.allocation_sha256 != step.allocation_sha256
        ):
            raise QueueCorruption("知识准备工作项祖先改变了原任务或仓库范围")
        if (parent.role, parent.checkpoint_sequence, parent_step.boundary.source_revision) != (
            current.role,
            current.checkpoint_sequence,
            step.boundary.source_revision,
        ):
            return None
        previous = self.knowledge_preparation_retry(parent_id, _depth=_depth + 1)
        matches: list[DeliveryResolution] = []
        for row in events:
            detail = json.loads(str(row["payload_json"])).get("detail", {})
            if detail.get("next_work_item_id") != current.id:
                continue
            resolution = DeliveryResolution.model_validate(detail.get("resolution"))
            resolution.validate_integrity()
            if detail.get("resolution_sha256") != resolution.resolution_sha256:
                raise QueueCorruption("已消费知识准备决定的完整正文与摘要不一致")
            matches.append(resolution)
        if not matches:
            return previous
        if len(matches) != 1:
            raise QueueCorruption("知识准备存在不唯一的已消费决定")
        resolution = matches[0]
        if resolution.expected_task_intent_sha256 != task_intent_sha256(task):
            raise QueueCorruption("知识准备决定不再符合当前任务的冻结范围")
        if resolution.resolution_kind is not DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION:
            return previous
        evidence = resolution.knowledge_preparation
        assert evidence is not None
        if (
            current.id != "work_" + resolution.resolution_sha256
            or evidence.work_item_id != parent_id
            or current.task_id != evidence.task_id
            or current.repository_id != evidence.scope.repository_id
            or current.role is not evidence.role
            or current.attempt != evidence.original_attempt + 1
            or current.checkpoint_sequence != evidence.checkpoint_sequence
            or step.boundary.source_revision != evidence.source_revision
        ):
            raise QueueCorruption("知识准备下一窗口不属于当前工作项、角色和源码")
        self._require_knowledge_window_predecessor(evidence, previous)
        return evidence

    def knowledge_timeout(self, task: Task, claim: QueueClaim) -> int | None:
        """A fresh real claim may use only its own consumed next execution window."""
        from ai_software_engineer.knowledge.preparation_retry import claim_identity_sha256

        original = self.original_claim(claim.lease.id)
        if claim_identity_sha256(original) != claim_identity_sha256(claim):
            raise QueueConflict("知识准备窗口请求改变了当前真实领取身份")
        item = self.get(claim.work_item.id)
        if (
            task.id != item.task_id
            or item.status not in {WorkItemStatus.LEASED, WorkItemStatus.RUNNING}
            or (
                item.task_id,
                item.role,
                item.attempt,
                item.checkpoint_sequence,
                item.dispatch_sequence,
            )
            != (
                claim.work_item.task_id,
                claim.work_item.role,
                claim.work_item.attempt,
                claim.work_item.checkpoint_sequence,
                claim.work_item.dispatch_sequence,
            )
        ):
            raise QueueConflict("知识准备窗口请求不属于当前任务和执行身份")
        evidence = self.knowledge_preparation_retry(item.id)
        if evidence is not None and (
            evidence.scope.repository_root != task.repository
            or (
                task.engineering_policy is not None
                and task.engineering_policy.scope != evidence.scope
            )
        ):
            raise QueueConflict("知识准备窗口请求改变了冻结工程范围")
        return evidence.next_timeout_seconds if evidence is not None else None

    def resolve_wait(
        self,
        resolution: DeliveryResolution,
        *,
        invocation_records: KnowledgeRecordStore | None = None,
    ) -> QueuedWorkItem:
        """Consume sealed engineering proof with Task, queue and budget in one fence."""
        resolution.validate_integrity()
        now = self._clock()
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self._lock_authority(cursor)
            current = self._get_locked(cursor, resolution.work_item_id, lock=True)
            if (
                current.wait_disposition is not None
                and current.wait_disposition.facts.classification == "EXECUTION_BASELINE_PAUSED"
            ):
                raise QueueConflict("工程暂停不能通过调查或普通等待处理解除; 请明确批准继续原需求")
            cursor.execute(
                "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
                "AND event_type='WAIT_RESOLVED' ORDER BY sequence DESC FOR UPDATE",
                (current.id,),
            )
            for prior in cursor.fetchall():
                payload = json.loads(str(prior["payload_json"]))
                detail = payload.get("detail", {})
                if detail.get("resolution_sha256") == resolution.resolution_sha256:
                    if detail.get("resolution") != resolution.to_wire():
                        raise QueueCorruption(
                            "consumed engineering decision changed its exact body"
                        )
                    return self._get_locked(cursor, str(detail["next_work_item_id"]), lock=True)
            disposition = current.wait_disposition
            if (
                current.status
                not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
                or disposition is None
                or disposition.disposition_sha256 != resolution.expected_disposition_sha256
                or current.task_id != resolution.task_id
            ):
                raise QueueConflict("engineering decision does not match the current wait")
            cursor.execute(
                "SELECT payload_json,revision FROM tasks WHERE id=%s FOR UPDATE", (current.task_id,)
            )
            row = cursor.fetchone()
            if row is None:
                raise QueueCorruption("waiting Task is missing")
            task = _decode_task(current.task_id, str(row["payload_json"]))
            step = self.step(current.id)
            if resolution.authorization_source == "organization_engineering_policy":
                admission = resolution.engineering_admission
                if (
                    admission is None
                    or task.engineering_policy is None
                    or admission.policy != task.engineering_policy
                    or admission.task_intent_sha256 != task_intent_sha256(task)
                    or admission.policy.scope.repository_id != current.repository_id
                    or admission.policy.scope.repository_root != task.repository
                    or admission.capabilities != (EngineeringCapability.DELIVERY_WAIT_RESOLUTION,)
                ):
                    raise QueueConflict("自动工程处理不符合原任务的精确冻结授权")
            if (
                task.status in {TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.DONE}
                or task_intent_sha256(task) != resolution.expected_task_intent_sha256
                or digest(task.to_wire()) != resolution.task_snapshot_sha256
                or row["revision"] != resolution.task_revision
                or resolution.task_revision != resolution.expected_checkpoint_sequence
                or record_digest(step) != resolution.step_sha256
                or step.boundary.source_revision != resolution.expected_source_revision
            ):
                raise QueueConflict("engineering decision Task or source facts drifted")
            cursor.execute(
                "SELECT lease_id FROM work_queue_claims WHERE work_item_id=%s "
                "AND state='ACTIVE' FOR UPDATE",
                (current.id,),
            )
            if cursor.fetchone() is not None:
                raise QueueLeaseLost("a live claim prevents engineering wait resolution")
            if resolution.resolution_kind in {
                DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
                DeliveryResolutionKind.REVERIFY_CANDIDATE,
                DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION,
                DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION,
                DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT,
                DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION,
                DeliveryResolutionKind.RETRY_REJECTED_WORKSPACE_ADMISSION,
            }:
                if current.role not in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER):
                    raise QueueConflict("wait does not belong to a delivery role")
                failure = resolution.retry_failure
                if resolution.resolution_kind is DeliveryResolutionKind.REVERIFY_CANDIDATE:
                    verification = resolution.verification_retry
                    if (
                        current.role is not AgentRole.QA
                        or verification is None
                        or verification.candidate_revision != step.boundary.source_revision
                        or task.work_budget_exhausted
                        or task.attempts >= task.max_attempts
                    ):
                        raise QueueConflict("候选复验缺少精确 QA 证据或冻结工作额度")
                    cursor.execute(
                        "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
                        "WHERE task_id=%s",
                        (task.id,),
                    )
                    accepted = tuple(
                        _decode(record, AcceptedRoleArtifact) for record in cursor.fetchall()
                    )
                    if not any(
                        record.work_item_id == current.id
                        and record.receipt.artifact_id == verification.previous_qa_artifact_id
                        and record.receipt.sha256 == verification.previous_qa_sha256
                        and record.source_revision == verification.candidate_revision
                        and record.run_id == verification.previous_run_id
                        and record.context_manifest_id == verification.previous_context_manifest_id
                        for record in accepted
                    ):
                        raise QueueConflict("候选复验没有原 QA 的精确接纳记录")
                    updated_task = Task.model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
                elif (
                    resolution.resolution_kind is DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION
                ):
                    preparation = resolution.verifier_preparation
                    if (
                        current.role not in {AgentRole.QA, AgentRole.REVIEWER}
                        or preparation is None
                        or preparation.native_execution_state != "FINISHED"
                        or preparation.candidate_revision != step.boundary.source_revision
                        or task.work_budget_exhausted
                        or task.attempts >= task.max_attempts
                    ):
                        raise QueueConflict("验证准备重试缺少精确已终结证据或冻结工作额度")
                    updated_task = Task.model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
                elif (
                    resolution.resolution_kind is DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION
                ):
                    from ai_software_engineer.knowledge.preparation_retry import (
                        claim_identity_sha256,
                    )

                    knowledge = resolution.knowledge_preparation
                    if (
                        knowledge is None
                        or disposition.facts.classification != "KNOWLEDGE_PREPARATION_LIMIT"
                        or disposition.facts.evidence_ids
                        != ("knowledge-preparation://" + knowledge.outcome_sha256,)
                        or knowledge.task_id != task.id
                        or knowledge.work_item_id != current.id
                        or knowledge.role is not current.role
                        or knowledge.original_attempt != current.attempt
                        or knowledge.original_attempt != task.attempts
                        or knowledge.checkpoint_sequence != current.checkpoint_sequence
                        or knowledge.scope.repository_id != current.repository_id
                        or knowledge.scope.repository_root != task.repository
                        or knowledge.source_revision != step.boundary.source_revision
                        or task.work_budget_exhausted
                        or task.attempts >= task.max_attempts
                    ):
                        raise QueueConflict("知识准备续跑缺少精确停止记录、冻结窗口或剩余工作额度")
                    original_knowledge_claim = self.original_claim(knowledge.original_lease_id)
                    if claim_identity_sha256(
                        original_knowledge_claim
                    ) != knowledge.original_claim_sha256 or (
                        original_knowledge_claim.work_item.id,
                        original_knowledge_claim.work_item.dispatch_sequence,
                    ) != (current.id, knowledge.original_dispatch_sequence):
                        raise QueueConflict("知识准备续跑改变了原执行的领取身份")
                    self._require_knowledge_window_predecessor(
                        knowledge, self.knowledge_preparation_retry(current.id)
                    )
                    cursor.execute(
                        "SELECT lease_id FROM work_queue_claims WHERE task_id=%s "
                        "AND state='ACTIVE' FOR UPDATE",
                        (task.id,),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("原任务仍有活跃领取, 不能开始知识准备续跑")
                    updated_task = Task.model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
                elif (
                    resolution.resolution_kind
                    is DeliveryResolutionKind.RETRY_REJECTED_WORKSPACE_ADMISSION
                ):
                    from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256

                    workspace = resolution.rejected_workspace_admission
                    if workspace is None:
                        raise QueueConflict("工作区准入恢复缺少可信拒绝证明")
                    workspace.validate_integrity()
                    if (
                        current.role is not AgentRole.CODER
                        or task.status is not TaskStatus.IMPLEMENTING
                        or disposition.facts.classification
                        not in {"NONTRANSIENT_INFRA", "PLATFORM_BUG", "INVALID_OUTPUT"}
                        or workspace.task_id != task.id
                        or workspace.work_item_id != current.id
                        or workspace.role is not current.role
                        or workspace.attempt != task.attempts
                        or workspace.attempt != current.attempt
                        or workspace.dispatch_sequence != current.dispatch_sequence
                        or workspace.checkpoint_sequence != current.checkpoint_sequence
                        or workspace.source_revision != step.boundary.source_revision
                        or workspace.scope.repository_id != current.repository_id
                        or workspace.scope.repository_root != task.repository
                        or (
                            task.engineering_policy is not None
                            and workspace.scope != task.engineering_policy.scope
                        )
                        or task.work_budget_exhausted
                        or task.attempts >= task.max_attempts
                    ):
                        raise QueueConflict("工作区准入恢复改变了原输入或没有剩余普通工作额度")
                    workspace_claim = self.original_claim(workspace.lease_id)
                    if (
                        claim_identity_sha256(workspace_claim) != workspace.claim_sha256
                        or workspace_claim.work_item.id != current.id
                        or workspace_claim.work_item.dispatch_sequence != current.dispatch_sequence
                        or workspace_claim.work_item.attempt != current.attempt
                    ):
                        raise QueueConflict("工作区准入恢复改变了原真实领取身份")
                    cursor.execute(
                        "SELECT lease_id FROM work_queue_claims WHERE task_id=%s "
                        "AND state='ACTIVE' FOR UPDATE",
                        (task.id,),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("任务仍有活跃领取, 不能恢复工作区准入")
                    cursor.execute(
                        "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
                        "WHERE task_id=%s FOR UPDATE",
                        (task.id,),
                    )
                    if any(
                        _decode(row, AcceptedRoleArtifact).work_item_id == current.id
                        for row in cursor.fetchall()
                    ):
                        raise QueueConflict("目标工作区准入工作项已有接纳结果")
                    cursor.execute(
                        "SELECT sequence FROM work_queue_events WHERE work_item_id=%s "
                        "AND event_type='COMPLETED' LIMIT 1",
                        (current.id,),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("目标工作区准入工作项已完成推进")
                    updated_task = Task.model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
                elif (
                    resolution.resolution_kind
                    is DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION
                ):
                    from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256

                    rejected_knowledge = resolution.rejected_knowledge
                    if (
                        rejected_knowledge is None
                        or current.role is not AgentRole.CODER
                        or task.status is not TaskStatus.IMPLEMENTING
                        or not rejected_knowledge_wait_matches(
                            disposition.facts, rejected_knowledge.observation_sha256
                        )
                        or (
                            rejected_knowledge.current_draft_sha256 is not None
                            and resolution.authorization_source != "engineering_operator_decision"
                        )
                        or rejected_knowledge.task_id != task.id
                        or rejected_knowledge.work_item_id != current.id
                        or rejected_knowledge.role is not current.role
                        or rejected_knowledge.original_attempt != task.attempts
                        or rejected_knowledge.original_attempt != current.attempt
                        or rejected_knowledge.current_dispatch_sequence != current.dispatch_sequence
                        or rejected_knowledge.checkpoint_sequence != current.checkpoint_sequence
                        or rejected_knowledge.source_revision != step.boundary.source_revision
                        or rejected_knowledge.scope.repository_id != current.repository_id
                        or rejected_knowledge.scope.repository_root != task.repository
                        or (
                            task.engineering_policy is not None
                            and rejected_knowledge.scope != task.engineering_policy.scope
                        )
                        or task.work_budget_exhausted
                        or task.attempts >= task.max_attempts
                    ):
                        raise QueueConflict("知识评估拒绝恢复缺少精确原输入与剩余普通工作额度")
                    original_rejected = self.original_claim(rejected_knowledge.original_lease_id)
                    current_rejected = self.original_claim(rejected_knowledge.current_lease_id)
                    if (
                        claim_identity_sha256(original_rejected)
                        != rejected_knowledge.original_claim_sha256
                        or claim_identity_sha256(current_rejected)
                        != rejected_knowledge.current_claim_sha256
                        or original_rejected.work_item.id != current.id
                        or current_rejected.work_item.id != current.id
                        or original_rejected.work_item.dispatch_sequence
                        != rejected_knowledge.original_dispatch_sequence
                        or current_rejected.work_item.dispatch_sequence != current.dispatch_sequence
                        or (
                            original_rejected.lease.id != current_rejected.lease.id
                            and rejected_knowledge.carry_refusal_sha256 is None
                        )
                    ):
                        raise QueueConflict("知识评估拒绝恢复改变了原真实领取或当前接续拒绝")
                    cursor.execute(
                        "SELECT lease_id FROM work_queue_claims WHERE task_id=%s "
                        "AND state='ACTIVE' FOR UPDATE",
                        (task.id,),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("任务仍有活跃领取, 不能恢复知识准备")
                    cursor.execute(
                        "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
                        "WHERE task_id=%s FOR UPDATE",
                        (task.id,),
                    )
                    if any(
                        _decode(row, AcceptedRoleArtifact).work_item_id == current.id
                        for row in cursor.fetchall()
                    ):
                        raise QueueConflict("目标知识准备工作项已有接纳结果")
                    cursor.execute(
                        "SELECT sequence FROM work_queue_events WHERE work_item_id=%s "
                        "AND event_type='COMPLETED' LIMIT 1",
                        (current.id,),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("目标知识准备工作项已完成推进")
                    updated_task = Task.model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
                elif (
                    resolution.resolution_kind is DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT
                ):
                    from ai_software_engineer.knowledge.preparation_retry import (
                        claim_identity_sha256,
                    )

                    rejected = resolution.rejected_output
                    if (
                        rejected is None
                        or current.role is not AgentRole.CODER
                        or task.status is not TaskStatus.IMPLEMENTING
                        or disposition.facts.classification
                        not in {"PLATFORM_BUG", "INVALID_OUTPUT"}
                        or rejected.task_id != task.id
                        or rejected.work_item_id != current.id
                        or rejected.original_attempt != task.attempts
                        or rejected.original_attempt != current.attempt
                        or rejected.original_dispatch_sequence != current.dispatch_sequence
                        or rejected.checkpoint_sequence != current.checkpoint_sequence
                        or rejected.source_revision != step.boundary.source_revision
                        or rejected.scope.repository_id != current.repository_id
                        or rejected.scope.repository_root != task.repository
                        or (
                            task.engineering_policy is not None
                            and rejected.scope != task.engineering_policy.scope
                        )
                        or task.work_budget_exhausted
                        or task.attempts >= task.max_attempts
                    ):
                        raise QueueConflict("被拒产出续跑缺少当前精确开发记录与剩余工作额度")
                    rejected_claim = self.original_claim(rejected.original_lease_id)
                    if (
                        claim_identity_sha256(rejected_claim) != rejected.original_claim_sha256
                        or rejected_claim.work_item.id != current.id
                    ):
                        raise QueueConflict("被拒产出续跑改变了原真实领取身份")
                    cursor.execute(
                        "SELECT lease_id FROM work_queue_claims WHERE task_id=%s "
                        "AND state='ACTIVE' FOR UPDATE",
                        (task.id,),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("原开发任务仍有活跃领取, 不能恢复被拒产出")
                    cursor.execute(
                        "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
                        "WHERE task_id=%s FOR UPDATE",
                        (task.id,),
                    )
                    publications = tuple(
                        _decode(row, AcceptedRoleArtifact) for row in cursor.fetchall()
                    )
                    retired = self.retired_rejected_outputs(task.id, cursor=cursor)
                    if any(
                        publication.checkpoint_sequence >= current.checkpoint_sequence
                        and not is_retired_rejected_publication(
                            publication,
                            retired,
                            current_work_item_id=current.id,
                            current_run_id=rejected.previous_run_id,
                            checkpoint_sequence=current.checkpoint_sequence,
                        )
                        and (
                            publication.work_item_id != current.id
                            or publication.lease_id != rejected.original_lease_id
                            or publication.dispatch_sequence != current.dispatch_sequence
                            or publication.run_id != rejected.previous_run_id
                            or publication.context_manifest_id
                            != rejected.previous_context_manifest_id
                            or publication.source_revision != rejected.source_revision
                            or publication.receipt.artifact_id != rejected.rejected_artifact_id
                            or publication.receipt.sha256 != rejected.rejected_artifact_sha256
                        )
                        for publication in publications
                    ):
                        raise QueueConflict("原开发之后已有独立发布结果, 不能恢复被拒草稿")
                    cursor.execute(
                        "SELECT event_id FROM state_events WHERE task_id=%s AND "
                        "JSON_CONTAINS(JSON_EXTRACT(payload_json,'$.artifact_ids'),"
                        "JSON_QUOTE(%s)) LIMIT 1",
                        (task.id, rejected.rejected_artifact_id),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("原产出已被交付 checkpoint 采纳, 不能作为被拒草稿重试")
                    cursor.execute(
                        "SELECT sequence FROM work_queue_events WHERE work_item_id=%s "
                        "AND event_type='COMPLETED' LIMIT 1",
                        (current.id,),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("原开发结果已经完成推进, 不能作为被拒草稿重试")
                    updated_task = Task.model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
                elif resolution.retry_cause == "provider_transient":
                    if (
                        failure is None
                        or failure.role is not current.role
                        or failure.attempt != task.attempts
                    ):
                        raise QueueConflict(
                            "new execution requires the exact sealed interruption budget fact"
                        )
                    updated_task = task.with_retry_failure(failure)
                elif resolution.retry_cause == "service_pause":
                    pause = resolution.verifier_pause
                    if (
                        pause is None
                        or current.role not in {AgentRole.QA, AgentRole.REVIEWER}
                        or (
                            disposition.facts.classification != "SERVICE_PAUSED"
                            or pause.request.role != current.role
                            or pause.request.attempt != task.attempts
                            or pause.request.task_id != task.id
                            or pause.request.source_revision != resolution.expected_source_revision
                            or failure is not None
                            or task.work_budget_exhausted
                            or task.attempts >= task.max_attempts
                        )
                    ):
                        raise QueueConflict(
                            "service pause requires an exact verifier stop "
                            "and frozen work allowance"
                        )
                    updated_task = Task.model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
                elif resolution.retry_cause == "local_execution_limit":
                    if (
                        failure is not None
                        or task.work_budget_exhausted
                        or task.attempts >= task.max_attempts
                    ):
                        raise QueueConflict("local interruption has no frozen work allowance")
                    updated_task = Task.model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
                else:
                    raise QueueConflict("retry requires a typed sealed interruption cause")
                if updated_task.attempts <= task.attempts:
                    raise QueueConflict("no frozen execution allowance remains")
                cursor.execute(
                    "UPDATE tasks SET payload_json=%s WHERE id=%s",
                    (_encode(updated_task.to_wire()), task.id),
                )
                identity = "work_" + resolution.resolution_sha256
                next_item = QueuedWorkItem.model_validate(
                    {
                        **current.to_wire(),
                        "id": identity,
                        "attempt": updated_task.attempts,
                        "status": WorkItemStatus.READY,
                        "wait_reason": None,
                        "wait_disposition": None,
                        "available_at": None,
                        "parent_work_item_id": current.id,
                        "dispatch_sequence": 0,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                boundary = RoleRunBoundary(
                    task.id,
                    current.role,
                    updated_task.attempts,
                    resolution.task_revision,
                    resolution.expected_source_revision,
                )
                next_step = QueuedRoleStep(
                    work_item=next_item,
                    boundary=boundary,
                    allocation_sha256=step.allocation_sha256,
                )
                _put(cursor, "work_queue_steps", identity, task.id, next_step)
                next_item = self._enqueue_locked(cursor, next_item)
                settled = current.model_copy(
                    update={
                        "status": WorkItemStatus.CLOSED,
                        "updated_at": now,
                        "wait_reason": None,
                        "wait_disposition": None,
                    }
                )
            else:
                if resolution.retry_failure is not None:
                    raise QueueConflict("noninvoking resolution cannot add a retry failure")
                if (
                    resolution.resolution_kind
                    is DeliveryResolutionKind.RETRY_REJECTED_STATIC_QA_OUTPUT
                ):
                    next_item, settled = self._rejected_static_qa_successor(
                        cursor,
                        resolution,
                        current,
                        disposition,
                        task,
                        step,
                        now,
                        invocation_records,
                    )
                elif resolution.resolution_kind is DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY:
                    next_item, settled = self._static_qa_successor(
                        cursor, resolution, current, disposition, task, step, now
                    )
                if resolution.resolution_kind is DeliveryResolutionKind.SCHEDULE_RECOVERY_INPUT:
                    pre_context = resolution.pre_context_recovery_input
                    if (
                        current.role is not AgentRole.CODER
                        or disposition.facts.classification != "CONTEXT_CAPACITY"
                        or any(
                            value.startswith("context-capacity://")
                            for value in disposition.facts.evidence_ids
                        )
                        or task.status is not TaskStatus.IMPLEMENTING
                        or task.attempts != current.attempt
                        or task.work_budget_exhausted
                        or pre_context is None
                        or pre_context.worktree_head_revision != step.boundary.source_revision
                    ):
                        raise QueueConflict("预 Context 恢复不属于当前原 Coder 容量等待")
                    claims = self.claims_for_work_item(current.id)
                    if len(claims) != 1 or (
                        claims[0].lease.id != pre_context.original_lease_id
                        or digest(claims[0].to_wire()) != pre_context.original_claim_sha256
                        or claims[0].work_item.dispatch_sequence != current.dispatch_sequence
                        or claims[0].work_item.checkpoint_sequence != current.checkpoint_sequence
                    ):
                        raise QueueConflict("预 Context 恢复的真实原 claim 已变化")
                    cursor.execute(
                        "SELECT id FROM work_queue_accepted_artifacts WHERE task_id=%s "
                        "AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.work_item_id'))=%s "
                        "LIMIT 1 FOR UPDATE",
                        (task.id, current.id),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict(
                            "原 Coder 工作项已有接纳产出, 不能重领预 Context 容量等待"
                        )
                if (
                    resolution.resolution_kind is not DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY
                    and (
                        resolution.knowledge_pause is not None
                        or any(
                            value.startswith("knowledge-pause://")
                            for value in disposition.facts.evidence_ids
                        )
                    )
                ):
                    from ai_software_engineer.knowledge.claim_identity import (
                        claim_identity_sha256,
                    )

                    paused = resolution.knowledge_pause
                    if (
                        resolution.resolution_kind is not DeliveryResolutionKind.RESUME_UNINVOKED
                        or paused is None
                        or disposition.facts.classification != "SERVICE_PAUSED"
                        or disposition.facts.evidence_ids
                        != ("knowledge-pause://" + paused.outcome_sha256,)
                        or paused.task_id != task.id
                        or paused.work_item_id != current.id
                        or paused.role is not current.role
                        or paused.original_attempt != current.attempt
                        or paused.original_attempt != task.attempts
                        or paused.original_dispatch_sequence != current.dispatch_sequence
                        or paused.checkpoint_sequence != current.checkpoint_sequence
                        or paused.scope.repository_id != current.repository_id
                        or paused.scope.repository_root != task.repository
                        or current.repository_scopes != (task.repository,)
                        or paused.source_revision != step.boundary.source_revision
                        or task.status
                        is not {
                            AgentRole.CODER: TaskStatus.IMPLEMENTING,
                            AgentRole.QA: TaskStatus.QA,
                            AgentRole.REVIEWER: TaskStatus.REVIEW,
                        }.get(current.role)
                        or (
                            task.engineering_policy is not None
                            and paused.scope != task.engineering_policy.scope
                        )
                    ):
                        raise QueueConflict("知识暂停继续缺少精确未调用证明或原任务绑定已变化")
                    original_paused_claim = self.original_claim(paused.original_lease_id)
                    if claim_identity_sha256(
                        original_paused_claim
                    ) != paused.original_claim_sha256 or (
                        original_paused_claim.work_item.id,
                        original_paused_claim.work_item.task_id,
                        original_paused_claim.work_item.role,
                        original_paused_claim.work_item.attempt,
                        original_paused_claim.work_item.checkpoint_sequence,
                        original_paused_claim.work_item.dispatch_sequence,
                        original_paused_claim.work_item.repository_id,
                        original_paused_claim.work_item.repository_scopes,
                    ) != (
                        current.id,
                        task.id,
                        current.role,
                        current.attempt,
                        current.checkpoint_sequence,
                        current.dispatch_sequence,
                        current.repository_id,
                        current.repository_scopes,
                    ):
                        raise QueueConflict("知识暂停继续改变了原真实领取身份")
                    cursor.execute(
                        "SELECT lease_id FROM work_queue_claims WHERE task_id=%s "
                        "AND state='ACTIVE' FOR UPDATE",
                        (task.id,),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("原任务仍有活跃领取, 不能继续知识准备")
                    cursor.execute(
                        "SELECT id FROM work_queue_accepted_artifacts WHERE task_id=%s "
                        "AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.work_item_id'))=%s "
                        "LIMIT 1 FOR UPDATE",
                        (task.id, current.id),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("主角色已有接纳产出, 不能按未调用知识暂停恢复")
                    cursor.execute(
                        "SELECT sequence FROM work_queue_events WHERE work_item_id=%s "
                        "AND event_type='COMPLETED' LIMIT 1 FOR UPDATE",
                        (current.id,),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("知识暂停原工作项已完成推进")
                if (
                    resolution.resolution_kind
                    not in {
                        DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY,
                        DeliveryResolutionKind.SCHEDULE_RECOVERY_INPUT,
                    }
                    and disposition.facts.classification == "CONTEXT_CAPACITY"
                ):
                    preparation = resolution.verifier_preparation
                    expected_stage = (
                        TaskStatus.QA if current.role is AgentRole.QA else TaskStatus.REVIEW
                    )
                    if (
                        resolution.resolution_kind is not DeliveryResolutionKind.RESUME_UNINVOKED
                        or current.role not in {AgentRole.QA, AgentRole.REVIEWER}
                        or preparation is None
                        or preparation.context_capacity_receipt_sha256 is None
                        or preparation.context_capacity_claim_sha256 is None
                        or preparation.native_failure_code is not None
                        or preparation.budget_source is not None
                        or disposition.facts.evidence_ids
                        != ("context-capacity://" + preparation.context_capacity_receipt_sha256,)
                        or preparation.candidate_revision != step.boundary.source_revision
                        or current.attempt != task.attempts
                        or task.status is not expected_stage
                    ):
                        raise QueueConflict("容量继续缺少当前验证角色的精确未调用证明")
                    capacity_claims = tuple(
                        claim
                        for claim in self.claims_for_work_item(current.id)
                        if digest(claim.to_wire()) == preparation.context_capacity_claim_sha256
                    )
                    if len(capacity_claims) != 1 or (
                        capacity_claims[0].work_item.dispatch_sequence != current.dispatch_sequence
                        or capacity_claims[0].work_item.checkpoint_sequence
                        != current.checkpoint_sequence
                        or capacity_claims[0].work_item.role is not current.role
                        or capacity_claims[0].work_item.attempt != current.attempt
                    ):
                        raise QueueConflict("容量继续与原真实 claim 或当前队列世代不一致")
                    cursor.execute(
                        "SELECT id FROM work_queue_accepted_artifacts WHERE task_id=%s "
                        "AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.work_item_id'))=%s "
                        "LIMIT 1 FOR UPDATE",
                        (task.id, current.id),
                    )
                    if cursor.fetchone() is not None:
                        raise QueueConflict("验证角色已有接纳产出, 不能按未调用容量恢复")
                if resolution.resolution_kind is DeliveryResolutionKind.REPLAY_RECORDED_RESULT:
                    original = resolution.original_authority
                    if original is None:
                        raise QueueConflict(
                            "result replay requires the original producer authority"
                        )
                    claim = self.original_claim(original.lease.id)
                    if (
                        claim.assignment != original.assignment
                        or claim.lease != original.lease
                        or claim.model_selection != original.model_selection
                        or (
                            claim.work_item.id,
                            claim.work_item.role,
                            claim.work_item.attempt,
                            claim.work_item.checkpoint_sequence,
                        )
                        != (
                            current.id,
                            current.role,
                            current.attempt,
                            current.checkpoint_sequence,
                        )
                        or current.preferred_agent_id != original.assignment.agent_id
                    ):
                        raise QueueConflict("result replay changed the original frozen producer")
                if resolution.resolution_kind not in {
                    DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY,
                    DeliveryResolutionKind.RETRY_REJECTED_STATIC_QA_OUTPUT,
                }:
                    next_item = current.model_copy(
                        update={
                            "status": WorkItemStatus.READY,
                            "updated_at": now,
                            "wait_reason": None,
                            "wait_disposition": None,
                            "dispatch_sequence": current.dispatch_sequence + 1,
                        }
                    )
                    settled = next_item
            self._update_item(cursor, settled)
            self._append_event(
                cursor,
                settled,
                from_status=current.status,
                event_type="WAIT_RESOLVED",
                lease_id=None,
                occurred_at=now,
                detail={
                    "resolution_sha256": resolution.resolution_sha256,
                    "next_work_item_id": next_item.id,
                    "resolution": resolution.to_wire(),
                    "budget_refund": False,
                },
            )
            return next_item

    def __init__(
        self,
        dsn: str,
        *,
        capacity_reader: CapacityReader | None = None,
        authority_lock: AuthorityLock | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._capacity_reader = capacity_reader
        self._external_lock = authority_lock
        self._clock = clock or (lambda: datetime.now(UTC))
        super().__init__(dsn)
        with (
            closing(open_mysql_connection(dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            for table in _TABLES:
                cursor.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} (id VARCHAR(128) PRIMARY KEY, "
                    "task_id VARCHAR(128) NOT NULL, payload_json JSON NOT NULL, "
                    f"sha256 CHAR(64) NOT NULL, KEY ix_{table}_task(task_id)) "
                    "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"
                )
                cursor.execute(f"SHOW COLUMNS FROM {table}")
                if {row["Field"] for row in cursor.fetchall()} != {
                    "id",
                    "task_id",
                    "payload_json",
                    "sha256",
                }:
                    raise QueueCorruption("unexpected role queue record schema")

    def _lock_authority(self, cursor: object) -> None:
        typed = cast(DictCursor, cursor)
        if self._external_lock is not None:
            self._external_lock(typed)
        super()._lock_authority(typed)

    def _external_facts(self, cursor: DictCursor, now: datetime) -> WorkforceFacts:
        return (
            self._capacity_reader(cursor, now)
            if self._capacity_reader is not None
            else WorkforceFacts()
        )

    def list_active_leases(self, *, now: datetime) -> tuple[TaskLease, ...]:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            external = self._external_facts(cursor, now)
        return (*super().list_active_leases(now=now), *external.leases)

    def list_assignments(self) -> tuple[RoleAssignment, ...]:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            external = self._external_facts(cursor, datetime.now(UTC))
        return (*super().list_assignments(), *external.assignments)

    def _validate_capacity_locked(
        self, cursor: object, assignment: RoleAssignment, *, agent_capacity: int, now: datetime
    ) -> None:
        facts = self._external_facts(cast(DictCursor, cursor), now)
        used = sum(
            lease.capacity_units for lease in facts.leases if lease.agent_id == assignment.agent_id
        )
        super()._validate_capacity_locked(
            cursor, assignment, agent_capacity=agent_capacity - used, now=now
        )
        try:
            validate_assignment_independence(assignment, facts.assignments)
        except ValueError as error:
            raise QueueConflict(str(error)) from error

    def admit(self, admission: RoleQueueAdmission, step: QueuedRoleStep) -> None:
        if (
            admission.task_id != step.boundary.task_id
            or admission.allocation_sha256 != step.allocation_sha256
            or admission.repository_id != step.work_item.repository_id
        ):
            raise QueueConflict("admission does not bind step")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self._lock_authority(cursor)
            _put(cursor, "work_queue_admissions", admission.task_id, admission.task_id, admission)
            _put(cursor, "work_queue_steps", step.work_item.id, admission.task_id, step)
            self._enqueue_locked(cursor, step.work_item)

    def admission(self, task_id: str) -> RoleQueueAdmission | None:
        return self._find("work_queue_admissions", task_id, RoleQueueAdmission)

    def step(self, work_item_id: str) -> QueuedRoleStep:
        from ai_software_engineer.work_queue.baseline import effective_step

        return effective_step(self, self.original_step(work_item_id))

    def step_for_invocation(self, work_item_id: str, baseline_sha256: str | None) -> QueuedRoleStep:
        from ai_software_engineer.work_queue.baseline import effective_step

        return effective_step(
            self, self.original_step(work_item_id), baseline_sha256=baseline_sha256, latest=False
        )

    def original_step(self, work_item_id: str) -> QueuedRoleStep:
        step = self._find("work_queue_steps", work_item_id, QueuedRoleStep)
        if step is None:
            raise QueueNotFound("role step binding missing")
        if step.work_item.id != work_item_id:
            raise QueueCorruption("role step identity mismatch")
        return step

    def items_for_task(self, task_id: str) -> tuple[QueuedWorkItem, ...]:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT id,payload_json FROM work_queue_items WHERE task_id=%s "
                "ORDER BY checkpoint_sequence,attempt,id",
                (task_id,),
            )
            return tuple(self._decode_item(row) for row in cursor.fetchall())

    def cancellation_fence(self, cursor: DictCursor, task_id: str) -> None:
        """Fence a user-cancelled Task mutation against current execution authority.

        The caller owns all historical Task process locks and has already sealed
        the exact deletion receipt. This callback is compatible with the existing
        MySqlTaskRepository mutation fence; it neither terminates Task state nor
        releases a claim itself.
        """
        self._lock_authority(cursor)
        self._require_cancelled_task_idle(cursor, task_id, now=self._clock())

    def close_cancelled_task(
        self,
        task: Task,
        *,
        expected_items: tuple[QueuedWorkItem, ...],
        cancellation_sha256: str,
        now: datetime,
    ) -> tuple[QueuedWorkItem, ...]:
        """Close abandoned work only after the exact Task was durably terminated.

        Cancellation is not a Worker execution or a completion verdict. No claim,
        Assignment, successor Run or accepted Artifact is created. Existing closed
        work and immutable retry/wait history retain their original facts.
        """
        self._require_aware(now, "cancellation clock")
        digest = _CANCELLATION_DIGEST.validate_python(cancellation_sha256)
        if task.status not in _TERMINAL_TASK_STATUSES:
            raise QueueConflict("取消队列前必须先将任务按审计事件结束")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self._lock_authority(cursor)
            cursor.execute(
                "SELECT id,status,payload_json FROM tasks WHERE id=%s FOR UPDATE", (task.id,)
            )
            task_row = cursor.fetchone()
            if task_row is None:
                raise QueueNotFound("取消队列的任务不存在")
            current_task = self._decode_model(task_row, "payload_json", Task)
            if task_row["id"] != current_task.id or task_row["status"] != current_task.status.value:
                raise QueueCorruption("取消队列的任务索引与正文不一致")
            if current_task.to_wire() != task.to_wire():
                raise QueueConflict("取消队列的任务快照已变化")
            if now < task.updated_at:
                raise QueueConflict("取消队列的时间早于任务结束时间")
            items = self.verify_cancelled_inventory(
                cursor, task, expected_items, cancellation_sha256=digest, now=now
            )
            # A stale event timestamp must not conceal a currently valid lease,
            # and a caller-supplied future timestamp cannot skip a live owner.
            live_now = self._clock()
            self._require_aware(live_now, "cancellation authority clock")
            expired_claims = self._require_cancelled_task_idle(
                cursor, task.id, now=min(now, live_now)
            )
            item_by_id = {item.id: item for item in items}
            for row in expired_claims:
                claim_item = item_by_id.get(self._text(row, "work_item_id"))
                assignment = self._decode_model(row, "assignment_json", RoleAssignment)
                if claim_item is None or assignment.repository_id != claim_item.repository_id:
                    raise QueueCorruption("取消队列的租约与仓库工作项不一致")
            for row in expired_claims:
                self._release_claim(
                    cursor, self._text(row, "lease_id"), state="EXPIRED", ended_at=now
                )
            closed_items = []
            for item in items:
                if item.status is WorkItemStatus.CLOSED:
                    closed_items.append(item)
                    continue
                closed = item.model_copy(
                    update={
                        "status": WorkItemStatus.CLOSED,
                        "wait_reason": None,
                        "wait_disposition": None,
                        "available_at": None,
                        "updated_at": now,
                    }
                )
                self._update_item(cursor, closed)
                self._append_event(
                    cursor,
                    closed,
                    from_status=item.status,
                    event_type="REQUIREMENT_CANCELLED",
                    lease_id=None,
                    occurred_at=now,
                    detail={
                        "cancellation_sha256": digest,
                        "task_sha256": record_digest(task),
                        "previous_work_item": item.to_wire(),
                        "expired_lease_ids": [
                            self._text(row, "lease_id")
                            for row in expired_claims
                            if row["work_item_id"] == item.id
                        ],
                    },
                )
                closed_items.append(closed)
            return tuple(closed_items)

    def verify_cancelled_inventory(
        self,
        cursor: DictCursor,
        task: Task,
        expected_items: tuple[QueuedWorkItem, ...],
        *,
        cancellation_sha256: str,
        now: datetime,
    ) -> tuple[QueuedWorkItem, ...]:
        """Fence the receipt's exact queue inventory, including partial replay.

        This shares the caller's SQL transaction. The deletion application uses
        it in the Task mutation fence as well as the queue close transaction, so
        an unclaimed scheduling change cannot expand the sealed cancellation.
        """
        self._require_aware(now, "cancellation inventory clock")
        digest = _CANCELLATION_DIGEST.validate_python(cancellation_sha256)
        self._lock_authority(cursor)
        expected = {item.id: item for item in expected_items}
        if len(expected) != len(expected_items) or any(
            item.task_id != task.id or item.repository_scopes != (task.repository,)
            for item in expected_items
        ):
            raise QueueConflict("删除凭据的队列范围与任务不一致")
        cursor.execute(
            "SELECT id,task_id,repository_id,status,payload_json FROM work_queue_items "
            "WHERE task_id=%s ORDER BY checkpoint_sequence,attempt,id FOR UPDATE",
            (task.id,),
        )
        items = tuple(self._cancellation_item(row, task) for row in cursor.fetchall())
        if {item.id for item in items} != set(expected):
            raise QueueConflict("删除凭据封存后的队列范围已变化")
        repository_ids = {item.repository_id for item in items}
        if len(repository_ids) > 1:
            raise QueueCorruption("取消队列的任务跨越了不同仓库")
        cursor.execute(
            "SELECT id,task_id,payload_json,sha256 FROM work_queue_admissions "
            "WHERE id=%s FOR UPDATE",
            (task.id,),
        )
        admission_row = cursor.fetchone()
        if admission_row is not None:
            admission = _decode(admission_row, RoleQueueAdmission)
            if any(item.repository_id != admission.repository_id for item in items):
                raise QueueCorruption("取消队列的仓库与原始派发不一致")
        for item in items:
            original = expected[item.id]
            if now < item.updated_at:
                raise QueueConflict("取消队列的时间早于最近的调度事实")
            replay = self._check_cancellation_replay(cursor, item, digest)
            if item == original:
                continue
            closed = original.model_copy(
                update={
                    "status": WorkItemStatus.CLOSED,
                    "wait_reason": None,
                    "wait_disposition": None,
                    "available_at": None,
                    "updated_at": now,
                }
            )
            if original.status is WorkItemStatus.CLOSED or item != closed or not replay:
                raise QueueConflict("删除凭据封存后的队列事实已变化")
        return items

    def _require_cancelled_task_idle(
        self, cursor: DictCursor, task_id: str, *, now: datetime
    ) -> tuple[Mapping[str, object], ...]:
        self._require_aware(now, "cancellation authority clock")
        cursor.execute(
            "SELECT lease_id,work_item_id,task_id,assignment_json,lease_json,expires_at "
            "FROM work_queue_claims WHERE state='ACTIVE' AND "
            "(task_id=%s OR work_item_id IN "
            "(SELECT id FROM work_queue_items WHERE task_id=%s)) "
            "ORDER BY lease_id FOR UPDATE",
            (task_id, task_id),
        )
        rows = tuple(cursor.fetchall())
        for row in rows:
            lease = self._decode_model(row, "lease_json", TaskLease)
            assignment = self._decode_model(row, "assignment_json", RoleAssignment)
            if (
                row["task_id"] != task_id
                or lease.task_id != task_id
                or assignment.task_id != task_id
                or row["lease_id"] != lease.id
                or assignment.lease_id != lease.id
                or lease.assignment_id != assignment.id
                or lease.agent_id != assignment.agent_id
                or self._parse_time(self._text(row, "expires_at")) != lease.expires_at
            ):
                raise QueueCorruption("取消任务的租约身份或时限不一致")
            if lease.expires_at > now:
                raise QueueConflict("任务仍有有效执行租约, 不能删除需求")
        if any(
            lease.task_id == task_id and lease.expires_at > now
            for lease in self._external_facts(cursor, now).leases
        ):
            raise QueueConflict("任务仍有有效执行租约, 不能删除需求")
        return rows

    def _cancellation_item(self, row: Mapping[str, object], task: Task) -> QueuedWorkItem:
        item = self._decode_item(row)
        if (
            row["task_id"] != item.task_id
            or item.task_id != task.id
            or row["repository_id"] != item.repository_id
            or row["status"] != item.status.value
            or item.repository_scopes != (task.repository,)
        ):
            raise QueueCorruption("取消队列的工作项与任务仓库不一致")
        return item

    def _check_cancellation_replay(
        self, cursor: DictCursor, item: QueuedWorkItem, digest: str
    ) -> bool:
        cursor.execute(
            "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
            "AND event_type='REQUIREMENT_CANCELLED' ORDER BY sequence DESC LIMIT 1 FOR UPDATE",
            (item.id,),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        try:
            payload: object = json.loads(self._text(row, "payload_json"))
            if not isinstance(payload, dict) or not isinstance(payload.get("detail"), dict):
                raise ValueError("invalid cancellation event")
            detail = payload["detail"]
            saved_digest = _CANCELLATION_DIGEST.validate_python(detail["cancellation_sha256"])
            saved_item = QueuedWorkItem.model_validate(payload["work_item"])
        except (KeyError, ValueError, TypeError, ValidationError) as error:
            raise QueueCorruption("需求取消事件正文损坏") from error
        if saved_item != item or item.status is not WorkItemStatus.CLOSED:
            raise QueueCorruption("需求取消事件与当前队列事实不一致")
        if saved_digest != digest:
            raise QueueConflict("已取消工作项绑定了另一份删除凭据")
        return True

    def _find[T: DomainModel](self, table: str, key: str, model: type[T]) -> T | None:
        if table not in _TABLES:
            raise ValueError("unknown queue record table")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                f"SELECT id,task_id,payload_json,sha256 FROM {table} WHERE id=%s", (key,)
            )
            row = cursor.fetchone()
            return _decode(row, model) if row is not None else None

    def assert_owner(
        self, cursor: DictCursor, claim: QueueClaim, token: str, *, now: datetime
    ) -> None:
        self._lock_authority(cursor)
        current = self._get_locked(cursor, claim.work_item.id, lock=True)
        if current.dispatch_sequence != claim.work_item.dispatch_sequence:
            raise QueueLeaseLost("Worker generation changed")
        self._require_active_claim(cursor, current.id, claim.lease.id, token, now=now)

    @contextmanager
    def fence(self, claim: QueueClaim, token: str) -> Iterator[DictCursor]:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self.assert_owner(cursor, claim, token, now=datetime.now(UTC))
            yield cursor
            self._require_active_claim(
                cursor, claim.work_item.id, claim.lease.id, token, now=datetime.now(UTC)
            )

    def accept_artifact(
        self, claim: QueueClaim, token: str, store: ArtifactStore, artifact: Artifact
    ) -> ArtifactRef:
        if (
            artifact.task_id != claim.work_item.task_id
            or artifact.producer.role is not claim.work_item.role
            or artifact.producer.agent_id != claim.assignment.agent_id
        ):
            raise QueueConflict("Artifact does not belong to claimed role")
        with self.fence(claim, token) as cursor:
            reference = store.put(artifact)
            persisted = store.get(reference.artifact_id)
            if persisted != artifact:
                raise QueueCorruption("Artifact readback changed")
            accepted = AcceptedRoleArtifact(
                task_id=artifact.task_id,
                work_item_id=claim.work_item.id,
                lease_id=claim.lease.id,
                dispatch_sequence=claim.work_item.dispatch_sequence,
                checkpoint_sequence=claim.work_item.checkpoint_sequence,
                run_id=artifact.producer.run_id,
                context_manifest_id=artifact.context_manifest_id,
                source_revision=artifact.source_revision,
                receipt=QueueArtifactReceipt(
                    artifact_id=reference.artifact_id, sha256=reference.sha256
                ),
            )
            _put(
                cursor,
                "work_queue_accepted_artifacts",
                reference.artifact_id,
                artifact.task_id,
                accepted,
            )
            return reference

    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
                "WHERE task_id=%s ORDER BY id",
                (task_id,),
            )
            return tuple(_decode(row, AcceptedRoleArtifact) for row in cursor.fetchall())

    def finish(
        self,
        claim: QueueClaim,
        token: str,
        *,
        next_step: QueuedRoleStep | None,
        now: datetime,
        guard: Callable[[], None] | None = None,
    ) -> QueueCompletion:
        self._require_aware(now, "completion clock")
        receipts = tuple(
            item.receipt
            for item in self.accepted(claim.work_item.task_id)
            if item.work_item_id == claim.work_item.id
        )
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self._lock_authority(cursor)
            current = self._get_locked(cursor, claim.work_item.id, lock=True)
            expires_at = None
            if current.status is not WorkItemStatus.CLOSED:
                if guard is not None:
                    guard()
                if current.dispatch_sequence != claim.work_item.dispatch_sequence:
                    raise QueueLeaseLost("Worker generation changed")
                active = self._require_active_claim(
                    cursor, current.id, claim.lease.id, token, now=self._clock()
                )
                expires_at = self._parse_time(self._text(active, "expires_at"))
            if next_step is not None:
                _put(
                    cursor,
                    "work_queue_steps",
                    next_step.work_item.id,
                    claim.work_item.task_id,
                    next_step,
                )
            result = self._complete_locked(
                cursor,
                claim.work_item.id,
                lease_id=claim.lease.id,
                owner_token=token,
                receipts=receipts,
                next_work_item=next_step.work_item if next_step else None,
                now=now,
            )
            # 'now' is the deterministic event/next-step timestamp, not proof
            # that the lease survived SQL lock waits. The authority lock prevents
            # renewal/reclaim here, so check the locked lease's expiry again before
            # commit; rejection rolls back completion and successor publication.
            if expires_at is not None:
                if guard is not None:
                    guard()
                if self._clock() >= expires_at:
                    raise QueueLeaseLost("Lease expired during queue completion")
            return result


def _put(cursor: DictCursor, table: str, key: str, task_id: str, record: DomainModel) -> None:
    cursor.execute(
        f"SELECT id,task_id,payload_json,sha256 FROM {table} WHERE id=%s FOR UPDATE", (key,)
    )
    existing = cursor.fetchone()
    if existing is not None:
        if _decode(existing, type(record)) != record:
            raise QueueConflict("immutable queue record changed")
        return
    cursor.execute(
        f"INSERT INTO {table}(id,task_id,payload_json,sha256) VALUES (%s,%s,%s,%s)",
        (
            key,
            task_id,
            json.dumps(record.to_wire(), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            record_digest(record),
        ),
    )


def _decode[T: DomainModel](row: dict[str, object], model: type[T]) -> T:
    from ai_software_engineer.work_queue.baseline import (
        BaselineQueueConsumption,
        BaselineQueueRelease,
    )

    payload = row["payload_json"]
    if not isinstance(payload, str):
        raise QueueCorruption("queue record payload is not text")
    try:
        record = model.model_validate_json(payload)
    except ValidationError as error:
        raise QueueCorruption("invalid queue record contract") from error
    if isinstance(record, RoleQueueAdmission):
        key, task_id = record.task_id, record.task_id
    elif isinstance(record, QueuedRoleStep):
        key, task_id = record.work_item.id, record.boundary.task_id
    elif isinstance(record, AcceptedRoleArtifact):
        key, task_id = record.receipt.artifact_id, record.task_id
    elif isinstance(record, BaselineQueueConsumption):
        key, task_id = record.binding.binding_sha256, record.task_id
    elif isinstance(record, BaselineQueueRelease):
        key, task_id = record.authorization.authorization_sha256, record.task_id
    else:
        raise QueueCorruption("unknown queue record model")
    if row["id"] != key or row["task_id"] != task_id:
        raise QueueCorruption("queue record indexed identity mismatch")
    if record_digest(record) != row["sha256"]:
        raise QueueCorruption("queue record digest mismatch")
    return record
