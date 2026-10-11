"""Independent checkpoints for completed Coder progress rejected by an exact contract.

These records preserve a legal worktree; they never amend an old output, stop,
publication receipt or verdict, and never claim a timeout or provider failure.
"""

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator

from ai_software_engineer.agents.models import AgentRequest, AgentRunStatus
from ai_software_engineer.artifacts import artifact_digest
from ai_software_engineer.domain.artifact import CoderProgressArtifact
from ai_software_engineer.domain.coder_work import validate_coder_slice_output
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import RejectedCoderOutputEvidence
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, ArtifactKind, TaskStatus
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import (
    WorkspaceMutationInventory,
    capture_mutation_inventory,
    changed_mutation_paths,
    is_execution_cache_path,
)
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.preparation_retry import claim_identity_sha256
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep, record_digest
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.models import QueueClaim


def supported_rejected_progress(outcome: DeliveryInvocationOutcome) -> bool:
    """Only a machine-verifiable sequence mismatch is admitted by this capability."""
    artifact, request = outcome.result.artifact, outcome.start.request
    return (
        outcome.result.status is AgentRunStatus.SUCCEEDED
        and request.role is AgentRole.CODER
        and isinstance(artifact, CoderProgressArtifact)
        and artifact.content.checkpoint_sequence != request.attempt
    )


class RejectedCoderOutputCheckpoint(DomainModel):
    kind: Literal["rejected_coder_output_checkpoint"] = "rejected_coder_output_checkpoint"
    schema_version: Literal["v1"] = "v1"
    task_snapshot_sha256: StageSha256
    step_sha256: StageSha256
    outcome: DeliveryInvocationOutcome
    capture_start: ExecutionCaptureStart
    capture_stop: ExecutionCaptureStop
    capture: CapturedMutations
    inventory_after: WorkspaceMutationInventory
    checkpoint_sha256: StageSha256

    @model_validator(mode="after")
    def validate_exact_checkpoint(self) -> Self:
        outcome, start, stop = self.outcome, self.capture_start, self.capture_stop
        outcome.validate_integrity()
        start.validate_integrity()
        stop.validate_integrity()
        request, artifact = outcome.start.request, outcome.result.artifact
        if not supported_rejected_progress(outcome) or not isinstance(
            artifact, CoderProgressArtifact
        ):
            raise ValueError("checkpoint requires a supported rejected Coder progress output")
        if request.work_slice is not None:
            validate_coder_slice_output(request.work_slice, artifact)
        parents = request.expected_parent_artifact_ids
        if parents is None:
            parents = request.input_artifact_ids
        supersedes = (
            request.expected_supersedes_by_kind.get(ArtifactKind.CODER_PROGRESS)
            if request.expected_supersedes_by_kind is not None
            else request.continuation_checkpoint_id
        )
        if (
            start.request != request
            or start.claim.work_item.id != outcome.start.work_item_id
            or start.claim.work_item.checkpoint_sequence != start.task_revision
            or start.claim.lease.id != outcome.start.lease_id
            or start.task_revision != outcome.start.checkpoint_sequence
            or stop.capture_start_sha256 != start.start_sha256
            or stop.task_id != request.task_id
            or stop.run_id != request.run_id
            or stop.process_stop.kind != "completed"
            or stop.process_stop.returncode != 0
            or stop.process_stop.stopped_at < start.started_at
            or not stop.output_present
            or stop.cause is not None
            or stop.original_error_code is not None
            or artifact.parent_artifact_ids != parents
            or artifact.supersedes != supersedes
            or artifact.producer.agent_id != start.claim.assignment.agent_id
            or self.capture.task_id != request.task_id
            or self.capture.worktree_path != start.worktree_path
            or self.capture.source_revision != request.source_revision
            or self.capture.index_diff_sha256 != hashlib.sha256(b"").hexdigest()
            or self.capture.to_capture().changed_paths
            != tuple(sorted(item.path for item in artifact.content.changed_files))
        ):
            raise ValueError("rejected output checkpoint changed its exact original authority")
        observed = {item.path: item for item in self.inventory_after.files}
        for mutation in self.capture.mutations:
            actual = observed.get(mutation.path)
            if mutation.after is None:
                if actual is not None:
                    raise ValueError("deleted mutation is present in rejected output inventory")
            elif actual is None or (actual.kind, actual.sha256, actual.mode, actual.size) != (
                "file",
                mutation.after.sha256,
                mutation.after.mode,
                mutation.after.size,
            ):
                raise ValueError("rejected output mutation does not match its complete inventory")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"checkpoint_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.checkpoint_sha256 != self.recompute_sha256():
            raise ValueError("rejected output checkpoint digest mismatch")

    @property
    def evidence(self) -> RejectedCoderOutputEvidence:
        start, outcome = self.capture_start, self.outcome
        request, claim = start.request, start.claim
        artifact = outcome.result.artifact
        assert isinstance(artifact, CoderProgressArtifact)
        return RejectedCoderOutputEvidence(
            scope=EngineeringScope(
                team_id=start.scope.team_id,
                project_id=start.scope.project_id,
                repository_id=start.scope.repository_id,
                repository_root=claim.work_item.repository_scopes[0],
            ),
            requirement_id=start.scope.requirement_id,
            task_id=request.task_id,
            work_item_id=outcome.start.work_item_id,
            original_lease_id=outcome.start.lease_id,
            original_claim_sha256=claim_identity_sha256(claim),
            original_attempt=request.attempt,
            original_dispatch_sequence=claim.work_item.dispatch_sequence,
            checkpoint_sequence=outcome.start.checkpoint_sequence,
            previous_run_id=request.run_id,
            previous_context_manifest_id=request.context_manifest_id,
            source_revision=request.source_revision,
            invocation_start_sha256=outcome.start.start_sha256,
            invocation_outcome_sha256=outcome.outcome_sha256,
            rejected_artifact_id=artifact.artifact_id,
            rejected_artifact_sha256=artifact_digest(artifact),
            expected_sequence=request.attempt,
            reported_sequence=artifact.content.checkpoint_sequence,
            process_stop_sha256=self.capture_stop.process_stop.stop_sha256,
            capture_sha256=self.capture.capture_sha256,
            workspace_inventory_sha256=self.inventory_after.sha256,
            checkpoint_sha256=self.checkpoint_sha256,
        )


