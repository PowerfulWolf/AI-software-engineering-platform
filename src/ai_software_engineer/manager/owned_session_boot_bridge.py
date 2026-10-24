"""Read-only stable-boot continuity for exact already-sealed local native stops.

The old receipt and proof are never rewritten. An approved historical stable boot
observation can supplement their adjustable Darwin boot-time spelling, only along
this Task's verified recovery ancestry. Original birth/SID rechecks still apply.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import TypeAdapter

from ai_software_engineer.agents.execution import ExecutionStop, NativeProcessStop
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.agents.structured_observation import StructuredNativeStopReceipt
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, TeamRole
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import Task, task_matches_dispatch
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.legacy_containment import (
    LocalBootObservation,
    LocalBootObserver,
    TrustedLocalBootObserver,
)
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.owned_sessions import OwnedSessionStopProof, OwnedSessionUnknown
from ai_software_engineer.recovery.models import MAX_INHERITED_REAPPLY_INPUTS, RecoveryScope, digest
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.store import TaskRepository


@dataclass(frozen=True)
class _ValidatedBootAnchor:
    boot: LocalBootObservation
    account_sha256: str
    observed_at: datetime
    plan_sha256: str
    binding_sha256: str
    authority_sha256: str
    isolation_sha256: str
    recovery_chain_sha256s: tuple[str, ...]


def _current_account(machine_sha256: str) -> str:
    return hashlib.sha256(f"{machine_sha256}:uid:{os.getuid()}".encode()).hexdigest()


def _darwin_time(value: str, prefix: str) -> datetime:
    match = re.fullmatch(re.escape(prefix) + r":([0-9]{1,12}):([0-9]{1,6})", value)
    if match is None:
        raise OwnedSessionUnknown("legacy Darwin timestamp is incomplete")
    seconds, microseconds = int(match[1]), int(match[2])
    if seconds <= 0 or microseconds >= 1_000_000:
        raise OwnedSessionUnknown("legacy Darwin timestamp is incomplete")
    try:
        return datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=microseconds)
    except (OverflowError, OSError, ValueError) as error:
        raise OwnedSessionUnknown("legacy Darwin timestamp is unavailable") from error


@dataclass(frozen=True)
class _BootContinuity:
    original_proof: OwnedSessionStopProof
    read_anchor: Callable[[], _ValidatedBootAnchor]
    reread_witness: Callable[[], datetime]
    observer: LocalBootObserver
    account: Callable[[str], str] = _current_account

    def require_current(self, proof: OwnedSessionStopProof, observed_boot_identity: str) -> None:
        proof.validate_integrity()
        if (
            proof != self.original_proof
            or re.fullmatch(r"darwin:[0-9]+:[0-9]+", proof.boot_identity) is None
        ):
            raise OwnedSessionUnknown("legacy owned-session proof is not exactly bound")
        started_at = self.reread_witness()
        anchor = self.read_anchor()
        current = self.observer.observe()
        recorded_boot = _darwin_time(proof.boot_identity, "darwin")
        births = tuple(
            _darwin_time(p.birth_identity, "darwin-time") for p in proof.observed_processes
        )
        leader_birth = _darwin_time(proof.leader.birth_identity, "darwin-time")
        # Conservative contradiction checks only. These adjustable timestamps
        # never establish machine/session identity or replace the stable anchor.
        if (
            recorded_boot < min(anchor.boot.booted_at, current.booted_at)
            or recorded_boot > started_at
            or leader_birth < started_at
            or any(birth < leader_birth or birth > proof.observed_at for birth in births)
        ):
            raise OwnedSessionUnknown(
                "legacy owned-session timestamps contradict its local boundary"
            )
        if (
            observed_boot_identity != "darwin-session:" + current.boot_session_sha256
            or current.machine_sha256 != anchor.boot.machine_sha256
            or current.boot_session_sha256 != anchor.boot.boot_session_sha256
            or self.account(current.machine_sha256) != anchor.account_sha256
            or anchor.boot.booted_at > anchor.observed_at
            or current.booted_at > started_at
            or anchor.observed_at > started_at
            or started_at > proof.observed_at
            or proof.observed_at > datetime.now(UTC)
        ):
            raise OwnedSessionUnknown("legacy owned-session stable boot continuity is unconfirmed")


class ScopedNativeStopVerifier:
    """Trusted composition seam; request/model input cannot supply an anchor or skip.

    Every call reopens original envelope bytes and the full approved ancestry.
    The lower-level stop reader checks the original leader, observed births and
    full empty SID twice between fresh stable OS identity observations.
    """

    def __init__(
        self,
        *,
        state: Path,
        task: Task,
        scope: EngineeringScope,
        requirement_id: str,
        knowledge_requirement_id: str,
        repository: TaskRepository,
        observer: LocalBootObserver | None = None,
    ) -> None:
        self.state, self.task, self.scope = state, task, scope
        self.requirement_id, self.knowledge_requirement_id = (
            requirement_id,
            knowledge_requirement_id,
        )
        self.repository = repository
        self.observer = observer if observer is not None else TrustedLocalBootObserver()

    def _anchor(self) -> _ValidatedBootAnchor:
        current = self.repository.get(self.task.id)
        if (
            not task_matches_dispatch(current, self.task)
            or current.repository != self.scope.repository_root
            or task_intent_sha256(current) != task_intent_sha256(self.task)
        ):
            raise ValueError("stable boot bridge current Task changed")
        recovery_scope = RecoveryScope(
            team_id=self.scope.team_id,
            repository_id=self.scope.repository_id,
            repository_root=self.scope.repository_root,
            delivery_id=self.requirement_id,
        )
        recoveries: FileRecoveryStore | None = None
        seen: set[str] = set()
        chain: list[str] = []
        successor_created_at: datetime | None = None
        while True:
            if current.id in seen or len(seen) >= MAX_INHERITED_REAPPLY_INPUTS:
                raise ValueError("stable boot bridge ancestry is cyclic or exceeds bound")
            seen.add(current.id)
            root = self.state / "execution-baselines" / current.id
            if root.exists() or root.is_symlink():
                baselines = FileExecutionBaselineStore(root, read_only=True)
                candidates: list[_ValidatedBootAnchor] = []
                for binding in baselines.bindings_for_task(current.id):
                    if binding.purpose is not BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION:
                        continue
                    plan = baselines.plan(binding.plan_sha256)
                    proof = plan.facts.knowledge_isolation
                    if proof is None:
                        raise ValueError("stable boot anchor omitted its isolation proof")
                    proof.validate_integrity()
                    if (
                        proof.scope != self.scope
                        or proof.requirement_id != self.requirement_id
                        or proof.knowledge_requirement_id != self.knowledge_requirement_id
                        or proof.task_id != current.id
                        or task_intent_sha256(current) != proof.task_intent_sha256
                        or binding.authority_source != "engineering_operator_decision"
                        or binding.continuation_mode is not BaselineContinuationMode.PAUSE
                        or binding.knowledge_isolation_sha256 != proof.proof_sha256
                    ):
                        raise ValueError("stable boot anchor belongs to another approved scope")
                    surveys = (*proof.repository_surveys, *proof.worktree_surveys)
                    for survey in surveys:
                        survey.require_idle()
                    candidates.append(
                        _ValidatedBootAnchor(
                            boot=proof.boot,
                            account_sha256=proof.repository_surveys[0].account_sha256,
                            observed_at=max(
                                binding.completed_at, *(s.observed_at for s in surveys)
                            ),
                            plan_sha256=plan.plan_sha256,
                            binding_sha256=binding.binding_sha256,
                            authority_sha256=binding.authority_sha256,
                            isolation_sha256=proof.proof_sha256,
                            recovery_chain_sha256s=tuple(chain),
                        )
                    )
                if candidates:
                    anchor = max(candidates, key=lambda a: a.observed_at)
                    if (
                        successor_created_at is not None
                        and anchor.observed_at > successor_created_at
                    ):
                        raise ValueError("stable boot anchor postdates its recovery successor")
                    return anchor
            raw_plan = current.metadata.get("recovery_plan_sha256")
            if raw_plan is None:
                raise ValueError("no approved stable boot anchor in this Task ancestry")
            plan_sha = TypeAdapter(StageSha256).validate_python(raw_plan)
            if recoveries is None:
                recoveries = FileRecoveryStore(
                    self.state / f"recovery-{self.requirement_id}", scope=recovery_scope
                )
            recovery_plan = recoveries.get_plan(plan_sha)
            authorization = recoveries.get_authorization(plan_sha)
            sealed = recoveries.get_task_record(plan_sha)
            if (
                recovery_plan.source.scope != recovery_scope
                or recovery_plan.new_task_id != current.id
                or not authorization.decision.approved
                or not task_matches_dispatch(current, sealed.task)
                or recovery_plan.source.parent_delivery_id != self.knowledge_requirement_id
            ):
                raise ValueError("stable boot bridge recovery is outside exact approved lineage")
            parent = self.repository.get(recovery_plan.source.task_id)
            if (
                self.repository.current_revision(parent.id) != recovery_plan.source.task_revision
                or digest(parent.to_wire()) != recovery_plan.source.task_sha256
                or parent.repository != self.scope.repository_root
                or parent.status is not TaskStatus.BLOCKED
                or parent.updated_at > recovery_plan.created_at
            ):
                raise ValueError("stable boot bridge recovery predecessor changed")
            chain.extend(
                (
                    recovery_plan.plan_sha256,
                    authorization.authorization_sha256,
                    sealed.record_sha256,
                )
            )
            successor_created_at = recovery_plan.created_at
            current = parent

    def _require(
        self, stop: ExecutionStop, request: AgentRequest | None, witness: Callable[[], datetime]
    ) -> None:
        proof = stop.session_proof if isinstance(stop, NativeProcessStop) else None
        bridge = (
            _BootContinuity(proof, self._anchor, witness, self.observer)
            if proof is not None and proof.boot_identity.startswith("darwin:")
            else None
        )
        NativeCoderContinuation._require_stopped(stop, request, boot_continuity=bridge)

    def require_knowledge(
        self,
        receipt: StructuredNativeStopReceipt,
        outcome: KnowledgeInvocationOutcome,
        context_sha256: str,
    ) -> None:
        def witness() -> datetime:
            outcome.validate_integrity()
            receipt.validate_integrity()
            intent, bound = outcome.intent, outcome.intent.binding
            if (
                bound.task_id != self.task.id
                or bound.team_id != self.scope.team_id
                or bound.project_id != self.scope.project_id
                or bound.repository_ids != (self.scope.repository_id,)
                or bound.requirement_id not in (self.knowledge_requirement_id, self.task.id)
                or bound.role is not TeamRole.CODER
                or intent.claim is None
                or intent.claim.work_item.repository_scopes != (self.scope.repository_root,)
                or receipt.admission.call.route_kind != "codex_cli"
                or receipt not in tuple(record.observation for record in outcome.executions)
            ):
                raise ValueError("stable boot bridge knowledge witness is not exact local Coder")
            records = KnowledgeRecordStore(
                self.state.parent / "knowledge/runs/invocations" / invocation_lane_sha256(bound),
                read_only=True,
            )
            if (
                records.get(
                    "knowledge-invocation-intents", bound.run_id + ":" + intent.phase, type(intent)
                )
                != intent
                or records.get(
                    "knowledge-invocation-outcomes",
                    bound.run_id + ":" + intent.phase,
                    type(outcome),
                )
                != outcome
            ):
                raise ValueError("stable boot bridge original knowledge envelope changed")
            KnowledgeInvocationJournal._require_outcome(records, intent, outcome)
            context = FileContextStore(self.state.parent / "contexts", read_only=True).get(
                bound.context_manifest_id
            )
            if (
                context.task_id != self.task.id
                or context.role is not AgentRole.CODER
                or context.source_revision != bound.source_revision
                or digest(context.to_wire()) != context_sha256
            ):
                raise ValueError("stable boot bridge knowledge Context changed")
            return receipt.admission.admitted_at

        self._require(receipt.process_stop, None, witness)

    def require_stopped(self, stop: ExecutionStop, request: AgentRequest | None = None) -> None:
        def witness() -> datetime:
            if (
                request is None
                or request.task_id != self.task.id
                or request.role is not AgentRole.CODER
            ):
                raise ValueError("stable boot bridge requires an exact original Coder request")
            ledger = FileContinuationStore(
                self.state / "continuations" / self.task.id, task_id=self.task.id
            )
            start, sealed = (
                ledger.capture_start(request.run_id),
                ledger.capture_stop(request.run_id),
            )
            if (
                start.request != request
                or sealed.process_stop != stop
                or (
                    start.scope.team_id,
                    start.scope.project_id,
                    start.scope.repository_id,
                    start.scope.requirement_id,
                )
                != (
                    self.scope.team_id,
                    self.scope.project_id,
                    self.scope.repository_id,
                    self.requirement_id,
                )
            ):
                raise ValueError("stable boot bridge capture witness changed")
            return start.started_at

        self._require(stop, request, witness)
