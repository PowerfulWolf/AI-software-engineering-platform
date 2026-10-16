"""Exact no-main knowledge rejection and fresh-owner carry, never a model retry."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import AwareDatetime, JsonValue, TypeAdapter

from ai_software_engineer.agents.execution import current_execution_guard, execution_scope
from ai_software_engineer.agents.fallback import ModelRouteAttemptStoreError, model_route_root
from ai_software_engineer.artifacts import ArtifactStore, ArtifactStoreError
from ai_software_engineer.context import ContextStoreError, FileContextStore
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.delivery_resolution import RejectedKnowledgePreparationEvidence
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, TeamRole
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git import GitWorkspaceError, GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.assessment_rejection import (
    KnowledgeAssessmentRejected,
    RejectedKnowledgeAssessment,
    derive_rejected_assessment,
)
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationIntent,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
    invocation_scope_lane_sha256,
)
from ai_software_engineer.knowledge.models import (
    Digest,
    KnowledgeError,
    KnowledgeRunBinding,
    digest,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.capacity_input_reader import (
    CapacityInputReader,
    UninvokedClaimBoundary,
)
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.manager.knowledge_invocation_proof import require_knowledge_claim_context
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.work_queue.claim_snapshot import require_claim_snapshot
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueError


class RejectedKnowledgeQueue(Protocol):
    def original_claim(self, lease_id: str) -> QueueClaim: ...
    def claims_for_work_item(self, work_item_id: str) -> tuple[QueueClaim, ...]: ...
    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]: ...
    def step_for_invocation(
        self, work_item_id: str, baseline_sha256: str | None
    ) -> QueuedRoleStep: ...


class RejectedKnowledgeCarryRefusal(DomainModel):
    """Actual fresh owner refused before invocation; no invented past event."""

    kind: Literal["rejected_knowledge_carry_refusal"] = "rejected_knowledge_carry_refusal"
    observation_sha256: Digest
    claim: QueueClaim
    claim_sha256: Digest
    refused_at: AwareDatetime
    refusal_sha256: Digest

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.claim_sha256 != claim_identity_sha256(self.claim) or self.refusal_sha256 != digest(
            self.model_dump(mode="json", exclude={"refusal_sha256"})
        ):
            raise ValueError("知识拒绝接续记录摘要不一致")


def rejected_assessment_for_work(
    *,
    records_root: Path,
    task: Task,
    item: QueuedWorkItem,
    scope: EngineeringScope,
    requirement_id: str,
) -> RejectedKnowledgeAssessment | None:
    """Inspect only the two documented exact lanes and this WorkItem's preparations."""
    bindings: dict[str, KnowledgeRunBinding] = {}
    for requirement in dict.fromkeys((requirement_id, task.id)):
        lane_id = invocation_scope_lane_sha256(
            team_id=scope.team_id,
            project_id=scope.project_id,
            requirement_id=requirement,
            repository_ids=(scope.repository_id,),
            task_id=task.id,
            role=TeamRole(item.role.value),
        )
        lane_path = records_root / "invocations" / lane_id
        if not lane_path.exists():
            continue
        lane = KnowledgeRecordStore(lane_path, read_only=True)
        intents = lane.list("knowledge-invocation-intents", KnowledgeInvocationIntent, limit=512)
        for intent in intents:
            claimed = intent.claim
            if claimed is None or claimed.work_item.id != item.id:
                continue
            intent.validate_integrity()
            if intent.phase != "assessment":
                continue
            outcome = lane.find(
                "knowledge-invocation-outcomes",
                intent.binding.run_id + ":" + intent.phase,
                KnowledgeInvocationOutcome,
            )
            # This guard only owns complete RETURNED semantic assessments. Empty
            # query consultations, local-limit/provider failures and unknown calls
            # remain the responsibility of their existing typed knowledge gate.
            if outcome is None or outcome.state != "RETURNED":
                continue
            outcome.validate_integrity()
            if outcome.intent != intent:
                raise KnowledgeError("ASSESSMENT_REJECTION_INTENT_CHANGED")
            bindings[intent.binding.run_id] = intent.binding
    if not bindings:
        return None
    if len(bindings) != 1:
        raise ValueError("原工作项含不同知识输入或未知接续调用")
    try:
        return derive_rejected_assessment(records_root, next(iter(bindings.values())))
    except KnowledgeError as error:
        if str(error) == "ASSESSMENT_REJECTION_NOT_REJECTED":
            return None
        raise


