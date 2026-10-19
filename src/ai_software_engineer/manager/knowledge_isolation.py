"""Current local engineering containment keeps legacy knowledge execution unknown."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self

from pydantic import Field, model_validator

from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, TeamRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.legacy_scope import require_delivery_requirement_scope
from ai_software_engineer.knowledge.preparation_retry import claim_identity_sha256
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.legacy_containment import LocalBootObservation
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionObserver,
    LegacyLocalExecutionSurvey,
)
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue.claim_snapshot import require_claim_snapshot
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem

if TYPE_CHECKING:
    from ai_software_engineer.manager.capacity_input_reader import CapacityInputReader
    from ai_software_engineer.manager.knowledge_invocation_proof import KnowledgeProofQueue


class KnowledgePreparationIsolationProof(DomainModel):
    """An exact present observation, never an original no-start or stop receipt."""

    kind: Literal["knowledge_preparation_isolation_v1"] = "knowledge_preparation_isolation_v1"
    scope: EngineeringScope
    requirement_id: NonEmptyStr
    knowledge_requirement_id: NonEmptyStr
    dispatch_sha256: Sha256
    task_id: TaskId
    task_intent_sha256: Sha256
    task_revision: int = Field(ge=1)
    work_item_id: NonEmptyStr
    checkpoint_sequence: int = Field(ge=0)
    original_claim: QueueClaim
    original_step: QueuedRoleStep
    outcome: KnowledgeInvocationOutcome
    context_sha256: Sha256
    boot: LocalBootObservation
    repository_surveys: tuple[LegacyLocalExecutionSurvey, LegacyLocalExecutionSurvey]
    worktree_surveys: tuple[LegacyLocalExecutionSurvey, LegacyLocalExecutionSurvey]
    historical_execution_status: Literal["UNKNOWN"] = "UNKNOWN"
    ordinary_work_consumption: Literal[1] = 1
    no_transient_refund: Literal[True] = True
    proof_sha256: Sha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        outcome, claim, step = self.outcome, self.original_claim, self.original_step
        intent = outcome.intent
        bound = intent.binding
        outcome.validate_integrity()
        if (
            outcome.state != "FAILED"
            or outcome.failure is None
            or outcome.failure.code is not AgentErrorCode.SERVICE_PAUSED
            or outcome.failure.transient
            or outcome.executions
            or outcome.pre_admission_pause is not None
            or intent.claim is None
            or claim_identity_sha256(intent.claim) != claim_identity_sha256(claim)
            or bound.task_id != self.task_id
            or bound.role is not TeamRole.CODER
            or bound.team_id != self.scope.team_id
            or bound.project_id != self.scope.project_id
            or bound.repository_ids != (self.scope.repository_id,)
            or bound.requirement_id != self.knowledge_requirement_id
            or (claim.work_item.id, claim.work_item.task_id, claim.work_item.role)
            != (self.work_item_id, self.task_id, AgentRole.CODER)
            or claim.work_item.checkpoint_sequence != self.checkpoint_sequence
            or self.task_revision != self.checkpoint_sequence
            or step.work_item.id != self.work_item_id
            or step.boundary.task_id != self.task_id
            or step.boundary.role is not AgentRole.CODER
            or step.boundary.attempt != claim.work_item.attempt
            or step.boundary.source_revision != bound.source_revision
            or step.allocation_sha256 != self.dispatch_sha256
            or claim.work_item.repository_id != self.scope.repository_id
            or claim.work_item.repository_scopes != (self.scope.repository_root,)
        ):
            raise ValueError("当前知识隔离必须精确保留旧知识失败、原 claim 和未知执行历史")
        surveys = (*self.repository_surveys, *self.worktree_surveys)
        for survey in surveys:
            survey.require_idle()
            if (
                survey.machine_sha256 != self.boot.machine_sha256
                or survey.boot_session_sha256 != self.boot.boot_session_sha256
                or survey.observed_at < outcome.completed_at
            ):
                raise ValueError("当前知识隔离调查没有绑定同机启动会话和旧结果之后的观察")
        for pair in (self.repository_surveys, self.worktree_surveys):
            if not pair[0].same_boundary(pair[1]) or pair[0].observed_at > pair[1].observed_at:
                raise ValueError("当前知识隔离的双重调查边界或时序不一致")
        if (
            self.repository_surveys[0].worktree_path != self.scope.repository_root
            or self.repository_surveys[0].account_sha256 != self.worktree_surveys[0].account_sha256
            or self.repository_surveys[0].scanner_version
            != self.worktree_surveys[0].scanner_version
        ):
            raise ValueError("当前知识隔离没有覆盖同账户的仓库和 Coder 工作区")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.proof_sha256 != digest(self.model_dump(mode="json", exclude={"proof_sha256"})):
            raise ValueError("当前知识准备隔离记录完整性异常")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "proof_sha256": "0" * 64})
        return value.model_copy(
            update={"proof_sha256": digest(value.model_dump(mode="json", exclude={"proof_sha256"}))}
        )


def read_unknown_knowledge_preparation(
    *,
    state: Path,
    task: Task,
    item: QueuedWorkItem,
    scope: EngineeringScope,
    requirement_id: str,
    queue: KnowledgeProofQueue,
    require_step: Callable[[QueuedWorkItem, QueuedRoleStep], None],
    no_start_reader: CapacityInputReader,
) -> tuple[KnowledgeInvocationOutcome, QueueClaim, QueuedRoleStep, str]:
    """Read one legacy unknown preparation; its missing observations grant no authority."""
    from ai_software_engineer.manager.capacity_input_reader import UninvokedClaimBoundary
    from ai_software_engineer.manager.knowledge_invocation_proof import (
        _knowledge_lanes,
        require_knowledge_claim_context,
    )

    lanes = _knowledge_lanes(
        state=state, task=task, item=item, scope=scope, requirement_id=requirement_id
    )
    selected = tuple(
        (lane, intent)
        for lane in lanes
        for intent in lane.intents
        if intent.claim is not None and intent.claim.work_item.id == item.id
    )
    if len(selected) != 1:
        raise ValueError("当前知识隔离只处理一个完整精确的旧知识准备, 不猜测混合调用")
    lane, intent = selected[0]
    assert intent.claim is not None
    same_lease = tuple(
        other
        for candidate in lanes
        for other in candidate.intents
        if other.claim is not None and other.claim.lease.id == intent.claim.lease.id
    )
    if len(same_lease) != 1:
        raise ValueError("旧知识准备同一真实 claim 还有其他调用, 不适用当前单一隔离路径")
    require_delivery_requirement_scope(
        intent.binding,
        requirement_id,
        records=KnowledgeRecordStore(state.parent / "knowledge" / "runs", read_only=True),
    )
    intent.validate_integrity()
    if invocation_lane_sha256(intent.binding) != lane.lane_id:
        raise ValueError("旧知识准备 lane 与冻结输入不一致")
    outcome = lane.outcome_map.get(intent.intent_sha256)
    if outcome is None:
        raise ValueError("旧知识准备缺少完整封存结果")
    KnowledgeInvocationJournal._require_outcome(lane.records, intent, outcome)
    if outcome.executions or any(
        v.intent_sha256 == intent.intent_sha256 for v in lane.observations
    ):
        raise ValueError("旧知识准备已有原生或 HTTP 执行观察, 不适用当前隔离路径")
    if intent.claim is None:
        raise ValueError("旧知识准备缺少原 claim")
    claim = queue.original_claim(intent.claim.lease.id)
    require_claim_snapshot(intent.claim, claim)
    step = queue.step_for_claim(claim)
    require_step(claim.work_item, step)
    context_sha256 = require_knowledge_claim_context(
        state,
        task,
        claim.work_item,
        claim,
        step,
        intent,
        KnowledgeRecordStore(state.parent / "knowledge" / "runs", read_only=True),
        scope,
    )
    no_start_reader.require_claim_not_started(
        UninvokedClaimBoundary(
            task_id=task.id,
            work_item_id=item.id,
            lease_id=claim.lease.id,
            role=item.role,
            attempt=item.attempt,
            checkpoint_sequence=item.checkpoint_sequence,
            dispatch_sequence=claim.work_item.dispatch_sequence,
            observed_at=outcome.completed_at,
            run_id=intent.binding.run_id,
            context_manifest_id=intent.binding.context_manifest_id,
        ),
        allow_later_claims=True,
    )
    return outcome, claim, step, context_sha256


def observe_isolation_boundary(
    *,
    observer: LegacyLocalExecutionObserver,
    boot: LocalBootObservation,
    repository_root: Path,
    worktree_root: Path,
) -> tuple[
    tuple[LegacyLocalExecutionSurvey, LegacyLocalExecutionSurvey],
    tuple[LegacyLocalExecutionSurvey, LegacyLocalExecutionSurvey],
]:
    repository = tuple(observer.observe(worktree_root=repository_root, boot=boot) for _ in range(2))
    worktree = tuple(observer.observe(worktree_root=worktree_root, boot=boot) for _ in range(2))
    for survey in (*repository, *worktree):
        survey.require_idle()
    return (repository[0], repository[1]), (worktree[0], worktree[1])


def require_current_isolation_boundary(
    proof: KnowledgePreparationIsolationProof,
    *,
    observer: LegacyLocalExecutionObserver,
    boot: LocalBootObservation,
    repository_root: Path,
    worktree_root: Path,
) -> None:
    proof.validate_integrity()
    if proof.boot != boot or (str(repository_root), str(worktree_root)) != (
        proof.scope.repository_root,
        proof.worktree_surveys[0].worktree_path,
    ):
        raise ValueError("当前知识隔离的电脑或完整工作区边界已变化")
    repository, worktree = observe_isolation_boundary(
        observer=observer,
        boot=boot,
        repository_root=repository_root,
        worktree_root=worktree_root,
    )
    for current, approved in zip(
        (*repository, *worktree), (*proof.repository_surveys, *proof.worktree_surveys), strict=True
    ):
        if not current.same_boundary(approved):
            raise ValueError("当前知识隔离的账户或调查器边界已变化")
