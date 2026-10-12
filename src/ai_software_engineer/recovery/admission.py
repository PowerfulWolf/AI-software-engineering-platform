"""Claimed Task-scoped main history; preparation counters are not invocation facts."""

from collections.abc import Callable
from functools import wraps

from ai_software_engineer.agents import AgentRequest, AgentRunStatus
from ai_software_engineer.agents.continuation import ContinuationExecutionUncertain
from ai_software_engineer.agents.execution import current_execution_guard
from ai_software_engineer.agents.workspace_admission import WorkspaceAdmissionRejected
from ai_software_engineer.artifacts import ArtifactStore, artifact_digest
from ai_software_engineer.artifacts.store import ArtifactStoreError
from ai_software_engineer.context.ports import ContextError
from ai_software_engineer.domain import AgentPermissions, AgentRole
from ai_software_engineer.domain.artifact import CoderProgressArtifact, ImplementationReportArtifact
from ai_software_engineer.git import GitWorkspaceError, WorkspacePolicyError
from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.ports import DeliveryQueuePending, QueueError
from ai_software_engineer.work_queue.worker import AcceptedArtifactStore, WorkerExecutionGuard


class RecoveryWorkspaceAdmissionRejected(RecoveryRejected, WorkspaceAdmissionRejected):
    """Preserve the recovery domain error while exposing a provider precondition."""