def rejected_knowledge_evidence(
    *,
    observation: RejectedKnowledgeAssessment,
    task: Task,
    item: QueuedWorkItem,
    step: QueuedRoleStep,
    scope: EngineeringScope,
    state: Path,
    route_root: Path,
    queue: RejectedKnowledgeQueue,
    artifacts: ArtifactStore,
    git: GitWorktreeManager,
    current_claim: QueueClaim | None = None,
    require_carry: bool = True,
) -> RejectedKnowledgePreparationEvidence:
    """Reopen all source, original ownership, absence and complete draft inputs."""
    observation.validate_integrity()
    original = observation.original_claim
    bound = observation.binding
    require_claim_snapshot(original, queue.original_claim(original.lease.id))
    claims = tuple(
        sorted(
            queue.claims_for_work_item(item.id), key=lambda value: value.work_item.dispatch_sequence
        )
    )
    if current_claim is None:
        if not claims:
            raise ValueError("知识拒绝没有真实 claim")
        current_claim = max(claims, key=lambda value: value.work_item.dispatch_sequence)
    current = current_claim
    require_claim_snapshot(current, queue.original_claim(current.lease.id))
    if (
        task.status is not TaskStatus.IMPLEMENTING
        or item.role is not AgentRole.CODER
        or bound.task_id != task.id
        or bound.role.value != item.role.value
        or (bound.team_id, bound.project_id, bound.repository_ids)
        != (scope.team_id, scope.project_id, (scope.repository_id,))
        or scope.repository_root != task.repository
        or bound.source_revision != step.boundary.source_revision
        or original.work_item.id != item.id
        or current.work_item.id != item.id
        or original.work_item.attempt != item.attempt
        or item.attempt != task.attempts
        or original.work_item.checkpoint_sequence != item.checkpoint_sequence
        or current.work_item.dispatch_sequence != item.dispatch_sequence
        or item.checkpoint_sequence != step.boundary.checkpoint_sequence
        or not claims
        or len(claims) > 512
        or claims[0].lease.id != original.lease.id
        or claims[-1].lease.id != current.lease.id
        or any(
            value.work_item.task_id != task.id
            or value.work_item.id != item.id
            or value.work_item.role is not item.role
            or value.work_item.attempt != item.attempt
            or value.work_item.checkpoint_sequence != item.checkpoint_sequence
            for value in claims
        )
        or any(record.work_item_id == item.id for record in queue.accepted(task.id))
    ):
        raise ValueError("知识拒绝恢复的任务、范围、claim 或接纳事实已变化")
    records_root = state.parent / "knowledge/runs"
    if derive_rejected_assessment(records_root, bound) != observation:
        raise ValueError("知识拒绝恢复的精确封存事实已变化")
    lane = KnowledgeRecordStore(
        records_root / "invocations" / invocation_lane_sha256(bound), read_only=True
    )
    intent = lane.get(
        "knowledge-invocation-intents", bound.run_id + ":assessment", KnowledgeInvocationIntent
    )
    context_sha = require_knowledge_claim_context(
        state,
        task,
        original.work_item,
        original,
        step,
        intent,
        KnowledgeRecordStore(records_root, read_only=True),
        scope,
    )
    context = FileContextStore(state.parent / "contexts", read_only=True).get(
        bound.context_manifest_id
    )
    original_task = Task.model_validate_json(
        next(section.content for section in context.sections if section.name == "task")
    )
    if (
        digest({"task": original_task.to_wire(), "context": context.to_wire()})
        != observation.input_sha256
    ):
        raise ValueError("知识拒绝原咨询输入与完整 Context 不一致")
    policy = TypeAdapter(dict[str, JsonValue]).validate_json(
        next(section.content for section in context.sections if section.name == "policy")
    )
    if policy.pop("denied_paths", None) != list(
        task.constraints.denied_paths if task.constraints else ()
    ):
        raise ValueError("知识拒绝 Context 的禁止路径与冻结 Task 不一致")
    permissions = AgentPermissions.model_validate(policy)
    reader = CapacityInputReader(
        state=state,
        queue=queue,
        artifacts=artifacts,
        route_root=route_root,
        baselines=None,
        permissions=permissions,
    )
    for claimed in claims:
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
    worktree = git.recover(
        WorktreeSpec(
            task_id=task.id, role=AgentRole.CODER, attempt=1, source_revision=bound.source_revision
        )
    )
    inventory = capture_mutation_inventory(worktree.path)
    directory = state / "execution-baselines" / task.id
    inputs = StoredCoderExecutionInputResolver(
        FileExecutionBaselineStore(directory, read_only=True) if directory.is_dir() else None
    )
    source = inputs.current(task, implementation=None, progress=None)
    retained = inputs.retained_source_paths(
        task, workspace_root=worktree.path, permissions=permissions
    )
    if source.source_revision != bound.source_revision:
        raise ValueError("知识拒绝恢复不能改变当前冻结执行基线")
    if source.baseline is not None:
        assert inputs.store is not None
        baseline = source.baseline
        plan = inputs.store.plan(baseline.plan_sha256)
        if (
            plan.facts.permissions != permissions
            or plan.facts.denied_paths
            != (task.constraints.denied_paths if task.constraints else ())
            or baseline.after_inventory_sha256 != inventory.sha256
        ):
            raise ValueError("知识准备前的完整已批准草稿或权限发生漂移")
    capture = CapturedMutations.from_capture(
        git.capture_mutations(
            worktree,
            permissions,
            denied_paths=task.constraints.denied_paths if task.constraints else (),
            base_revision=bound.source_revision,
            include_ignored=True,
            retained_source_paths=retained,
        )
    )
    if source.baseline is None and capture.mutations:
        raise ValueError("没有完整已批准草稿的知识准备恢复只接受干净输入")
    if capture_mutation_inventory(worktree.path) != inventory:
        raise ValueError("知识拒绝恢复的完整工作现场正在变化")
    carry_sha = None
    carry_history: list[str] = []
    previous = claims[0]
    for claimed in claims[1:]:
        if (
            claimed.work_item.dispatch_sequence <= previous.work_item.dispatch_sequence
            or claimed.claimed_at <= previous.claimed_at
        ):
            raise ValueError("知识拒绝接续不是严格递增的真实领取历史")
        need_record = claimed.lease.id != current.lease.id or require_carry
        if need_record:
            carry = KnowledgeRecordStore(state / "rejected-knowledge", read_only=True).get(
                "carry-refusals", claimed.lease.id, RejectedKnowledgeCarryRefusal
            )
            carry.validate_integrity()
            require_claim_snapshot(carry.claim, claimed)
            if (
                carry.observation_sha256 != observation.observation_sha256
                or carry.refused_at < claimed.claimed_at
            ):
                raise ValueError("知识拒绝接续没有精确原拒绝")
            if claimed.lease.id != current.lease.id:
                following = claims[claims.index(claimed) + 1]
                if carry.refused_at >= following.claimed_at:
                    raise ValueError("知识拒绝历史收尾晚于后继领取, 不能证明安全接续")
            carry_history.append(carry.refusal_sha256)
            if claimed.lease.id == current.lease.id:
                carry_sha = carry.refusal_sha256
        previous = claimed
    return RejectedKnowledgePreparationEvidence(
        scope=scope,
        requirement_id=bound.requirement_id,
        task_id=task.id,
        work_item_id=item.id,
        role=item.role,
        original_lease_id=original.lease.id,
        original_claim_sha256=observation.original_claim_sha256,
        original_attempt=item.attempt,
        original_dispatch_sequence=original.work_item.dispatch_sequence,
        checkpoint_sequence=item.checkpoint_sequence,
        previous_run_id=bound.run_id,
        previous_context_manifest_id=bound.context_manifest_id,
        source_revision=bound.source_revision,
        observation_sha256=observation.observation_sha256,
        context_sha256=context_sha,
        workspace_inventory_sha256=inventory.sha256,
        workspace_capture_sha256=digest(capture.to_wire()),
        current_lease_id=current.lease.id,
        current_claim_sha256=claim_identity_sha256(current),
        current_dispatch_sequence=current.work_item.dispatch_sequence,
        carry_refusal_sha256=carry_sha,
        carry_history_sha256s=tuple(carry_history),
    )


