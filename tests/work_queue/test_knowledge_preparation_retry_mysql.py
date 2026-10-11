"""Real native knowledge stop, exact wait resolution and fresh transactional claims."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.execution import bind_execution_guard
from ai_software_engineer.agents.structured import (
    CodexCliStructuredModelClient,
    FallbackStructuredModelClient,
    StructuredModelRoute,
)
from ai_software_engineer.domain import AgentRole, RiskTier, Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryProofMissing,
    DeliveryResolution,
    DeliveryResolutionKind,
    HandleDeliveryWait,
    InspectDeliveryWait,
    ResolveDeliveryWait,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.retry_policy import DeliveryRetryPolicy
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationIntent,
    KnowledgeInvocationJournal,
    KnowledgePreparationLocalLimit,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeRunBinding,
    KnowledgeSnapshot,
    digest,
)
from ai_software_engineer.knowledge.preparation_retry import (
    claim_identity_sha256,
    preparation_retry_evidence,
    read_local_limit,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
from ai_software_engineer.orchestration.retry import RetryingOrchestrator
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.store.mysql_repository import _encode, open_mysql_connection
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
)
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueConflict
from ai_software_engineer.work_queue.worker import (
    DeliveryWaiting,
    WorkerDeliveryFailureControl,
    WorkerExecutionGuard,
    WorkerLease,
)
from tests.agents.test_openai_compatible import _coder_request
from tests.domain.factories import make_task
from tests.git.test_worktree import _create_fixture_repository, _git
from tests.knowledge.test_consultation import Model
from tests.work_queue.test_worker_mysql import ALLOCATION_SHA, REPOSITORY_ID, TOKEN, claim_step

pytestmark = pytest.mark.mysql
DeliveryRole = Literal[AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER]


@dataclass
class KnowledgeWaiting:
    repository: MySqlTaskRepository
    queue: MySqlRoleQueue
    claim: QueueClaim
    entry: DeliveryWaitService
    records: KnowledgeRecordStore
    executable: Path
    worktree: Path
    source: str
    scope: EngineeringScope

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

    def fail_knowledge(self, claim: QueueClaim, timeout: int) -> KnowledgePreparationLocalLimit:
        task = self.repository.get(claim.work_item.task_id)
        frozen = KnowledgeSnapshot.create(
            team_id=self.scope.team_id,
            project_id=self.scope.project_id,
            requirement_id=task.id,
            repository_ids=(self.scope.repository_id,),
            documents=(),
        )
        self.records.put("snapshots", frozen.snapshot_sha256, frozen)
        bound = KnowledgeRunBinding(
            run_id="run_knowledge_" + digest(claim.lease.id)[:32],
            task_id=task.id,
            role=TeamRole(claim.work_item.role.value),
            team_id=frozen.team_id,
            project_id=frozen.project_id,
            requirement_id=task.id,
            repository_ids=frozen.repository_ids,
            source_revision=self.source,
            context_manifest_id="ctx_" + digest(claim.lease.id),
            snapshot_sha256=frozen.snapshot_sha256,
        )
        client = FallbackStructuredModelClient(
            (
                StructuredModelRoute(
                    provider="fixture",
                    model="fixture-knowledge",
                    client=CodexCliStructuredModelClient(
                        repository_root=self.worktree,
                        model="fixture-knowledge",
                        executable=str(self.executable),
                        environment={},
                    ),
                ),
            ),
            role=bound.role,
        )
        lease = WorkerLease(self.queue, claim, TOKEN)
        guard = WorkerExecutionGuard()
        guard.lease = lease
        lease.start()
        try:
            with (
                pytest.raises(KnowledgePreparationLocalLimit) as failed,
                bind_execution_guard(guard),
            ):
                KnowledgeConsultationService(
                    client,
                    self.records,
                    invocation_journal=KnowledgeInvocationJournal(
                        self.records, claimed=lambda: claim
                    ),
                ).consult(bound, frozen, {}, timeout_seconds=timeout)
            # Exercise the real knowledge failure router, including its owner-fenced wait.
            runner = RetryingOrchestrator.__new__(RetryingOrchestrator)
            runner._repository = self.repository
            runner._delivery_failure_control = WorkerDeliveryFailureControl(guard)
            with pytest.raises(DeliveryWaiting):
                runner._knowledge_failure(task, failed.value)
            return failed.value
        finally:
            lease.stop()
            guard.lease = None


@pytest.fixture
def knowledge_waiting(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[KnowledgeWaiting]:
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    selected = cast(
        DeliveryRole | tuple[DeliveryRole, str], getattr(request, "param", AgentRole.CODER)
    )
    role, task_id = selected if isinstance(selected, tuple) else (selected, None)
    root = _create_fixture_repository(tmp_path)
    source = _git(root, "rev-parse", "HEAD")
    scope = EngineeringScope(
        team_id="team_knowledge_retry",
        project_id="project_knowledge_retry",
        repository_id=REPOSITORY_ID,
        repository_root=str(root),
    )
    policy = DeliveryRetryPolicy()
    original = make_task()
    if task_id is not None:
        original = original.model_copy(update={"id": task_id})
    assert original.constraints is not None
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
            "engineering_policy": EngineeringPolicy.bounded_local(
                scope=scope,
                principal=LocalOperatorPrincipal.trusted_local(),
            ).to_wire(),
        }
    )
    now = datetime.now(UTC)
    with MySqlTaskRepository(dsn) as repository:
        repository.create(task)
        repository.record_attempt(task.id, 1)
        statuses = [TaskStatus.PLANNING, TaskStatus.IMPLEMENTING]
        if role in {AgentRole.QA, AgentRole.REVIEWER}:
            statuses.append(TaskStatus.QA)
        if role is AgentRole.REVIEWER:
            statuses.append(TaskStatus.REVIEW)
        for index, status in enumerate(statuses):
            repository.append_event(
                build_event(
                    repository.get(task.id),
                    status,
                    event_id=f"evt_knowledge_retry_{index}",
                    reason="knowledge retry fixture",
                    source_revision=source,
                    occurred_at=now,
                )
            )
        sequence = repository.current_revision(task.id)
        item = QueuedWorkItem(
            id="work_knowledge_retry_original",
            task_id=task.id,
            repository_id=REPOSITORY_ID,
            role=role,
            attempt=1,
            checkpoint_sequence=sequence,
            repository_scopes=(str(root),),
            status=WorkItemStatus.READY,
            preferred_agent_id=f"agent_{role.value}_001",
            priority=500,
            risk=RiskTier.NORMAL,
            required_capabilities=("delivery",),
            created_at=now,
            updated_at=now,
        )
        step = QueuedRoleStep(
            work_item=item,
            allocation_sha256=ALLOCATION_SHA,
            boundary=RoleRunBoundary(task.id, role, 1, sequence, source),
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
        git = GitWorktreeManager(root, tmp_path / "worktrees")
        worktree = git.create(
            WorktreeSpec(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=source,
            )
        ).path
        (worktree / "src" / "preserved.py").write_text("# existing legal development progress\n")
        executable = tmp_path / "slow-knowledge-model"
        executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(10)\n")
        executable.chmod(0o700)
        records = KnowledgeRecordStore(tmp_path / "sidecar" / "knowledge" / "runs")
        authority = tmp_path / "engineering-authority"
        authority.mkdir()

        def consume(resolution: DeliveryResolution) -> None:
            queue.resolve_wait(resolution)

        entry = DeliveryWaitService(
            repository=repository,
            queue=queue,
            scope=scope,
            sidecar_state=tmp_path / "sidecar" / "state",
            git=git,
            principal=LocalOperatorPrincipal.trusted_local(),
            consume=consume,
            engineering_authority=EngineeringAuthority(authority),
            knowledge_requirement_id=task.id,
            knowledge_retry=queue.knowledge_preparation_retry,
        )
        waiting = KnowledgeWaiting(
            repository, queue, claim, entry, records, executable, worktree, source, scope
        )
        waiting.fail_knowledge(claim, 1)
        yield waiting


@pytest.mark.parametrize(
    "knowledge_waiting", list((AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)), indirect=True
)
def test_real_local_limit_resolves_once_with_new_claim_and_same_task_source_and_progress(
    knowledge_waiting: KnowledgeWaiting,
) -> None:
    waiting = knowledge_waiting
    before = waiting.repository.get(waiting.claim.work_item.task_id)
    handling = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert handling.status == "RESOLVED" and handling.resolution is not None
    resolution = handling.resolution
    assert resolution.resolution_kind is DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION
    evidence = resolution.knowledge_preparation
    assert (
        evidence is not None
        and evidence.current_timeout_seconds == 1
        and evidence.next_timeout_seconds == 2
    )
    item = waiting.queue.resolve_wait(resolution)
    assert waiting.queue.resolve_wait(resolution) == item
    after = waiting.repository.get(before.id)
    assert (
        after.id == before.id
        and after.status is before.status
        and after.base_ref == before.base_ref
    )
    assert after.attempts == 2 and after.work_attempt == 2 and not after.retry_failures
    assert (
        item.role is waiting.claim.work_item.role
        and item.parent_work_item_id == waiting.claim.work_item.id
    )
    assert waiting.queue.step(item.id).boundary.source_revision == waiting.source
    next_claim = claim_step(waiting.queue, waiting.queue.step(item.id))
    assert next_claim.lease.id != waiting.claim.lease.id
    assert next_claim.assignment.id != waiting.claim.assignment.id
    assert next_claim.assignment.agent_id == f"agent_{item.role.value}_001"
    assert waiting.queue.knowledge_timeout(after, next_claim) == 2
    with pytest.raises(QueueConflict):
        waiting.queue.knowledge_timeout(after, waiting.claim)
    assert (
        waiting.worktree / "src" / "preserved.py"
    ).read_text() == "# existing legal development progress\n"
    assert _git(waiting.worktree, "rev-parse", "HEAD") == waiting.source
    assert not (waiting.entry.sidecar_state / "invocations").exists()
    assert waiting.queue.accepted(before.id) == ()


@pytest.mark.parametrize(
    "knowledge_waiting",
    [
        (AgentRole.QA, "task_continue_knowledge_qa"),
        (AgentRole.REVIEWER, "task_continue_knowledge_review"),
    ],
    indirect=True,
)
def test_real_legacy_verifier_knowledge_scope_resolves_under_its_native_parent(
    knowledge_waiting: KnowledgeWaiting,
) -> None:
    waiting = knowledge_waiting
    item = waiting.queue.get(waiting.claim.work_item.id)
    assert item.wait_disposition is not None
    outcome = read_local_limit(
        waiting.records.root,
        item.wait_disposition.facts.evidence_ids[0].removeprefix("knowledge-preparation://"),
    )
    bound = outcome.intent.binding
    frozen = waiting.records.get("snapshots", bound.snapshot_sha256, KnowledgeSnapshot)
    historical = bound.model_copy(
        update={"run_id": "run_legacy_scope_origin", "context_manifest_id": "ctx_" + "7" * 64}
    )
    with pytest.raises(KnowledgeGapRaised) as previous:
        KnowledgeConsultationService(Model(), waiting.records).consult(
            historical, frozen, {}, timeout_seconds=1
        )
    assert previous.value.gap.binding.requirement_id == item.task_id
    waiting.entry.knowledge_requirement_id = "delivery_multi_original_parent"
    handling = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert handling.status == "RESOLVED" and handling.resolution is not None
    knowledge = handling.resolution.knowledge_preparation
    assert knowledge is not None
    assert knowledge.requirement_id == item.task_id
    assert knowledge.delivery_requirement_id == "delivery_multi_original_parent"
    next_item = waiting.queue.resolve_wait(handling.resolution)
    next_claim = claim_step(waiting.queue, waiting.queue.step(next_item.id))
    current = waiting.repository.get(item.task_id)
    assert current.status in {TaskStatus.QA, TaskStatus.REVIEW}
    assert current.work_attempt == 2 and not current.retry_failures
    assert waiting.queue.knowledge_timeout(current, next_claim) == 2
    assert next_item.task_id == item.task_id and next_item.role is item.role
    assert _git(waiting.worktree, "rev-parse", "HEAD") == waiting.source


def test_missing_independent_native_receipt_keeps_wait_and_never_issues_next_claim(
    knowledge_waiting: KnowledgeWaiting,
) -> None:
    waiting = knowledge_waiting
    proof = waiting.entry.inspect(waiting.command())
    evidence = proof.knowledge_preparation
    assert evidence is not None
    intent = waiting.records.get(
        "knowledge-local-limit-intents",
        evidence.outcome_sha256,
        KnowledgeInvocationIntent,
    )
    lane = waiting.records.root / "invocations" / invocation_lane_sha256(intent.binding)
    (receipt,) = tuple(
        lane.glob(
            "knowledge-execution-records-" + digest(evidence.execution_record_sha256s[-1]) + ".json"
        )
    )
    receipt.unlink()
    handling = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert handling.resolution is None and handling.status == "PLATFORM_ATTENTION"
    assert DeliveryProofMissing.KNOWLEDGE_PREPARATION_UNAVAILABLE in handling.investigation.missing
    assert waiting.repository.get(waiting.claim.work_item.task_id).attempts == 1
    assert waiting.queue.get(waiting.claim.work_item.id).status is WorkItemStatus.WAITING_DEPENDENCY


def test_two_frozen_extensions_stop_at_four_times_initial_without_a_futile_action(
    knowledge_waiting: KnowledgeWaiting,
) -> None:
    waiting = knowledge_waiting
    evidence_chain = []
    for expected_window in (2, 4):
        handling = waiting.entry.handle(
            HandleDeliveryWait.model_validate(waiting.command().to_wire())
        )
        assert handling.resolution is not None
        evidence = handling.resolution.knowledge_preparation
        assert evidence is not None and evidence.next_timeout_seconds == expected_window
        evidence_chain.append(evidence)
        item = waiting.queue.resolve_wait(handling.resolution)
        claim = claim_step(waiting.queue, waiting.queue.step(item.id))
        timeout = waiting.queue.knowledge_timeout(waiting.repository.get(item.task_id), claim)
        assert timeout == expected_window
        waiting.claim = claim
        waiting.fail_knowledge(claim, timeout)
    assert evidence_chain[1].root_intent_sha256 == evidence_chain[0].intent_sha256
    assert evidence_chain[1].expansion_number == 2
    before = waiting.repository.get(waiting.claim.work_item.task_id)
    final = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert final.status == "BUDGET_EXHAUSTED" and final.resolution is None
    assert final.investigation.missing == (DeliveryProofMissing.KNOWLEDGE_WINDOW_EXHAUSTED,)
    assert final.investigation.permitted_resolutions == ()
    assert "扩窗上限" in final.summary
    assert waiting.repository.get(before.id) == before
    assert before.attempts == 3 and before.work_attempt == 3 and not before.retry_failures


@pytest.mark.parametrize("legacy", [True, False])
def test_no_frozen_capability_requires_exact_engineering_decision_without_upgrading_policy(
    knowledge_waiting: KnowledgeWaiting,
    legacy: bool,
) -> None:
    waiting = knowledge_waiting
    task = waiting.repository.get(waiting.claim.work_item.task_id)
    policy = task.engineering_policy
    assert policy is not None
    if legacy:
        policy = None
    else:
        from ai_software_engineer.domain.engineering_authority import EngineeringCapability

        policy = EngineeringPolicy.model_validate(
            {
                **policy.to_wire(),
                "grants": [
                    g.to_wire()
                    for g in policy.grants
                    if g.capability is not EngineeringCapability.DELIVERY_WAIT_RESOLUTION
                ],
            }
        )
    replacement = Task.model_validate(
        {
            **task.to_wire(),
            "engineering_policy": policy.to_wire() if policy else None,
        }
    )
    # Fixture-only persisted legacy setup; production never rewrites a frozen policy.
    with (
        closing(open_mysql_connection(waiting.queue._dsn)) as connection,
        connection.cursor(DictCursor) as cursor,
    ):
        cursor.execute(
            "UPDATE tasks SET payload_json=%s WHERE id=%s",
            (_encode(replacement.to_wire()), task.id),
        )
        item = waiting.queue.get(waiting.claim.work_item.id)
        assert item.wait_disposition is not None
        from ai_software_engineer.domain.continuation import task_intent_sha256
        from ai_software_engineer.domain.delivery_disposition import (
            DeliveryFailureFacts,
            decide_delivery_disposition,
        )

        disposition = decide_delivery_disposition(
            DeliveryFailureFacts.model_validate(
                {
                    **item.wait_disposition.facts.to_wire(),
                    "task_intent_sha256": task_intent_sha256(replacement),
                }
            )
        )
        item = item.model_copy(update={"wait_disposition": disposition})
        waiting.queue._update_item(cursor, item)
        connection.commit()
    handling = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert handling.status == "NEEDS_AUTHORIZATION" and handling.resolution is None
    proof = handling.investigation
    assert proof.permitted_resolutions == (DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION,)
    decision = waiting.entry.resolve(
        ResolveDeliveryWait.model_validate(
            {
                **waiting.command().to_wire(),
                "resolution_kind": DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION,
                "proof_sha256": proof.proof_sha256,
                "submitted_at": datetime.now(UTC),
            }
        )
    )
    assert decision.authorization_source == "engineering_operator_decision"
    assert decision.engineering_admission is None
    assert waiting.repository.get(task.id).engineering_policy == policy
    assert waiting.repository.get(task.id).attempts == 2


def test_original_repository_scopes_are_part_of_exact_claim_authority(
    knowledge_waiting: KnowledgeWaiting,
) -> None:
    waiting = knowledge_waiting
    proof = waiting.entry.inspect(waiting.command())
    evidence = proof.knowledge_preparation
    assert evidence is not None
    outcome = read_local_limit(waiting.records.root, evidence.outcome_sha256)
    original = waiting.queue.original_claim(evidence.original_lease_id)
    foreign = original.model_copy(
        update={
            "work_item": original.work_item.model_copy(
                update={"repository_scopes": ("/foreign/repository",)},
            )
        }
    )
    assert claim_identity_sha256(foreign) != claim_identity_sha256(original)
    with pytest.raises(KnowledgeError, match="CLAIM_OR_SCOPE"):
        preparation_retry_evidence(
            outcome=outcome,
            task=waiting.repository.get(evidence.task_id),
            item=waiting.queue.get(evidence.work_item_id),
            source_revision=waiting.source,
            scope=waiting.scope,
            historical_claim=foreign,
            previous=None,
        )


def test_same_role_provider_successor_keeps_the_consumed_frozen_window(
    knowledge_waiting: KnowledgeWaiting,
) -> None:
    waiting = knowledge_waiting
    handling = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert handling.resolution is not None
    item = waiting.queue.resolve_wait(handling.resolution)
    claim = claim_step(waiting.queue, waiting.queue.step(item.id))
    task = waiting.repository.get(item.task_id)
    from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure

    waiting.repository.record_retry_failure(
        task.id,
        DeliveryRetryFailure(
            role=cast(DeliveryRole, item.role),
            attempt=task.attempts,
            code="PROVIDER_UNAVAILABLE",
            run_id="run_provider_retry_fixture",
        ),
    )
    after = waiting.repository.get(task.id)
    next_item = item.model_copy(
        update={
            "id": "work_provider_retry_successor",
            "attempt": after.attempts,
            "status": WorkItemStatus.READY,
            "parent_work_item_id": item.id,
            "dispatch_sequence": 0,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    step = QueuedRoleStep(
        work_item=next_item,
        allocation_sha256=ALLOCATION_SHA,
        boundary=RoleRunBoundary(
            task.id,
            cast(DeliveryRole, item.role),
            after.attempts,
            item.checkpoint_sequence,
            waiting.source,
        ),
    )
    waiting.queue.finish(claim, TOKEN, next_step=step, now=next_item.created_at)
    next_claim = claim_step(waiting.queue, step)
    assert waiting.queue.knowledge_timeout(after, next_claim) == 2
    assert after.work_attempt == 2 and after.transient_failures(item.role) == 1


def test_main_role_start_blocks_knowledge_preparation_restart(
    knowledge_waiting: KnowledgeWaiting,
) -> None:
    waiting = knowledge_waiting
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
    records = KnowledgeRecordStore(waiting.entry.sidecar_state / "invocations")
    records.put("invocation-starts", claim.work_item.id, start)
    handling = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert handling.resolution is None and handling.investigation.permitted_resolutions == ()
    assert DeliveryProofMissing.KNOWLEDGE_PREPARATION_UNAVAILABLE in handling.investigation.missing
    assert waiting.repository.get(claim.work_item.task_id).attempts == 1


def test_resolution_facts_rechecked_before_consumption_and_scope_drift_is_rejected(
    knowledge_waiting: KnowledgeWaiting,
) -> None:
    waiting = knowledge_waiting
    proof = waiting.entry.inspect(waiting.command())
    before = waiting.repository.get(waiting.claim.work_item.task_id)
    waiting.entry.knowledge_requirement_id = "requirement_other_project"
    with pytest.raises(ValueError, match="事实已变化"):
        waiting.entry.resolve(
            ResolveDeliveryWait.model_validate(
                {
                    **waiting.command().to_wire(),
                    "resolution_kind": DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION,
                    "proof_sha256": proof.proof_sha256,
                    "submitted_at": datetime.now(UTC),
                }
            )
        )
    assert waiting.repository.get(before.id) == before
    assert waiting.queue.get(waiting.claim.work_item.id).status is WorkItemStatus.WAITING_DEPENDENCY


def test_knowledge_budget_exhaustion_preserves_wait_without_advertising_retry(
    knowledge_waiting: KnowledgeWaiting,
) -> None:
    waiting = knowledge_waiting
    task = waiting.repository.get(waiting.claim.work_item.task_id)
    policy = task.retry_policy
    assert policy is not None
    exhausted = Task.model_validate({**task.to_wire(), "attempts": policy.max_work_attempts})
    with (
        closing(open_mysql_connection(waiting.queue._dsn)) as connection,
        connection.cursor(DictCursor) as cursor,
    ):
        cursor.execute(
            "UPDATE tasks SET payload_json=%s WHERE id=%s", (_encode(exhausted.to_wire()), task.id)
        )
        connection.commit()
    handling = waiting.entry.handle(HandleDeliveryWait.model_validate(waiting.command().to_wire()))
    assert handling.status == "BUDGET_EXHAUSTED" and handling.resolution is None
    assert handling.investigation.permitted_resolutions == ()
    assert handling.investigation.missing == (DeliveryProofMissing.BUDGET_EXHAUSTED,)
    assert waiting.repository.get(task.id) == exhausted