def reject_invalid_admission[**P, R](method: Callable[P, R]) -> Callable[P, R]:
    """Convert trusted gate rejections without swallowing ownership/wait decisions."""

    @wraps(method)
    def checked(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return method(*args, **kwargs)
        except (
            ContinuationExecutionUncertain,
            DeliveryQueuePending,
            KnowledgeGapRaised,
            RecoveryWorkspaceAdmissionRejected,
        ):
            raise
        except (
            RecoveryRejected,
            KnowledgeError,
            ContextError,
            ArtifactStoreError,
            GitWorkspaceError,
            WorkspacePolicyError,
            QueueError,
            OSError,
            ValueError,
        ) as error:
            raise RecoveryWorkspaceAdmissionRejected(str(error)) from error

    return checked


class ClaimedRecoveryInvocationHistory:
    def __init__(
        self,
        *,
        dispatch: RecoveryDispatchRecord,
        permissions: AgentPermissions,
        invocations: KnowledgeRecordStore,
        artifacts: ArtifactStore,
        guard: WorkerExecutionGuard | None = None,
    ) -> None:
        self.dispatch, self.permissions = dispatch, permissions
        self.invocations, self.artifacts, self.guard = invocations, artifacts, guard

    def prior_main_outcomes(self, request: AgentRequest) -> tuple[DeliveryInvocationOutcome, ...]:
        """Read this Task's queue index and exact invocation keys under its Worker lock."""
        guard = self.worker()
        guard.check()
        assert guard.lease is not None
        claim, queue = guard.lease.claim, guard.lease.queue
        current = claim.work_item
        if (
            request.role is not AgentRole.CODER
            or (request.task_id, request.role, request.attempt)
            != (current.task_id, current.role, current.attempt)
            or request.task_id != self.dispatch.task_id
            or current.repository_id != self.dispatch.repository_id
            or request.permissions != self.permissions
        ):
            raise RecoveryRejected("recovery seed request differs from the current claim")
        admission = queue.admission(request.task_id)
        if admission is None or (
            admission.task_id,
            admission.repository_id,
            admission.allocation_sha256,
        ) != (request.task_id, self.dispatch.repository_id, self.dispatch.dispatch_sha256):
            raise RecoveryRejected("recovery seed queue admission changed")
        outcomes: list[DeliveryInvocationOutcome] = []
        found_current = False
        for item in queue.items_for_task(request.task_id):
            if item.task_id != request.task_id or item.repository_id != current.repository_id:
                raise RecoveryRejected("recovery seed queue contains foreign work")
            if item.role is not AgentRole.CODER:
                continue
            start = self.invocations.find("invocation-starts", item.id, DeliveryInvocationStart)
            outcome = self.invocations.find(
                "invocation-outcomes", item.id, DeliveryInvocationOutcome
            )
            if start is None:
                if outcome is not None or item.id == current.id:
                    raise RecoveryRejected("recovery invocation start is missing")
                continue  # Knowledge-only preparation did not reach the main role boundary.
            start.validate_integrity()
            step = queue.step_for_invocation(item.id, start.request.execution_baseline_sha256)
            original = queue.original_claim(start.lease_id)
            if (
                (start.work_item_id, start.checkpoint_sequence)
                != (item.id, item.checkpoint_sequence)
                or (start.request.task_id, start.request.role, start.request.attempt)
                != (item.task_id, item.role, item.attempt)
                or step.allocation_sha256 != self.dispatch.dispatch_sha256
                or step.boundary.source_revision != start.request.source_revision
                or original.lease.id != start.lease_id
                or (
                    step.work_item.id,
                    step.boundary.task_id,
                    step.boundary.role,
                    step.boundary.attempt,
                    step.boundary.checkpoint_sequence,
                )
                != (item.id, item.task_id, item.role, item.attempt, item.checkpoint_sequence)
                or (
                    original.work_item.id,
                    original.work_item.task_id,
                    original.work_item.repository_id,
                    original.work_item.role,
                    original.work_item.attempt,
                    original.work_item.checkpoint_sequence,
                )
                != (
                    item.id,
                    item.task_id,
                    item.repository_id,
                    item.role,
                    item.attempt,
                    item.checkpoint_sequence,
                )
            ):
                raise RecoveryRejected("recovery invocation differs from its durable queue step")
            if item.id == current.id:
                if found_current or start.request != request or start.lease_id != claim.lease.id:
                    raise RecoveryRejected(
                        "recovery admission differs from the exact current start"
                    )
                if outcome is not None:
                    raise RecoveryRejected("completed recovery invocation must not call a provider")
                found_current = True
                continue
            if outcome is None:
                raise ContinuationExecutionUncertain(
                    "先前主执行已记录, 结果尚未封存; 保留现场, 禁止重复调用或重新消费恢复种子"
                )
            outcome.validate_integrity()
            if outcome.start != start:
                raise RecoveryRejected("recovery outcome changed its exact invocation start")
            outcomes.append(outcome)
        if not found_current:
            raise RecoveryRejected("current recovery invocation is outside the claimed Task queue")
        guard.check()
        return tuple(outcomes)

    def worker(self) -> WorkerExecutionGuard:
        guard = self.guard or current_execution_guard()
        if not isinstance(guard, WorkerExecutionGuard):
            raise RecoveryRejected("recovery seed admission has no bound Worker")
        return guard

    def has_accepted_input(
        self, request: AgentRequest, outcomes: tuple[DeliveryInvocationOutcome, ...]
    ) -> bool:
        """Legacy missing seed receipts are never backfilled from later accepted output."""
        guard = self.worker()
        assert guard.lease is not None
        queue = guard.lease.queue
        accepted = AcceptedArtifactStore(self.artifacts, queue, request.task_id, guard)
        receipts = queue.accepted(request.task_id)
        for outcome in outcomes:
            result, artifact = outcome.result, outcome.result.artifact
            if result.status is not AgentRunStatus.SUCCEEDED or not isinstance(
                artifact, CoderProgressArtifact | ImplementationReportArtifact
            ):
                continue
            if isinstance(artifact, CoderProgressArtifact):
                if request.continuation_checkpoint_id != artifact.artifact_id:
                    continue
            elif artifact.artifact_id not in request.input_artifact_ids:
                continue
            if artifact.source_revision != request.source_revision:
                continue
            original = queue.original_claim(outcome.start.lease_id)
            matching = tuple(
                publication
                for publication in receipts
                if publication.receipt.artifact_id == artifact.artifact_id
                and publication.task_id == request.task_id
                and publication.work_item_id == outcome.start.work_item_id
                and publication.lease_id == outcome.start.lease_id
                and publication.run_id == result.run_id
                and publication.context_manifest_id == result.context_manifest_id
                and publication.source_revision == artifact.source_revision
                and publication.checkpoint_sequence == outcome.start.checkpoint_sequence
                and publication.dispatch_sequence == original.work_item.dispatch_sequence
            )
            if len(matching) != 1:
                continue
            stored = accepted.get(artifact.artifact_id)
            if artifact_digest(stored) != artifact_digest(artifact):
                raise RecoveryRejected("accepted recovery input differs from its main outcome")
            return True
        return False