def carry_rejected_knowledge(
    *,
    task: Task,
    step: QueuedRoleStep,
    claim: QueueClaim,
    records: KnowledgeRecordStore,
    state: Path,
    queue: RejectedKnowledgeQueue,
    artifacts: ArtifactStore,
    git: GitWorktreeManager,
    scope: EngineeringScope,
    requirement_id: str,
) -> None:
    try:
        observation = rejected_assessment_for_work(
            records_root=records.root,
            task=task,
            item=claim.work_item,
            scope=scope,
            requirement_id=requirement_id,
        )
        if observation is None:
            return
        if observation.original_claim.lease.id == claim.lease.id:
            raise ValueError("知识拒绝不得在同一原所有者下重新执行")
        rejected_knowledge_evidence(
            observation=observation,
            task=task,
            item=claim.work_item,
            step=step,
            scope=scope,
            state=state,
            route_root=model_route_root(state.parent),
            queue=queue,
            artifacts=artifacts,
            git=git,
            current_claim=claim,
            require_carry=False,
        )
        from ai_software_engineer.work_queue.worker import WorkerExecutionGuard

        guard = current_execution_guard()
        if not isinstance(guard, WorkerExecutionGuard) or guard.lease is None:
            raise KnowledgeError("REJECTED_KNOWLEDGE_OWNER_REQUIRED")
        guard.check()
        require_claim_snapshot(guard.lease.claim, claim)
        carry_root = state / "rejected-knowledge"
        carry = (
            KnowledgeRecordStore(carry_root, read_only=True).find(
                "carry-refusals", claim.lease.id, RejectedKnowledgeCarryRefusal
            )
            if carry_root.is_dir()
            else None
        )
        if carry is None:
            carry = RejectedKnowledgeCarryRefusal(
                observation_sha256=observation.observation_sha256,
                claim=claim,
                claim_sha256=claim_identity_sha256(claim),
                refused_at=datetime.now(UTC),
                refusal_sha256="0" * 64,
            )
            carry = carry.model_copy(
                update={
                    "refusal_sha256": digest(
                        carry.model_dump(mode="json", exclude={"refusal_sha256"})
                    )
                }
            )
        carry.validate_integrity()
        require_claim_snapshot(carry.claim, claim)
        if carry.observation_sha256 != observation.observation_sha256:
            raise KnowledgeError("REJECTED_KNOWLEDGE_CARRY_CHANGED")
        with execution_scope(guard):
            records.put("assessment-rejections", observation.observation_sha256, observation)
            KnowledgeRecordStore(carry_root).put("carry-refusals", claim.lease.id, carry)
        raise KnowledgeAssessmentRejected(observation.reason, observation)
    except (
        ValueError,
        OSError,
        ArtifactStoreError,
        ContextStoreError,
        ModelRouteAttemptStoreError,
        GitWorkspaceError,
        ContinuationRejected,
        QueueError,
    ) as error:
        raise KnowledgeError("REJECTED_KNOWLEDGE_CARRY_UNAVAILABLE") from error