def read_rejected_checkpoint(
    state: Path, work_item_id: str
) -> RejectedCoderOutputCheckpoint | None:
    root = state / "rejected-coder-output"
    if not root.is_dir():
        return None
    record = KnowledgeRecordStore(root, read_only=True).find(
        "rejected-checkpoints", work_item_id, RejectedCoderOutputCheckpoint
    )
    if record is not None:
        record.validate_integrity()
        if record.outcome.start.work_item_id != work_item_id:
            raise ContinuationRejected("被拒产出的保留现场记录属于另一个工作项")
    return record


def capture_rejected_checkpoint(
    *,
    state: Path,
    task: Task,
    step: QueuedRoleStep,
    outcome: DeliveryInvocationOutcome,
    start: ExecutionCaptureStart,
    stop: ExecutionCaptureStop,
    git: GitWorktreeManager,
    validate_inputs: Callable[[], None],
) -> RejectedCoderOutputCheckpoint:
    """Caller owns an idle Task lock and validates the original real stop/claim."""
    if task.status is not TaskStatus.IMPLEMENTING or task.attempts != start.request.attempt:
        raise ContinuationRejected("被拒产出已经不属于当前开发 checkpoint")
    validate_inputs()
    existing = read_rejected_checkpoint(state, step.work_item.id)
    if existing is not None:
        if (
            existing.task_snapshot_sha256,
            existing.step_sha256,
            existing.outcome,
            existing.capture_start,
            existing.capture_stop,
        ) != (digest(task.to_wire()), record_digest(step), outcome, start, stop):
            raise ContinuationRejected("被拒产出的原执行或任务事实已变化")
        verify_rejected_workspace(existing, git, task)
        validate_inputs()
        return existing
    worktree = git.recover(
        WorktreeSpec(
            task_id=task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=start.request.source_revision,
        )
    )
    if str(worktree.path) != start.worktree_path or worktree.detached:
        raise ContinuationRejected("被拒产出的工作区身份已变化")
    denied = task.constraints.denied_paths if task.constraints else ()
    capture = CapturedMutations.from_capture(
        git.capture_mutations(worktree, start.request.permissions, denied_paths=denied)
    )
    record = RejectedCoderOutputCheckpoint(
        task_snapshot_sha256=digest(task.to_wire()),
        step_sha256=record_digest(step),
        outcome=outcome,
        capture_start=start,
        capture_stop=stop,
        capture=capture,
        inventory_after=capture_mutation_inventory(worktree.path),
        checkpoint_sha256="0" * 64,
    )
    record = record.model_copy(update={"checkpoint_sha256": record.recompute_sha256()})
    verify_rejected_workspace(record, git, task)
    validate_inputs()
    return KnowledgeRecordStore(state / "rejected-coder-output").put(
        "rejected-checkpoints", step.work_item.id, record
    )


