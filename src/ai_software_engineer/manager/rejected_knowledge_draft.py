"""Current complete draft proposed for exact human engineering acceptance.

This record is a present observation, never a reconstruction of the historical
post-progress inventory. Its consumer needs a separate exact engineering decision.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, JsonValue, StrictInt, TypeAdapter, model_validator

from ai_software_engineer.agents.models import AgentRequest, AgentRunStatus
from ai_software_engineer.artifacts import ArtifactStore, artifact_digest
from ai_software_engineer.artifacts.ordering import latest_accepted_artifact
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.artifact import CoderProgressArtifact, ImplementationReportArtifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import RejectedKnowledgePreparationEvidence
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.execution_baseline import CoderExecutionInput
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import Task, TaskId, task_matches_dispatch
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import WorkspaceMutationInventory, capture_mutation_inventory
from ai_software_engineer.git.policy import is_protected_rule_path
from ai_software_engineer.knowledge.assessment_rejection import RejectedKnowledgeAssessment
from ai_software_engineer.knowledge.models import Digest, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.work_queue.claim_snapshot import require_claim_snapshot
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem, WorkItemId


class CurrentDraftQueue(Protocol):
    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]: ...
    def original_claim(self, lease_id: str) -> QueueClaim: ...
    def step_for_invocation(
        self, work_item_id: str, baseline_sha256: str | None
    ) -> QueuedRoleStep: ...


class RejectedKnowledgeCurrentDraft(DomainModel):
    kind: Literal["rejected_knowledge_current_draft"] = "rejected_knowledge_current_draft"
    schema_version: Literal["v1"] = "v1"
    scope: EngineeringScope
    task_id: TaskId
    task_intent_sha256: Digest
    task_snapshot_sha256: Digest
    work_item_id: WorkItemId
    checkpoint_sequence: Annotated[StrictInt, Field(ge=0)]
    observation_sha256: Digest
    progress: CoderProgressArtifact
    publication: AcceptedRoleArtifact
    start: DeliveryInvocationStart
    outcome: DeliveryInvocationOutcome
    capture_start: ExecutionCaptureStart
    capture_stop: ExecutionCaptureStop
    context_sha256: Digest
    permissions: AgentPermissions
    capture: CapturedMutations
    inventory: WorkspaceMutationInventory
    record_sha256: Digest

    @model_validator(mode="after")
    def require_exact_relations(self) -> Self:
        start, outcome, captured, stopped = (
            self.start,
            self.outcome,
            self.capture_start,
            self.capture_stop,
        )
        for value in (start, outcome, captured, stopped):
            value.validate_integrity()
        progress, publication, request = self.progress, self.publication, start.request
        draft = outcome.result.artifact
        if (
            not progress.integrity.validated
            or progress.integrity.validated_at is None
            or artifact_digest(progress) != progress.integrity.sha256
            or not isinstance(draft, CoderProgressArtifact)
            or artifact_digest(draft) != progress.integrity.sha256
            or outcome.start != start
            or outcome.result.status is not AgentRunStatus.SUCCEEDED
            or request.role is not AgentRole.CODER
            or captured.request != request
            or (captured.claim.work_item.id, captured.claim.lease.id)
            != (start.work_item_id, start.lease_id)
            or captured.task_intent_sha256 != self.task_intent_sha256
            or captured.task_revision != start.checkpoint_sequence
            or stopped.capture_start_sha256 != captured.start_sha256
            or stopped.task_id != self.task_id
            or stopped.run_id != request.run_id
            or stopped.process_stop.kind != "completed"
            or stopped.process_stop.returncode != 0
            or stopped.process_stop.session_proof is None
            or not stopped.output_present
            or stopped.cause is not None
            or stopped.original_error_code is not None
            or stopped.execution_abort_reason is not None
            or not (
                captured.started_at
                <= stopped.process_stop.stopped_at
                <= progress.integrity.validated_at
            )
            or progress.producer.role is not AgentRole.CODER
            or progress.producer.agent_id != captured.claim.assignment.agent_id
            or progress.producer.run_id != request.run_id
            or progress.context_manifest_id != request.context_manifest_id
            or progress.source_revision != request.source_revision
            or progress.content.checkpoint_sequence != request.attempt
            or request.permissions != self.permissions
            or self.permissions.can_change_state
            or self.permissions.can_merge
            or captured.claim.work_item.checkpoint_sequence != start.checkpoint_sequence
            or captured.claim.work_item.attempt != request.attempt
            or self.capture.base_revision not in {None, progress.source_revision}
            or (
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
            != (
                self.task_id,
                start.work_item_id,
                start.lease_id,
                captured.claim.work_item.dispatch_sequence,
                start.checkpoint_sequence,
                request.run_id,
                request.context_manifest_id,
                progress.source_revision,
                progress.artifact_id,
                progress.integrity.sha256,
            )
            or self.capture.task_id != self.task_id
            or self.capture.source_revision != progress.source_revision
            or self.capture.worktree_path != captured.worktree_path
            or self.capture.index_diff_sha256 != hashlib.sha256(b"").hexdigest()
            or self.capture.to_capture().changed_paths
            != tuple(sorted(value.path for value in progress.content.changed_files))
            or self.scope.repository_id != captured.scope.repository_id
            or self.scope.team_id != captured.scope.team_id
            or self.scope.project_id != captured.scope.project_id
            or self.scope.repository_root not in captured.claim.work_item.repository_scopes
            or self.task_id != request.task_id
            or progress.task_id != self.task_id
            or self.work_item_id == start.work_item_id
            or self.checkpoint_sequence <= start.checkpoint_sequence
        ):
            raise ValueError("current knowledge draft changed its exact accepted progress lineage")
        observed = {value.path: value for value in self.inventory.files}
        if tuple(observed) != tuple(sorted(observed)) or len(observed) != len(self.inventory.files):
            raise ValueError("current draft inventory paths must be sorted and unique")
        for observed_file in self.inventory.files:
            path = observed_file.path
            # Complete observations include the manager-owned .git identity;
            # mutation write policy remains independently stricter below.
            if (
                not path
                or path == "."
                or path.startswith("/")
                or "\\" in path
                or PurePosixPath(path).as_posix() != path
                or ".." in PurePosixPath(path).parts
                or any(ord(character) < 32 for character in path)
            ):
                raise ValueError("current draft inventory contains a noncanonical observed path")
            TypeAdapter(Digest).validate_python(observed_file.sha256)
            if not 0 <= observed_file.mode <= 0o7777 or observed_file.size < 0:
                raise ValueError("current draft inventory has invalid file metadata")
        for mutation in self.capture.mutations:
            if (
                is_protected_rule_path(mutation.path)
                or not any(fnmatchcase(mutation.path, path) for path in self.permissions.read_paths)
                or not any(
                    fnmatchcase(mutation.path, path) for path in self.permissions.write_paths
                )
            ):
                raise ValueError("current draft mutation exceeds the exact Coder permissions")
            actual = observed.get(mutation.path)
            if mutation.after is None:
                if actual is not None:
                    raise ValueError("current draft deletion is present in complete inventory")
            elif actual is None or (actual.kind, actual.sha256, actual.mode, actual.size) != (
                "file",
                mutation.after.sha256,
                mutation.after.mode,
                mutation.after.size,
            ):
                raise ValueError("current draft body differs from complete observed inventory")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "record_sha256": "0" * 64})
        return value.model_copy(update={"record_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"record_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.record_sha256 != self.recompute_sha256():
            raise ValueError("current rejected knowledge draft digest mismatch")


def read_current_draft(state: Path, identity: str) -> RejectedKnowledgeCurrentDraft:
    record = KnowledgeRecordStore(state / "rejected-knowledge", read_only=True).get(
        "current-drafts", identity, RejectedKnowledgeCurrentDraft
    )
    record.validate_integrity()
    if record.record_sha256 != identity:
        raise ValueError("current knowledge draft filename identity mismatch")
    return record


def _accepted_progress(
    task: Task,
    queue: CurrentDraftQueue,
    artifacts: ArtifactStore,
    source: CoderExecutionInput,
) -> tuple[CoderProgressArtifact, AcceptedRoleArtifact]:
    publications = queue.accepted(task.id)
    by_id = {value.receipt.artifact_id: value for value in publications}
    if len(by_id) != len(publications):
        raise ValueError("accepted progress publication identities are not unique")
    accepted = tuple(artifacts.get(identity) for identity in by_id)
    for artifact in accepted:
        if (
            artifact.task_id != task.id
            or artifact.integrity.sha256 != by_id[artifact.artifact_id].receipt.sha256
            or artifact_digest(artifact) != artifact.integrity.sha256
        ):
            raise ValueError("current draft accepted artifacts changed their real publication")
    if latest_accepted_artifact(accepted, ImplementationReportArtifact) is not None:
        raise ValueError(
            "current knowledge draft acceptance cannot supersede an accepted candidate"
        )
    progress = latest_accepted_artifact(
        accepted,
        CoderProgressArtifact,
        excluded_artifact_ids=source.superseded_artifact_ids,
    )
    if progress is None:
        raise ValueError("current knowledge draft requires a real latest accepted progress")
    return progress, by_id[progress.artifact_id]


def collect_current_draft(
    *,
    state: Path,
    task: Task,
    item: QueuedWorkItem,
    observation: RejectedKnowledgeAssessment,
    scope: EngineeringScope,
    queue: CurrentDraftQueue,
    artifacts: ArtifactStore,
    git: GitWorktreeManager,
    permissions: AgentPermissions,
    capture: CapturedMutations,
    inventory: WorkspaceMutationInventory,
    source: CoderExecutionInput,
) -> RejectedKnowledgeCurrentDraft:
    progress, publication = _accepted_progress(task, queue, artifacts, source)
    invocations = KnowledgeRecordStore(state / "invocations", read_only=True)
    start = invocations.get("invocation-starts", publication.work_item_id, DeliveryInvocationStart)
    outcome = invocations.get(
        "invocation-outcomes", publication.work_item_id, DeliveryInvocationOutcome
    )
    native = FileContinuationStore(state / "continuations" / task.id, task_id=task.id)
    captured, stopped = (
        native.capture_start(start.request.run_id),
        native.capture_stop(start.request.run_id),
    )
    require_claim_snapshot(captured.claim, queue.original_claim(publication.lease_id))
    context = FileContextStore(state.parent / "contexts", read_only=True).get(
        progress.context_manifest_id
    )
    tasks = tuple(section for section in context.sections if section.name == "task")
    policies = tuple(section for section in context.sections if section.name == "policy")
    claimed = tuple(
        section for section in context.sections if section.name == "source:execution.claim"
    )
    if any(len(values) != 1 or values[0].truncated for values in (tasks, policies, claimed)):
        raise ValueError("current draft progress lacks complete original Task/policy/claim context")
    original_task = Task.model_validate_json(tasks[0].content)
    policy = TypeAdapter(dict[str, JsonValue]).validate_json(policies[0].content)
    denied = policy.pop("denied_paths", None)
    original_claim = queue.original_claim(publication.lease_id)
    claim_wire = TypeAdapter(dict[str, JsonValue]).validate_json(claimed[0].content)
    step = queue.step_for_invocation(
        publication.work_item_id, start.request.execution_baseline_sha256
    )
    sealed_at = progress.integrity.validated_at
    if sealed_at is None:
        raise ValueError("current draft progress has no real platform seal time")
    if (
        not task_matches_dispatch(original_task, task)
        or original_task.status is not TaskStatus.IMPLEMENTING
        or original_task.attempts != start.request.attempt
        or start.request.attempt >= item.attempt
        or not (
            stopped.process_stop.stopped_at <= sealed_at < observation.original_claim.claimed_at
        )
        or original_claim.claimed_at > start.started_at
        or start.started_at > captured.started_at
        or context.task_id != task.id
        or context.role is not AgentRole.CODER
        or context.attempt != start.request.attempt
        or context.source_revision != source.source_revision
        or progress.source_revision != source.source_revision
        or step.boundary.source_revision != source.source_revision
        or step.allocation_sha256 != captured.scope.dispatch_sha256
        or step.work_item.id != publication.work_item_id
        or step.boundary.checkpoint_sequence != start.checkpoint_sequence
        or AgentPermissions.model_validate(policy) != permissions
        or denied != list(task.constraints.denied_paths if task.constraints else ())
        or claimed[0].uri != "claim://" + original_claim.lease.id
        or any(
            claim_wire.get(field) != value
            for field, value in {
                "task_id": task.id,
                "work_item_id": publication.work_item_id,
                "lease_id": original_claim.lease.id,
                "assignment_id": original_claim.assignment.id,
                "dispatch_sequence": original_claim.work_item.dispatch_sequence,
                "role": AgentRole.CODER.value,
                "attempt": original_claim.work_item.attempt,
                "checkpoint_sequence": original_claim.work_item.checkpoint_sequence,
            }.items()
        )
    ):
        raise ValueError("current knowledge draft changed its original frozen execution input")
    NativeCoderContinuation._require_stopped(stopped.process_stop, start.request)
    worktree = git.recover(
        WorktreeSpec(
            task_id=task.id, role=AgentRole.CODER, attempt=1, source_revision=source.source_revision
        )
    )
    if (
        worktree.path != Path(capture.worktree_path)
        or capture_mutation_inventory(worktree.path) != inventory
    ):
        raise ValueError("current knowledge draft changed while observed")
    return RejectedKnowledgeCurrentDraft.create(
        scope=scope,
        task_id=task.id,
        task_intent_sha256=task_intent_sha256(task),
        task_snapshot_sha256=digest(task.to_wire()),
        work_item_id=item.id,
        checkpoint_sequence=item.checkpoint_sequence,
        observation_sha256=observation.observation_sha256,
        progress=progress,
        publication=publication,
        start=start,
        outcome=outcome,
        capture_start=captured,
        capture_stop=stopped,
        context_sha256=digest(context.to_wire()),
        permissions=permissions,
        capture=capture,
        inventory=inventory,
    )


class RejectedKnowledgeDraftAdmission:
    """Reopen the consumed exact human decision before the successor provider starts."""

    def __init__(
        self,
        *,
        state: Path,
        git: GitWorktreeManager,
        task_reader: Callable[[], Task],
        claim_reader: Callable[[], QueueClaim],
        retry_reader: Callable[[str], RejectedKnowledgePreparationEvidence | None],
    ) -> None:
        self.state, self.git, self.task_reader = state, git, task_reader
        self.claim_reader, self.retry_reader = claim_reader, retry_reader

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None:
        claim, task = self.claim_reader(), self.task_reader()
        evidence = self.retry_reader(claim.work_item.id)
        if evidence is None or evidence.current_draft_sha256 is None:
            raise ContinuationRejected("current retained draft has no exact consumed decision")
        record = read_current_draft(self.state, evidence.current_draft_sha256)
        if (
            request.role is not AgentRole.CODER
            or request.task_id != task.id
            or task.id != record.task_id
            or task.status is not TaskStatus.IMPLEMENTING
            or task_intent_sha256(task) != record.task_intent_sha256
            or task.attempts != claim.work_item.attempt
            or request.attempt != claim.work_item.attempt
            or claim.work_item.attempt != evidence.original_attempt + 1
            or claim.work_item.parent_work_item_id != evidence.work_item_id
            or claim.work_item.task_id != task.id
            or claim.work_item.role is not AgentRole.CODER
            or claim.work_item.repository_id != record.scope.repository_id
            or claim.work_item.checkpoint_sequence != record.checkpoint_sequence
            or task.repository != record.scope.repository_root
            or request.source_revision != record.progress.source_revision
            or request.permissions != record.permissions
            or request.continuation_checkpoint_id != record.progress.artifact_id
            or record.progress.artifact_id not in request.input_artifact_ids
            or request.continuation_changed_paths
            != tuple(sorted(value.path for value in record.progress.content.changed_files))
            or request.run_id == evidence.previous_run_id
            or request.context_manifest_id == evidence.previous_context_manifest_id
            or claim.lease.id == evidence.current_lease_id
            or str(workspace_root) != record.capture.worktree_path
            or record.task_id != evidence.task_id
            or record.scope != evidence.scope
            or record.work_item_id != evidence.work_item_id
            or record.checkpoint_sequence != evidence.checkpoint_sequence
            or record.progress.source_revision != evidence.source_revision
            or request.run_id == record.start.request.run_id
            or request.context_manifest_id == record.progress.context_manifest_id
            or record.observation_sha256 != evidence.observation_sha256
            or record.inventory.sha256 != evidence.workspace_inventory_sha256
            or digest(record.capture.to_wire()) != evidence.workspace_capture_sha256
        ):
            raise ContinuationRejected("current draft is not bound to the new real claimed input")
        worktree = self.git.recover(
            WorktreeSpec(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=request.source_revision,
            )
        )
        if (
            worktree.path != workspace_root
            or capture_mutation_inventory(workspace_root) != record.inventory
        ):
            raise ContinuationRejected("approved current draft bytes or full inventory changed")
        current = self.git.capture_mutations(
            worktree,
            request.permissions,
            denied_paths=task.constraints.denied_paths if task.constraints else (),
            base_revision=record.capture.base_revision,
            include_ignored=True,
        )
        if CapturedMutations.from_capture(current) != record.capture:
            raise ContinuationRejected(
                "approved current draft source, index, modes or bodies changed"
            )
        NativeCoderContinuation._require_stopped(
            record.capture_stop.process_stop, record.start.request
        )
        if self.claim_reader() != claim or self.retry_reader(claim.work_item.id) != evidence:
            raise ContinuationRejected("current draft authority changed during provider admission")
