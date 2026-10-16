"""Exact returned knowledge rejection consumes one ordinary work attempt, once."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.agents.execution import bind_execution_guard
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextSource, FileContextBuilder, FileContextStore
from ai_software_engineer.domain import AgentRole, RiskTier, Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    HandleDeliveryWait,
    InspectDeliveryWait,
    ResolveDeliveryWait,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringCapability,
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.enums import NetworkAccess, TeamRole
from ai_software_engineer.domain.retry_policy import DeliveryRetryPolicy
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.assessment_rejection import (
    KnowledgeAssessmentRejected,
    RejectedKnowledgeAssessment,
    read_rejected_assessment,
)
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationJournal,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeRunBinding,
    KnowledgeSnapshot,
    digest,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
from ai_software_engineer.orchestration.retry import RetryingOrchestrator
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
)
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.worker import (
    DeliveryWaiting,
    WorkerDeliveryFailureControl,
    WorkerExecutionGuard,
    WorkerLease,
)
from tests.agents.test_openai_compatible import _coder_request
from tests.domain.factories import make_task
from tests.git.test_worktree import _create_fixture_repository, _git
from tests.knowledge.test_assessment_rejection import _native_executable
from tests.knowledge.test_invocation_native import _client
from tests.knowledge.test_retrieval_contract import document
from tests.work_queue.test_worker_mysql import ALLOCATION_SHA, REPOSITORY_ID, TOKEN, claim_step

pytestmark = pytest.mark.mysql


@dataclass
class RejectedKnowledgeWaiting:
    repository: MySqlTaskRepository
    queue: MySqlRoleQueue
    claim: QueueClaim
    entry: DeliveryWaitService
    records: KnowledgeRecordStore
    worktree: Path
    source: str
    observation: RejectedKnowledgeAssessment
    call_log: Path

    def command(self) -> InspectDeliveryWait:
        item = self.queue.get(self.claim.work_item.id)
        assert item.wait_disposition is not None
        facts = item.wait_disposition.facts
        return InspectDeliveryWait(
            work_item_id=item.id,
            expected_disposition_sha256=item.wait_disposition.disposition_sha256,
            expected_task_intent_sha256=facts.task_intent_sha256,
            expected_source_revision=facts.source_revision,
            expected_checkpoint_sequence=facts.checkpoint_sequence,
        )

    def immutable_bytes(self) -> dict[str, bytes]:
        roots = (self.records.root, self.records.root.parent.parent / "contexts")
        return {str(path): path.read_bytes() for root in roots for path in root.rglob("*.json")}


@pytest.fixture
def rejected_waiting(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[RejectedKnowledgeWaiting]:
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    root = _create_fixture_repository(tmp_path)
    source = _git(root, "rev-parse", "HEAD")
    scope = EngineeringScope(
        team_id="team_rejected_knowledge",
        project_id="project_rejected_knowledge",
        repository_id=REPOSITORY_ID,
        repository_root=str(root),
    )
    policy = DeliveryRetryPolicy()
    scenario = getattr(request, "param", "normal")
    if scenario.endswith("exhausted"):
        policy = DeliveryRetryPolicy(max_work_attempts=1)
    original = make_task()
    assert original.constraints is not None
    engineering = EngineeringPolicy.bounded_local(
        scope=scope, principal=LocalOperatorPrincipal.trusted_local()
    )
    if scenario == "manual":
        engineering = EngineeringPolicy.model_validate(
            {
                **engineering.to_wire(),
                "grants": [
                    grant.to_wire()
                    for grant in engineering.grants
                    if grant.capability is not EngineeringCapability.DELIVERY_WAIT_RESOLUTION
                ],
            }
        )
    task = Task.model_validate(
        {
            **original.to_wire(),
            "repository": str(root),
            "base_ref": source,
            "retry_policy": policy.to_wire(),
            "max_attempts": policy.execution_limit,
            "constraints": {
                **original.constraints.to_wire(),
                "max_attempts": policy.execution_limit,
            },
            "engineering_policy": engineering.to_wire(),
            "metadata": {
                **original.metadata,
                **({"repository_id": REPOSITORY_ID} if scenario.startswith("legacy") else {}),
            },
        }
    )
    now = datetime.now(UTC)
    with MySqlTaskRepository(dsn) as repository:
        repository.create(task)
        repository.record_attempt(task.id, 1)
        for index, status in enumerate((TaskStatus.PLANNING, TaskStatus.IMPLEMENTING)):
            repository.append_event(
                build_event(
                    repository.get(task.id),
                    status,
                    event_id=f"evt_knowledge_rejection_{index}",
                    reason="exact knowledge rejection fixture",
                    source_revision=source,
                    occurred_at=now,
                )
            )
        task = repository.get(task.id)
        sequence = repository.current_revision(task.id)
        item = QueuedWorkItem(
            id="work_rejected_knowledge_original",
            task_id=task.id,
            repository_id=REPOSITORY_ID,
            role=AgentRole.CODER,
            attempt=1,
            checkpoint_sequence=sequence,
            repository_scopes=(str(root),),
            status=WorkItemStatus.READY,
            preferred_agent_id="agent_coder_001",
            priority=500,
            risk=RiskTier.NORMAL,
            required_capabilities=("delivery",),
            created_at=now,
            updated_at=now,
        )
        step = QueuedRoleStep(
            work_item=item,
            allocation_sha256=ALLOCATION_SHA,
            boundary=RoleRunBoundary(task.id, AgentRole.CODER, 1, sequence, source),
        )
        queue = MySqlRoleQueue(dsn)
        queue.admit(
            RoleQueueAdmission(
                task_id=task.id,
                repository_id=REPOSITORY_ID,
                allocation_sha256=ALLOCATION_SHA,
                legacy_artifacts=(),
            ),
            step,
        )
        claim = claim_step(queue, step)
        git = GitWorktreeManager(root, tmp_path / "worktrees" / REPOSITORY_ID)
        worktree = git.create(
            WorktreeSpec(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=source,
            )
        ).path
        sidecar = tmp_path / "sidecar"
        records = KnowledgeRecordStore(sidecar / "knowledge" / "runs")
        frozen = KnowledgeSnapshot.create(
            team_id=scope.team_id,
            project_id=scope.project_id,
            requirement_id=(
                "delivery_multi_legacy_parent" if scenario == "legacy_parent" else task.id
            ),
            repository_ids=(scope.repository_id,),
            documents=(
                document().model_copy(
                    update={
                        "team_id": scope.team_id,
                        "project_id": scope.project_id,
                    }
                ),
            ),
        )
        records.put("snapshots", frozen.snapshot_sha256, frozen)
        permissions = AgentPermissions(
            read_paths=("**",),
            write_paths=("src/**",),
            commands=("python",),
            network=NetworkAccess.NONE,
        )
        claim_source = ContextSource(
            source_id="execution.claim",
            uri="claim://" + claim.lease.id,
            required=True,
            content=json.dumps(
                {
                    "task_id": task.id,
                    "work_item_id": claim.work_item.id,
                    "lease_id": claim.lease.id,
                    "assignment_id": claim.assignment.id,
                    "dispatch_sequence": claim.work_item.dispatch_sequence,
                    "role": claim.work_item.role.value,
                    "attempt": claim.work_item.attempt,
                    "checkpoint_sequence": claim.work_item.checkpoint_sequence,
                }
            ),
        )
        context = FileContextBuilder(root, permissions, sources=(claim_source,)).build(
            task,
            AgentRole.CODER,
            attempt=1,
        )
        FileContextStore(sidecar / "contexts").put(context)
        bound = KnowledgeRunBinding(
            run_id="run_knowledge_" + digest((context.context_id, frozen.snapshot_sha256))[:32],
            task_id=task.id,
            role=TeamRole.CODER,
            team_id=scope.team_id,
            project_id=scope.project_id,
            requirement_id=frozen.requirement_id,
            repository_ids=(scope.repository_id,),
            source_revision=source,
            context_manifest_id=context.context_id,
            snapshot_sha256=frozen.snapshot_sha256,
        )
        call_log = tmp_path / "native-calls"
        executable = _native_executable(tmp_path)
        executable.write_text(
            executable.read_text().replace("Path('calls')", f"Path({str(call_log)!r})")
        )
        client = _client(worktree, executable, bound.role)
        lease = WorkerLease(queue, claim, TOKEN)
        guard = WorkerExecutionGuard()
        guard.lease = lease
        lease.start()
        try:
            with (
                pytest.raises(KnowledgeAssessmentRejected) as rejected,
                bind_execution_guard(guard),
            ):
                KnowledgeConsultationService(
                    client,
                    records,
                    allow_repository_inspection=True,
                    invocation_journal=KnowledgeInvocationJournal(records, claimed=lambda: claim),
                ).consult(
                    bound,
                    frozen,
                    {"task": task.to_wire(), "context": context.to_wire()},
                    timeout_seconds=5,
                )
            observation = rejected.value.observation
            assert observation is not None
            runner = RetryingOrchestrator.__new__(RetryingOrchestrator)
            runner._repository = repository
            runner._delivery_failure_control = WorkerDeliveryFailureControl(guard)
            if not scenario.startswith("legacy"):
                with pytest.raises(DeliveryWaiting):
                    runner._knowledge_failure(task, rejected.value)
        finally:
            lease.stop()
            guard.lease = None
        authority = tmp_path / "engineering-authority"
        authority.mkdir()

        def consume(resolution: DeliveryResolution) -> None:
            queue.resolve_wait(resolution)

        entry = DeliveryWaitService(
            repository=repository,
            queue=queue,
            scope=scope,
            sidecar_state=sidecar / "state",
            git=git,
            principal=LocalOperatorPrincipal.trusted_local(),
            consume=consume,
            artifacts=FileArtifactStore(sidecar / "artifacts"),
            engineering_authority=EngineeringAuthority(authority),
            knowledge_requirement_id=task.id,
            knowledge_retry=queue.knowledge_preparation_retry,
        )
        yield RejectedKnowledgeWaiting(
            repository,
            queue,
            claim,
            entry,
            records,
            worktree,
            source,
            observation,
            call_log,
        )


def test_exact_returned_rejection_releases_owner_then_resolves_once_with_ordinary_work(
    rejected_waiting: RejectedKnowledgeWaiting,
) -> None:
    waiting = rejected_waiting
    before = waiting.repository.get(waiting.claim.work_item.task_id)
    bytes_before = waiting.immutable_bytes()
    assert waiting.queue.list_active_leases(now=datetime.now(UTC)) == ()
    original = waiting.queue.get(waiting.claim.work_item.id)
    assert original.status is WorkItemStatus.WAITING_DEPENDENCY
    assert original.wait_disposition is not None
    assert original.wait_disposition.facts.classification == "INVALID_OUTPUT"
    proof = waiting.entry.inspect(waiting.command())
    assert proof.permitted_resolutions == (
        DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION,
    )
    evidence = proof.rejected_knowledge
    assert (
        evidence is not None
        and evidence.observation_sha256 == waiting.observation.observation_sha256
    )
    handling = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert handling.status == "RESOLVED" and handling.resolution is not None
    resolution = handling.resolution
    assert resolution.resolution_kind is DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION
    assert resolution.knowledge_preparation is None and resolution.rejected_knowledge == evidence
    item = waiting.queue.resolve_wait(resolution)
    assert waiting.queue.resolve_wait(resolution) == item
    after = waiting.repository.get(before.id)
    assert after.attempts == before.attempts + 1 and after.work_attempt == before.work_attempt + 1
    assert after.status is before.status and after.base_ref == before.base_ref
    assert after.retry_failures == before.retry_failures and not after.retry_failures
    assert item.parent_work_item_id == original.id and item.id != original.id
    assert waiting.queue.step(item.id).boundary.source_revision == waiting.source
    next_claim = claim_step(waiting.queue, waiting.queue.step(item.id))
    assert next_claim.lease.id != waiting.claim.lease.id
    assert next_claim.assignment.id != waiting.claim.assignment.id
    assert waiting.queue.knowledge_timeout(after, next_claim) is None
    assert waiting.immutable_bytes() == bytes_before
    assert _git(waiting.worktree, "status", "--porcelain") == ""
    assert _git(waiting.worktree, "rev-parse", "HEAD") == waiting.source
    assert waiting.queue.accepted(before.id) == ()
    assert waiting.call_log.read_text().splitlines() == ["KnowledgeIntent", "KnowledgeAssessment"]
    assert (
        read_rejected_assessment(waiting.records.root, waiting.observation.observation_sha256)
        == waiting.observation
    )


@pytest.mark.parametrize("mutation", ["read", "record", "draft", "main"])
def test_changed_read_native_record_draft_or_late_main_refuses_without_new_work(
    rejected_waiting: RejectedKnowledgeWaiting,
    mutation: str,
) -> None:
    waiting = rejected_waiting
    before = waiting.repository.get(waiting.claim.work_item.task_id)
    if mutation == "read":
        identity = waiting.observation.manifest.evidence_ids[0]
        (waiting.records.root / waiting.records._name("evidence", identity)).unlink()
    elif mutation == "record":
        bound = waiting.observation.binding
        lane = KnowledgeRecordStore(
            waiting.records.root / "invocations" / invocation_lane_sha256(bound)
        )
        identity = waiting.observation.assessment_execution_record_sha256s[-1]
        (lane.root / lane._name("knowledge-execution-records", identity)).unlink()
    elif mutation == "draft":
        (waiting.worktree / "src" / "unexpected.py").write_text("# unapproved later mutation\n")
    else:
        claim = waiting.claim
        request = _coder_request().model_copy(
            update={
                "task_id": claim.work_item.task_id,
                "attempt": claim.work_item.attempt,
                "source_revision": waiting.source,
            }
        )
        start = DeliveryInvocationStart(
            work_item_id=claim.work_item.id,
            checkpoint_sequence=claim.work_item.checkpoint_sequence,
            request=request,
            lease_id=claim.lease.id,
            started_at=datetime.now(UTC),
            start_sha256="0" * 64,
        )
        start = start.model_copy(
            update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
        )
        KnowledgeRecordStore(waiting.entry.sidecar_state / "invocations").put(
            "invocation-starts",
            claim.work_item.id,
            start,
        )
    bytes_before = waiting.immutable_bytes()
    handling = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert handling.resolution is None and handling.investigation.permitted_resolutions == ()
    assert waiting.repository.get(before.id) == before
    assert waiting.queue.get(waiting.claim.work_item.id).status is WorkItemStatus.WAITING_DEPENDENCY
    assert waiting.immutable_bytes() == bytes_before
    assert waiting.call_log.read_text().splitlines() == ["KnowledgeIntent", "KnowledgeAssessment"]


@pytest.mark.parametrize("rejected_waiting", ["manual"], indirect=True)
def test_missing_frozen_capability_requires_exact_engineering_decision(
    rejected_waiting: RejectedKnowledgeWaiting,
) -> None:
    waiting = rejected_waiting
    task = waiting.repository.get(waiting.claim.work_item.task_id)
    policy = task.engineering_policy
    assert policy is not None
    handling = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert handling.status == "NEEDS_AUTHORIZATION" and handling.resolution is None
    assert waiting.repository.get(task.id).attempts == 1
    decision = waiting.entry.resolve(
        ResolveDeliveryWait.model_validate(
            {
                **waiting.command().to_wire(),
                "resolution_kind": DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION,
                "proof_sha256": handling.investigation.proof_sha256,
                "submitted_at": datetime.now(UTC),
            }
        )
    )
    assert decision.authorization_source == "engineering_operator_decision"
    assert decision.engineering_admission is None
    assert waiting.repository.get(task.id).attempts == 2
    assert waiting.repository.get(task.id).engineering_policy == policy


@pytest.mark.parametrize("rejected_waiting", ["exhausted"], indirect=True)
def test_work_budget_exhaustion_preserves_rejection_and_does_not_offer_retry(
    rejected_waiting: RejectedKnowledgeWaiting,
) -> None:
    waiting = rejected_waiting
    task = waiting.repository.get(waiting.claim.work_item.task_id)
    assert task.work_budget_exhausted
    handling = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert handling.status == "BUDGET_EXHAUSTED" and handling.resolution is None
    assert handling.investigation.permitted_resolutions == ()
    assert waiting.repository.get(task.id) == task


def test_product_only_principal_cannot_investigate_or_approve_knowledge_replacement(
    rejected_waiting: RejectedKnowledgeWaiting,
) -> None:
    waiting = rejected_waiting
    before = waiting.repository.get(waiting.claim.work_item.task_id)
    command = waiting.command()
    proof = waiting.entry.inspect(command)
    waiting.entry.principal = LocalOperatorPrincipal(
        operator_id="operator:product-only",
        duties=(OperatorDuty.PRODUCT,),
    )
    with pytest.raises(ValueError, match="ENGINEERING"):
        waiting.entry.inspect(command)
    with pytest.raises(ValueError, match="ENGINEERING"):
        waiting.entry.resolve(
            ResolveDeliveryWait.model_validate(
                {
                    **command.to_wire(),
                    "resolution_kind": DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION,
                    "proof_sha256": proof.proof_sha256,
                    "submitted_at": datetime.now(UTC),
                }
            )
        )
    assert waiting.repository.get(before.id) == before
    assert waiting.queue.get(waiting.claim.work_item.id).status is WorkItemStatus.WAITING_DEPENDENCY


@pytest.mark.parametrize("mutation", ["draft", "read"])
def test_changed_facts_after_exact_investigation_refuse_before_consumption(
    rejected_waiting: RejectedKnowledgeWaiting,
    mutation: str,
) -> None:
    waiting = rejected_waiting
    before = waiting.repository.get(waiting.claim.work_item.task_id)
    command = waiting.command()
    proof = waiting.entry.inspect(command)
    assert proof.rejected_knowledge is not None
    if mutation == "draft":
        (waiting.worktree / "src" / "unexpected.py").write_text("# changed after investigation\n")
    else:
        identity = waiting.observation.manifest.evidence_ids[0]
        (waiting.records.root / waiting.records._name("evidence", identity)).unlink()
    with pytest.raises(ValueError, match="事实已变化"):
        waiting.entry.resolve(
            ResolveDeliveryWait.model_validate(
                {
                    **command.to_wire(),
                    "resolution_kind": DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION,
                    "proof_sha256": proof.proof_sha256,
                    "submitted_at": datetime.now(UTC),
                }
            )
        )
    assert waiting.repository.get(before.id) == before
    assert waiting.queue.get(waiting.claim.work_item.id).status is WorkItemStatus.WAITING_DEPENDENCY


@pytest.mark.parametrize("mutation", ["none", "draft", "read"])
def test_sealed_unconsumed_decision_revalidates_original_facts_before_crash_replay(
    rejected_waiting: RejectedKnowledgeWaiting,
    mutation: str,
) -> None:
    waiting = rejected_waiting
    before = waiting.repository.get(waiting.claim.work_item.task_id)
    command = HandleDeliveryWait.model_validate(waiting.command().to_wire())
    real_consume = waiting.entry.consume

    def interrupted_consume(resolution: DeliveryResolution) -> None:
        resolution.validate_integrity()
        raise RuntimeError("fixture crash after immutable decision, before queue consumption")

    waiting.entry.consume = interrupted_consume
    with pytest.raises(RuntimeError, match="fixture crash"):
        waiting.entry.handle(command)
    sealed = waiting.entry.records.list("wait-resolutions", DeliveryResolution)
    assert len(sealed) == 1
    assert sealed[0].resolution_kind is DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION
    assert waiting.repository.get(before.id) == before
    waiting.entry.consume = real_consume
    if mutation == "draft":
        (waiting.worktree / "src" / "unexpected.py").write_text("# changed after sealed decision\n")
    elif mutation == "read":
        identity = waiting.observation.manifest.evidence_ids[0]
        (waiting.records.root / waiting.records._name("evidence", identity)).unlink()
    if mutation == "none":
        recovered = waiting.entry.handle(command)
        assert recovered.status == "RESOLVED" and recovered.resolution == sealed[0]
        after = waiting.repository.get(before.id)
        assert after.work_attempt == before.work_attempt + 1
        assert not after.retry_failures
        # Once consumed, the exact retry decision is idempotent even while a fresh
        # authorized Coder legitimately starts changing this retained worktree.
        (waiting.worktree / "src" / "next.py").write_text("# later authorized Coder progress\n")
        assert waiting.entry.handle(command).resolution == sealed[0]
        assert waiting.repository.get(before.id) == after
    else:
        with pytest.raises(ValueError, match=r"事实已变化|原等待"):
            waiting.entry.handle(command)
        assert waiting.repository.get(before.id) == before
        assert (
            waiting.queue.get(waiting.claim.work_item.id).status
            is WorkItemStatus.WAITING_DEPENDENCY
        )
    assert waiting.call_log.read_text().splitlines() == ["KnowledgeIntent", "KnowledgeAssessment"]