def verify_rejected_workspace(
    record: RejectedCoderOutputCheckpoint, git: GitWorktreeManager, task: Task
) -> None:
    record.validate_integrity()
    request = record.capture_start.request
    if (
        task.id != request.task_id
        or task_intent_sha256(task) != record.capture_start.task_intent_sha256
    ):
        raise ContinuationRejected("被拒产出的现场不属于原冻结任务")
    NativeCoderContinuation._require_stopped(record.capture_stop.process_stop, request)
    denied = task.constraints.denied_paths if task.constraints else ()
    mutations = changed_mutation_paths(
        record.capture_start.inventory_before, record.inventory_after
    )
    NativeCoderContinuation._authorize_mutations(
        request, Path(record.capture.worktree_path), mutations, denied
    )
    noncache = {path for path in mutations if not is_execution_cache_path(path)}
    if not noncache.issubset(
        set(record.capture.to_capture().changed_paths) | set(request.continuation_changed_paths)
    ):
        raise ContinuationRejected("被拒产出的完整现场未覆盖全部非缓存变更")
    git.verify_mutations(record.capture.to_capture(), request.permissions, denied_paths=denied)
    if capture_mutation_inventory(Path(record.capture.worktree_path)) != record.inventory_after:
        raise ContinuationRejected("被拒产出的完整现场已变化, 不能开始新的开发执行")


class RejectedCoderOutputAdmission:
    """The next real claim may read the captured legal draft, never accept the report."""

    def __init__(
        self,
        *,
        state: Path,
        git: GitWorktreeManager,
        task_reader: Callable[[], Task],
        claim_reader: Callable[[], QueueClaim],
        retry_reader: Callable[[str], RejectedCoderOutputEvidence | None],
    ) -> None:
        (
            self.state,
            self.git,
            self.task_reader,
            self.claim_reader,
            self.retry_reader,
        ) = state, git, task_reader, claim_reader, retry_reader

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None:
        claim = self.claim_reader()
        evidence = self.retry_reader(claim.work_item.id)
        if request.role is not AgentRole.CODER or evidence is None:
            raise ContinuationRejected("被拒产出续跑缺少当前精确决定, 不能放行保留草稿")
        record = read_rejected_checkpoint(self.state, evidence.work_item_id)
        task = self.task_reader()
        if (
            record is None
            or record.evidence != evidence
            or (
                claim.work_item.parent_work_item_id != evidence.work_item_id
                or claim.work_item.task_id != request.task_id
                or claim.work_item.role is not AgentRole.CODER
                or claim.assignment.agent_id != record.capture_start.claim.assignment.agent_id
                or claim.work_item.repository_scopes
                != record.capture_start.claim.work_item.repository_scopes
                or claim.work_item.attempt != evidence.original_attempt + 1
                or task.attempts != claim.work_item.attempt
                or request.attempt != claim.work_item.attempt
                or request.task_id != task.id
                or request.task_id != evidence.task_id
                or request.source_revision != evidence.source_revision
                or request.permissions != record.capture_start.request.permissions
                or request.run_id == evidence.previous_run_id
                or request.context_manifest_id == evidence.previous_context_manifest_id
                or claim.lease.id == evidence.original_lease_id
                or str(workspace_root) != record.capture.worktree_path
                or claim.work_item.checkpoint_sequence != evidence.checkpoint_sequence
                or claim.work_item.repository_id != evidence.scope.repository_id
                or task.repository != evidence.scope.repository_root
            )
        ):
            raise ContinuationRejected("被拒产出续跑缺少当前真实领取与完整现场的精确授权")
        verify_rejected_workspace(record, self.git, task)
        if self.claim_reader() != claim or self.retry_reader(claim.work_item.id) != evidence:
            raise ContinuationRejected("核验保留草稿期间当前领取或精确决定已变化")
