"""Isolated transactional engineering decisions; no providers or production facts."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.artifacts.store import seal_artifact
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    NetworkAccess,
    RiskTier,
    Task,
    TaskStatus,
)
from ai_software_engineer.domain.artifact import QaReportArtifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryDisposition,
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    OriginalInvocationAuthority,
    PreContextRecoveryInputEvidence,
    StaticQaMissingEntryEvidence,
    VerificationRetryEvidence,
    VerifierPreparationEvidence,
    delivery_wait_resolution_plan_sha256,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringAdmission,
    EngineeringCapability,
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.domain.native_verification import NativeVerificationWaitReason
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure, DeliveryRetryPolicy
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGapService,
    KnowledgeResolution,
    KnowledgeResolutionSource,
)
from ai_software_engineer.knowledge.models import digest, text_digest
from ai_software_engineer.knowledge.queue import QueueKnowledgeWaitPort
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.preflight_gate import PreflightInvocationControl
from ai_software_engineer.manager.verifier_preparation import (
    VerifierPreparationCheckpoint,
    VerifierPreparationIntent,
    VerifierPreparationObservation,
)
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
    record_digest,
)
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationStart,
    DurableInvocationControl,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueConflict, QueueCorruption, QueueLeaseLost
from ai_software_engineer.work_queue.preparation_resume import static_qa_preparation_reclaimed
from ai_software_engineer.work_queue.worker import (
    WorkerDeliveryFailureControl,
    WorkerExecutionGuard,
)
from tests.agents.test_openai_compatible import _coder_request
from tests.domain.factories import (
    make_coder_progress_artifact,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_task,
)
from tests.knowledge.test_queue import bound, route
from tests.manager.test_native_verification import _Guard
from tests.work_queue.test_worker_mysql import (
    ALLOCATION_SHA,
    REPOSITORY_ID,
    TOKEN,
    claim_step,
    dispatcher,
)

pytestmark = pytest.mark.mysql
SOURCE = "a" * 40


def reseal(resolution: DeliveryResolution, **updates: object) -> DeliveryResolution:
    updated = DeliveryResolution.model_validate({**resolution.to_wire(), **updates})
    return updated.model_copy(update={"resolution_sha256": updated.recompute_sha256()})


@dataclass
class WaitingFixture:
    dsn: str
    repository: MySqlTaskRepository
    queue: MySqlRoleQueue
    step: QueuedRoleStep
    claim: QueueClaim
    disposition: DeliveryDisposition
    now: datetime
    original_claim: QueueClaim | None = None

    def resolution(
        self,
        kind: DeliveryResolutionKind = DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
        *,
        provider: bool = False,
    ) -> DeliveryResolution:
        task = self.repository.get(self.step.boundary.task_id)
        original = self.queue.original_claim(self.claim.lease.id)
        retry = kind is DeliveryResolutionKind.RETRY_FROM_CHECKPOINT
        authority = None
        if kind is DeliveryResolutionKind.REPLAY_RECORDED_RESULT:
            authority = OriginalInvocationAuthority(
                work_item_id=self.step.work_item.id,
                checkpoint_sequence=self.step.boundary.checkpoint_sequence,
                assignment=original.assignment,
                lease=original.lease,
                model_selection=original.model_selection,
                request_permissions=AgentPermissions(
                    read_paths=("**",),
                    write_paths=("src/**", "tests/**"),
                    commands=("pytest",),
                    network=NetworkAccess.NONE,
                ),
                run_id="run_wait_original",
                context_manifest_id="ctx_" + "c" * 64,
                source_revision=SOURCE,
                request_sha256="d" * 64,
            )
        value = DeliveryResolution(
            task_id=task.id,
            work_item_id=self.step.work_item.id,
            expected_disposition_sha256=self.disposition.disposition_sha256,
            expected_task_intent_sha256=task_intent_sha256(task),
            expected_source_revision=SOURCE,
            expected_checkpoint_sequence=self.step.boundary.checkpoint_sequence,
            task_revision=self.repository.current_revision(task.id),
            task_snapshot_sha256=digest(task.to_wire()),
            step_sha256=record_digest(self.step),
            resolution_kind=kind,
            proof_sha256="e" * 64,
            operator_principal=LocalOperatorPrincipal.trusted_local(),
            submitted_at=self.now + timedelta(seconds=3),
            resolution_sha256="0" * 64,
            retry_cause=("provider_transient" if provider else "local_execution_limit")
            if retry
            else None,
            retry_failure=DeliveryRetryFailure(
                role=AgentRole.CODER,
                attempt=task.attempts,
                code="PROVIDER_UNAVAILABLE",
                run_id="run_wait_original",
            )
            if retry and provider
            else None,
            original_authority=authority,
        )
        return value.model_copy(update={"resolution_sha256": value.recompute_sha256()})

    def resolution_events(self) -> int:
        with (
            closing(open_mysql_connection(self.dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT COUNT(*) AS total FROM work_queue_events "
                "WHERE work_item_id=%s AND event_type='WAIT_RESOLVED'",
                (self.step.work_item.id,),
            )
            row = cursor.fetchone()
            assert row is not None
            return int(row["total"])


@pytest.fixture
def waiting(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[WaitingFixture]:
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    now = datetime.now(UTC)
    policy = DeliveryRetryPolicy()
    original = make_task()
    variant = getattr(request, "param", AgentRole.CODER)
    role = variant[0] if isinstance(variant, tuple) else variant
    static_qa = isinstance(variant, tuple) and variant[1] in {"STATIC_QA", "STATIC_QA_RECLAIMED"}
    classification: Literal[
        "PLATFORM_BUG",
        "EXECUTION_UNCERTAIN",
        "NONTRANSIENT_INFRA",
        "ENVIRONMENT_UNAVAILABLE",
        "CONTEXT_CAPACITY",
    ] = (
        "ENVIRONMENT_UNAVAILABLE"
        if static_qa
        else "NONTRANSIENT_INFRA"
        if isinstance(variant, tuple) and variant[1] == "NONTRANSIENT_INFRA"
        else "CONTEXT_CAPACITY"
        if isinstance(variant, tuple) and variant[1] == "CONTEXT_CAPACITY"
        else "PLATFORM_BUG"
        if isinstance(variant, tuple) and variant[1] == "PLATFORM_BUG"
        else "EXECUTION_UNCERTAIN"
    )
    assert role in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
    role = cast(Literal[AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER], role)
    assert original.constraints is not None
    task = Task.model_validate(
        {
            **original.to_wire(),
            "repository": "/fixture/repository",
            "engineering_policy": EngineeringPolicy.bounded_local(
                scope=EngineeringScope(
                    team_id="team_test",
                    project_id="project_test",
                    repository_id=REPOSITORY_ID,
                    repository_root="/fixture/repository",
                ),
                principal=LocalOperatorPrincipal.trusted_local(),
            ).to_wire(),
            "max_attempts": policy.execution_limit,
            "retry_policy": policy.to_wire(),
            "constraints": {
                **original.constraints.to_wire(),
                "max_attempts": policy.execution_limit,
            },
        }
    )
    with MySqlTaskRepository(dsn) as repository:
        repository.create(task)
        repository.record_attempt(task.id, 1)
        phases: tuple[TaskStatus, ...] = (TaskStatus.PLANNING, TaskStatus.IMPLEMENTING)
        if role in {AgentRole.QA, AgentRole.REVIEWER}:
            phases += (TaskStatus.QA,)
        if role is AgentRole.REVIEWER:
            phases += (TaskStatus.REVIEW,)
        for index, status in enumerate(phases):
            repository.append_event(
                build_event(
                    repository.get(task.id),
                    status,
                    event_id=f"evt_wait_resolution_{index}",
                    reason="queue decision fixture",
                    source_revision=SOURCE,
                    occurred_at=now + timedelta(microseconds=index),
                )
            )
        task = repository.get(task.id)
        revision = repository.current_revision(task.id)
        current_clock = [now + timedelta(seconds=5)]
        queue = MySqlRoleQueue(dsn, clock=lambda: current_clock[0])
        item = QueuedWorkItem(
            id="work_wait_resolution_001",
            task_id=task.id,
            repository_id=REPOSITORY_ID,
            role=role,
            attempt=1,
            checkpoint_sequence=revision,
            repository_scopes=(task.repository,),
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
            boundary=RoleRunBoundary(task.id, role, 1, revision, SOURCE),
        )
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
        original_claim = claim
        if isinstance(variant, tuple) and variant[1] == "STATIC_QA_RECLAIMED":
            expires = claim.lease.expires_at
            retry_at = expires + timedelta(seconds=1)
            (reclaimed,) = queue.reclaim_expired(now=expires, retry_at=retry_at)
            ready_at = retry_at + timedelta(seconds=1)
            ready = queue.make_ready(reclaimed.id, now=ready_at)
            current_clock[0] = ready_at + timedelta(seconds=1)
            claimed = dispatcher(queue).tick(now=current_clock[0], work_item_id=ready.id).claim
            assert claimed is not None
            claim = claimed
            now = current_clock[0]
        if classification == "PLATFORM_BUG":
            store = FileArtifactStore(tmp_path / "artifacts")
            store.put(
                seal_artifact(
                    make_plan_artifact().model_copy(update={"task_id": task.id}), validated_at=now
                )
            )
            progress = make_coder_progress_artifact()
            progress = progress.model_copy(
                update={
                    "task_id": task.id,
                    "source_revision": SOURCE,
                    "context_manifest_id": "ctx_" + "c" * 64,
                    "producer": progress.producer.model_copy(
                        update={
                            "agent_id": claim.assignment.agent_id,
                            "run_id": "run_wait_original",
                        }
                    ),
                    "content": progress.content.model_copy(update={"checkpoint_sequence": 9}),
                }
            )
            queue.accept_artifact(claim, TOKEN, store, seal_artifact(progress, validated_at=now))
        if role is AgentRole.QA and not static_qa:
            store = FileArtifactStore(tmp_path / "artifacts")
            implementation = make_implementation_artifact()
            implementation = implementation.model_copy(
                update={
                    "task_id": task.id,
                    "parent_artifact_ids": (),
                }
            )
            store.put(seal_artifact(implementation, validated_at=now))
            qa = make_qa_artifact()
            payload = qa.to_wire()
            payload.update(
                task_id=task.id, source_revision=SOURCE, context_manifest_id="ctx_" + "c" * 64
            )
            payload["producer"] = {
                **qa.producer.to_wire(),
                "agent_id": claim.assignment.agent_id,
                "run_id": "run_wait_original",
            }
            payload["content"] = {
                **qa.content.to_wire(),
                "status": "FAIL",
                "criteria_results": [
                    {**result.to_wire(), "status": "NOT_TESTED"}
                    for result in qa.content.criteria_results
                ],
                "tests_run": [
                    {**result.to_wire(), "status": "ERROR"} for result in qa.content.tests_run
                ],
            }
            artifact = cast(
                QaReportArtifact,
                seal_artifact(
                    QaReportArtifact.model_validate(payload),
                    validated_at=now,
                ),
            )
            queue.accept_artifact(claim, TOKEN, store, artifact)
        disposition = decide_delivery_disposition(
            DeliveryFailureFacts(
                task_id=task.id,
                work_item_id=item.id,
                role=item.role,
                classification=classification,
                source_revision=SOURCE,
                task_intent_sha256=task_intent_sha256(task),
                checkpoint_sequence=revision,
                budget_available=True,
                evidence_ids=("verifier-preparation://" + "f" * 64,) if static_qa else (),
            )
        )
        queue.wait(
            item.id,
            lease_id=claim.lease.id,
            owner_token=TOKEN,
            status=WorkItemStatus.WAITING_HUMAN,
            reason=disposition.reason,
            disposition=disposition,
            now=now + timedelta(seconds=2),
        )
        yield WaitingFixture(dsn, repository, queue, step, claim, disposition, now, original_claim)


def _policy_resolution(waiting: WaitingFixture, *, drift: bool = False) -> DeliveryResolution:
    original = waiting.resolution()
    task = waiting.repository.get(waiting.step.boundary.task_id)
    policy = task.engineering_policy
    assert policy is not None
    if drift:
        policy = policy.model_copy(update={"max_total_admissions": policy.max_total_admissions + 1})
    admission = EngineeringAdmission.create(
        task_id=task.id,
        task_intent_sha256=task_intent_sha256(task),
        policy=policy,
        policy_sha256=policy.policy_sha256,
        plan_sha256=delivery_wait_resolution_plan_sha256(
            original.proof_sha256, original.resolution_kind
        ),
        facts_sha256=original.proof_sha256,
        capabilities=(EngineeringCapability.DELIVERY_WAIT_RESOLUTION,),
        admission_number=1,
        admitted_at=original.submitted_at,
    )
    return reseal(
        original,
        authorization_source="organization_engineering_policy",
        operator_principal=None,
        engineering_admission=admission.to_wire(),
    )


def test_policy_wait_resolution_checks_exact_frozen_admission_and_consumes_once(
    waiting: WaitingFixture,
) -> None:
    resolution = _policy_resolution(waiting)
    next_item = waiting.queue.resolve_wait(resolution)
    assert next_item.attempt == 2 and next_item.id != waiting.step.work_item.id
    assert waiting.queue.resolve_wait(resolution) == next_item
    assert waiting.resolution_events() == 1


def test_policy_wait_resolution_rejects_a_valid_admission_for_different_policy(
    waiting: WaitingFixture,
) -> None:
    with pytest.raises(QueueConflict, match="冻结授权"):
        waiting.queue.resolve_wait(_policy_resolution(waiting, drift=True))
    assert waiting.resolution_events() == 0
    assert waiting.queue.get(waiting.step.work_item.id).status is WorkItemStatus.WAITING_HUMAN


@pytest.mark.parametrize("waiting", [(AgentRole.CODER, "CONTEXT_CAPACITY")], indirect=True)
def test_pre_context_schedule_requires_real_claim_and_consumes_without_budget_refund(
    waiting: WaitingFixture,
) -> None:
    task = waiting.repository.get(waiting.step.boundary.task_id)
    claim = waiting.queue.original_claim(waiting.claim.lease.id)
    base = waiting.resolution(DeliveryResolutionKind.RESUME_UNINVOKED)
    original = PreContextRecoveryInputEvidence(
        plan_sha256="a" * 64,
        authorization_sha256="b" * 64,
        task_record_sha256="c" * 64,
        dispatch_sha256="d" * 64,
        seed_record_sha256="e" * 64,
        source_inventory_sha256="f" * 64,
        original_claim_sha256=digest(claim.to_wire()),
        original_lease_id=claim.lease.id,
        worktree_head_revision=SOURCE,
    )
    resolution = reseal(
        base,
        resolution_kind=DeliveryResolutionKind.SCHEDULE_RECOVERY_INPUT,
        authorization_reference="test-human-resolution:pre-context",
        recovery_input_schedule_sha256="1" * 64,
        pre_context_recovery_input=original.to_wire(),
    )
    assert waiting.queue.consumed_recovery_input_resolution(task.id) is None
    stale = original.model_copy(update={"original_claim_sha256": "9" * 64})
    with pytest.raises(QueueConflict, match="原 claim"):
        waiting.queue.resolve_wait(reseal(resolution, pre_context_recovery_input=stale.to_wire()))
    assert waiting.resolution_events() == 0
    ready = waiting.queue.resolve_wait(resolution)
    assert ready.id == waiting.step.work_item.id
    assert ready.dispatch_sequence == waiting.claim.work_item.dispatch_sequence + 1
    assert ready.attempt == task.attempts == 1
    assert waiting.repository.get(task.id) == task
    assert waiting.queue.consumed_recovery_input_resolution(task.id) == resolution
    assert waiting.queue.resolve_wait(resolution) == ready
    assert waiting.resolution_events() == 1


@pytest.mark.parametrize("waiting", [AgentRole.QA], indirect=True)
def test_candidate_environment_retry_consumes_work_once_keeps_old_qa_and_candidate(
    waiting: WaitingFixture,
) -> None:
    accepted = waiting.queue.accepted(waiting.step.boundary.task_id)
    previous = accepted[0]
    base = waiting.resolution(DeliveryResolutionKind.RESUME_UNINVOKED)
    resolution = reseal(
        base,
        resolution_kind=DeliveryResolutionKind.REVERIFY_CANDIDATE,
        verification_retry=VerificationRetryEvidence(
            candidate_revision=SOURCE,
            previous_qa_artifact_id=previous.receipt.artifact_id,
            previous_qa_sha256=previous.receipt.sha256,
            previous_run_id=previous.run_id,
            previous_context_manifest_id=previous.context_manifest_id,
            invocation_outcome_sha256="b" * 64,
            prerequisite_facts_sha256="f" * 64,
        ).to_wire(),
    )
    next_item = waiting.queue.resolve_wait(resolution)
    task = waiting.repository.get(waiting.step.boundary.task_id)
    assert task.status is TaskStatus.QA and task.attempts == 2 and task.work_attempt == 2
    assert not task.retry_failures and next_item.id != waiting.step.work_item.id
    assert waiting.queue.step(next_item.id).boundary.source_revision == SOURCE
    assert waiting.queue.accepted(task.id) == accepted
    assert waiting.queue.resolve_wait(resolution) == next_item
    assert waiting.repository.get(task.id).attempts == 2
    assert waiting.resolution_events() == 1
    assert resolution.verification_retry is not None
    stale = resolution.verification_retry.model_copy(update={"previous_qa_sha256": "a" * 64})
    with pytest.raises(QueueConflict):
        waiting.queue.resolve_wait(reseal(resolution, verification_retry=stale.to_wire()))


@pytest.mark.parametrize("waiting", [AgentRole.QA, AgentRole.REVIEWER], indirect=True)
def test_finished_native_preparation_retry_has_new_identity_without_provider_refund(
    waiting: WaitingFixture,
) -> None:
    base = waiting.resolution(DeliveryResolutionKind.RESUME_UNINVOKED)
    resolution = reseal(
        base,
        resolution_kind=DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION,
        verifier_preparation=VerifierPreparationEvidence(
            candidate_revision=SOURCE,
            preparation_checkpoint_sha256="a" * 64,
            previous_run_id="run_wait_original",
            previous_context_manifest_id="ctx_" + "c" * 64,
            request_sha256="b" * 64,
            native_execution_state="FINISHED",
            native_binding_plan_sha256="c" * 64,
            native_started_sha256="d" * 64,
            native_finished_sha256="e" * 64,
            native_failure_code="TIMEOUT",
            prerequisite_facts_sha256="f" * 64,
            budget_source="frozen_work_attempt",
        ).to_wire(),
    )
    before = waiting.queue.accepted(waiting.step.boundary.task_id)
    next_item = waiting.queue.resolve_wait(resolution)
    task = waiting.repository.get(waiting.step.boundary.task_id)
    assert task.attempts == 2 and task.work_attempt == 2 and not task.retry_failures
    assert next_item.attempt == 2 and next_item.role == waiting.step.boundary.role
    assert next_item.id != waiting.step.work_item.id
    assert waiting.queue.accepted(task.id) == before
    assert waiting.queue.resolve_wait(resolution) == next_item
    assert waiting.resolution_events() == 1


def _static_qa_resolution(waiting: WaitingFixture) -> DeliveryResolution:
    original = waiting.original_claim
    assert original is not None
    current = waiting.claim
    base = waiting.resolution(DeliveryResolutionKind.RESUME_UNINVOKED)
    preparation = VerifierPreparationEvidence(
        candidate_revision=SOURCE,
        preparation_checkpoint_sha256="f" * 64,
        previous_run_id="run_wait_original",
        previous_context_manifest_id="ctx_" + "c" * 64,
        request_sha256="b" * 64,
        native_execution_state="NOT_STARTED",
        prerequisite_facts_sha256="d" * 64,
    )
    static = StaticQaMissingEntryEvidence(
        candidate_revision=SOURCE,
        observation_sha256="e" * 64,
        plan_artifact_id="art_plan_001",
        plan_artifact_sha256="a" * 64,
        implementation_artifact_id="art_impl_001",
        implementation_artifact_sha256="b" * 64,
        preparation_checkpoint_sha256="f" * 64,
        original_lease_id=original.lease.id,
        wait_lease_id=current.lease.id,
        original_dispatch_sequence=original.work_item.dispatch_sequence,
        wait_dispatch_sequence=current.work_item.dispatch_sequence,
        original_claim_sha256=digest(original.to_wire()),
        wait_claim_sha256=digest(current.to_wire()),
        previous_run_id=preparation.previous_run_id,
        previous_context_manifest_id=preparation.previous_context_manifest_id,
        prerequisite_facts_sha256=preparation.prerequisite_facts_sha256,
    )
    return reseal(
        base,
        resolution_kind=DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY,
        verifier_preparation=preparation.to_wire(),
        static_qa_missing_entry=static.to_wire(),
    )


@pytest.mark.parametrize(
    "waiting",
    [(AgentRole.QA, "STATIC_QA"), (AgentRole.QA, "STATIC_QA_RECLAIMED")],
    indirect=True,
)
def test_static_qa_decision_creates_fresh_claim_without_spending_frozen_work(
    waiting: WaitingFixture,
) -> None:
    resolution = _static_qa_resolution(waiting)
    task_before = waiting.repository.get(resolution.task_id)
    next_item = waiting.queue.resolve_wait(resolution)
    assert next_item.id == waiting.step.work_item.id
    assert next_item.dispatch_sequence == waiting.claim.work_item.dispatch_sequence + 1
    assert next_item.status is WorkItemStatus.READY
    assert next_item.attempt == task_before.attempts
    assert waiting.queue.get(waiting.step.work_item.id).status is WorkItemStatus.READY
    assert waiting.repository.get(task_before.id) == task_before
    assert waiting.queue.resolve_wait(resolution) == next_item
    assert waiting.resolution_events() == 1
    claimed = (
        dispatcher(waiting.queue)
        .tick(now=waiting.now + timedelta(seconds=8), work_item_id=next_item.id)
        .claim
    )
    assert claimed is not None
    waiting.queue.start(
        claimed.work_item.id,
        lease_id=claimed.lease.id,
        owner_token=TOKEN,
        now=waiting.now + timedelta(seconds=9),
    )
    waiting.queue.renew(
        claimed.work_item.id,
        lease_id=claimed.lease.id,
        owner_token=TOKEN,
        now=waiting.now + timedelta(seconds=10),
        expires_at=claimed.lease.expires_at + timedelta(minutes=1),
    )
    assert waiting.queue.static_qa_resolution_for_claim(claimed) == resolution
    stale_claim = claimed.model_copy(update={"worker_id": "worker_changed"})
    with pytest.raises(QueueConflict, match="current claim"):
        waiting.queue.static_qa_resolution_for_claim(stale_claim)


@pytest.mark.parametrize("waiting", [(AgentRole.QA, "STATIC_QA")], indirect=True)
@pytest.mark.parametrize("make_ready", [False, True])
def test_static_qa_decision_carries_across_fenced_lease_reclaim(
    waiting: WaitingFixture, make_ready: bool
) -> None:
    resolution = _static_qa_resolution(waiting)
    item = waiting.queue.resolve_wait(resolution)
    first = (
        dispatcher(waiting.queue)
        .tick(now=waiting.now + timedelta(seconds=8), work_item_id=item.id)
        .claim
    )
    assert first is not None
    retry_at = first.lease.expires_at + timedelta(seconds=1)
    waiting.queue.reclaim_expired(now=first.lease.expires_at, retry_at=retry_at)
    claim_at = retry_at + timedelta(seconds=1)
    if make_ready:
        waiting.queue.make_ready(item.id, now=claim_at)
        claim_at += timedelta(seconds=1)
    second = dispatcher(waiting.queue).tick(now=claim_at, work_item_id=item.id).claim
    assert second is not None and second.lease.id != first.lease.id
    assert second.work_item.dispatch_sequence == first.work_item.dispatch_sequence + 1 + int(
        make_ready
    )
    with pytest.raises(QueueLeaseLost):
        waiting.queue.static_qa_resolution_for_claim(first)
    if make_ready:
        # A manual READY transition after a reclaimed generation has no
        # consumed engineering decision or independent no-start proof.
        with pytest.raises(QueueCorruption):
            waiting.queue.static_qa_resolution_for_claim(second)
    else:
        assert waiting.queue.static_qa_resolution_for_claim(second) == resolution
    assert waiting.resolution_events() == 1
    assert waiting.repository.get(item.task_id).attempts == item.attempt


@pytest.mark.parametrize(
    "waiting",
    [(AgentRole.QA, "STATIC_QA"), (AgentRole.QA, "STATIC_QA_RECLAIMED")],
    indirect=True,
)
def test_static_qa_claim_drift_rejects_without_consuming_wait(waiting: WaitingFixture) -> None:
    resolution = _static_qa_resolution(waiting)
    assert resolution.static_qa_missing_entry is not None
    changed = resolution.static_qa_missing_entry.model_copy(
        update={"original_claim_sha256": "0" * 64}
    )
    with pytest.raises(QueueConflict, match="historical claims"):
        waiting.queue.resolve_wait(reseal(resolution, static_qa_missing_entry=changed.to_wire()))
    assert waiting.queue.get(waiting.step.work_item.id).status is WorkItemStatus.WAITING_HUMAN
    assert waiting.resolution_events() == 0


@pytest.mark.parametrize("waiting", [(AgentRole.QA, "STATIC_QA")], indirect=True)
@pytest.mark.parametrize("tamper", ["delete", "wrong_kind"])
@pytest.mark.parametrize("reclaimed", [False, True])
def test_static_qa_missing_consumed_event_cannot_fall_back_to_ordinary_qa(
    waiting: WaitingFixture, tamper: str, reclaimed: bool
) -> None:
    resolution = _static_qa_resolution(waiting)
    item = waiting.queue.resolve_wait(resolution)
    claim = (
        dispatcher(waiting.queue)
        .tick(now=waiting.now + timedelta(seconds=8), work_item_id=item.id)
        .claim
    )
    assert claim is not None
    if reclaimed:
        retry_at = claim.lease.expires_at + timedelta(seconds=1)
        waiting.queue.reclaim_expired(now=claim.lease.expires_at, retry_at=retry_at)
        reclaimed_claim = (
            dispatcher(waiting.queue)
            .tick(now=retry_at + timedelta(seconds=1), work_item_id=item.id)
            .claim
        )
        assert reclaimed_claim is not None
        claim = reclaimed_claim
    with closing(open_mysql_connection(waiting.dsn)) as connection:
        with connection.cursor() as cursor:
            if tamper == "delete":
                cursor.execute(
                    "DELETE FROM work_queue_events WHERE work_item_id=%s "
                    "AND event_type='WAIT_RESOLVED'",
                    (item.id,),
                )
            else:
                cursor.execute(
                    "UPDATE work_queue_events SET payload_json=JSON_SET(payload_json, "
                    "'$.detail.resolution.resolution_kind', 'RESUME_UNINVOKED') "
                    "WHERE work_item_id=%s AND event_type='WAIT_RESOLVED'",
                    (item.id,),
                )
            assert cursor.rowcount == 1
        connection.commit()
    with pytest.raises(QueueCorruption):
        waiting.queue.static_qa_resolution_for_claim(claim)


@pytest.mark.parametrize("waiting", [AgentRole.QA], indirect=True)
def test_ordinary_qa_retry_scheduled_generation_has_no_static_authority(
    waiting: WaitingFixture,
) -> None:
    resumed = waiting.queue.resolve_wait(
        waiting.resolution(DeliveryResolutionKind.RESUME_UNINVOKED)
    )
    first = (
        dispatcher(waiting.queue)
        .tick(now=waiting.now + timedelta(seconds=8), work_item_id=resumed.id)
        .claim
    )
    assert first is not None
    retry_at = first.claimed_at + timedelta(seconds=2)
    waiting.queue.retry(
        resumed.id,
        lease_id=first.lease.id,
        owner_token=TOKEN,
        reason="fixture transient retry",
        now=first.claimed_at + timedelta(seconds=1),
        available_at=retry_at,
    )
    second = (
        dispatcher(waiting.queue)
        .tick(now=retry_at + timedelta(seconds=1), work_item_id=resumed.id)
        .claim
    )
    assert second is not None
    assert second.work_item.dispatch_sequence == first.work_item.dispatch_sequence + 1
    assert waiting.queue.static_qa_resolution_for_claim(second) is None


@pytest.mark.parametrize("waiting", [(AgentRole.QA, "STATIC_QA")], indirect=True)
@pytest.mark.parametrize("changed_column", ["task_id", "work_item_id"])
def test_static_qa_claim_row_must_bind_exact_task_and_work_item(
    waiting: WaitingFixture, changed_column: str
) -> None:
    item = waiting.queue.resolve_wait(_static_qa_resolution(waiting))
    claim = (
        dispatcher(waiting.queue)
        .tick(now=waiting.now + timedelta(seconds=8), work_item_id=item.id)
        .claim
    )
    assert claim is not None
    if changed_column == "work_item_id":
        decoy = QueuedWorkItem.model_validate(
            {
                **item.to_wire(),
                "id": "work_static_qa_decoy",
                "role": AgentRole.REVIEWER,
                "parent_work_item_id": None,
                "dispatch_sequence": 0,
            }
        )
        waiting.queue.enqueue(decoy)
        replacement = decoy.id
    else:
        replacement = "task_unrelated_static_qa"
    with closing(open_mysql_connection(waiting.dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE work_queue_claims SET {changed_column}=%s WHERE lease_id=%s",
                (replacement, claim.lease.id),
            )
            assert cursor.rowcount == 1
        connection.commit()
    with pytest.raises(QueueConflict, match="current claim"):
        waiting.queue.static_qa_resolution_for_claim(claim)


@pytest.mark.parametrize("provider", [False, True])
def test_retry_reserves_new_identity_and_separates_work_from_provider_budget(
    waiting: WaitingFixture,
    provider: bool,
) -> None:
    resolution = waiting.resolution(provider=provider)
    next_item = waiting.queue.resolve_wait(resolution)
    task = waiting.repository.get(resolution.task_id)
    assert task.status is TaskStatus.IMPLEMENTING and task.attempts == 2
    assert task.work_attempt == (1 if provider else 2)
    assert task.transient_failures(AgentRole.CODER) == int(provider)
    assert next_item.id != waiting.step.work_item.id
    assert next_item.parent_work_item_id == waiting.step.work_item.id
    assert next_item.attempt == 2 and next_item.status is WorkItemStatus.READY
    assert waiting.queue.get(waiting.step.work_item.id).status is WorkItemStatus.CLOSED
    next_step = waiting.queue.step(next_item.id)
    assert next_step.boundary.source_revision == SOURCE
    assert next_step.boundary.checkpoint_sequence == waiting.step.boundary.checkpoint_sequence
    assert waiting.repository.current_revision(task.id) == waiting.step.boundary.checkpoint_sequence
    assert waiting.queue.list_active_leases(now=waiting.now + timedelta(seconds=5)) == ()
    assert waiting.resolution_events() == 1


@pytest.mark.parametrize(
    "kind",
    [
        DeliveryResolutionKind.REPLAY_RECORDED_RESULT,
        DeliveryResolutionKind.RESUME_UNINVOKED,
    ],
)
def test_noninvoking_resolution_preserves_attempt_and_original_producer(
    waiting: WaitingFixture,
    kind: DeliveryResolutionKind,
) -> None:
    resolution = waiting.resolution(kind)
    before = waiting.repository.get(resolution.task_id)
    resumed = waiting.queue.resolve_wait(resolution)
    assert resumed.id == waiting.step.work_item.id and resumed.attempt == before.attempts
    assert resumed.status is WorkItemStatus.READY
    assert waiting.repository.get(resolution.task_id) == before
    original = waiting.queue.original_claim(waiting.claim.lease.id)
    assert original.assignment == waiting.claim.assignment
    assert original.model_selection == waiting.claim.model_selection
    assert waiting.resolution_events() == 1


def test_same_slot_multiple_uninvoked_waits_have_distinct_consumptions(
    waiting: WaitingFixture,
) -> None:
    first = waiting.resolution(DeliveryResolutionKind.RESUME_UNINVOKED)
    ready = waiting.queue.resolve_wait(first)
    claim = claim_step(waiting.queue, waiting.step.model_copy(update={"work_item": ready}))
    next_disposition = decide_delivery_disposition(
        waiting.disposition.facts.model_copy(
            update={
                "evidence_ids": ("delivery-preflight://second-wait",),
            }
        )
    )
    waiting.queue.wait(
        ready.id,
        lease_id=claim.lease.id,
        owner_token=TOKEN,
        status=WorkItemStatus.WAITING_HUMAN,
        reason=next_disposition.reason,
        disposition=next_disposition,
        now=waiting.now + timedelta(seconds=6),
    )
    second_fixture = replace(waiting, claim=claim, disposition=next_disposition)
    second = second_fixture.resolution(DeliveryResolutionKind.RESUME_UNINVOKED)
    resumed = waiting.queue.resolve_wait(second)
    assert resumed.id == ready.id and resumed.dispatch_sequence == ready.dispatch_sequence + 1
    assert waiting.queue.resolve_wait(first) == resumed
    assert waiting.queue.resolve_wait(second) == resumed
    assert waiting.resolution_events() == 2
    assert waiting.repository.get(first.task_id).attempts == 1
    assert not waiting.repository.get(first.task_id).retry_failures


@pytest.mark.parametrize("waiting", [AgentRole.QA, AgentRole.REVIEWER], indirect=True)
def test_preparation_resume_requires_real_consumed_generation_and_original_request(
    waiting: WaitingFixture,
) -> None:
    request = AgentRequest.model_validate(
        {
            **_coder_request().to_wire(),
            "task_id": waiting.step.boundary.task_id,
            "role": waiting.step.boundary.role.value,
            "source_revision": SOURCE,
            "output_schema": "schemas/qa-report.schema.json"
            if waiting.step.boundary.role is AgentRole.QA
            else "schemas/review-report.schema.json",
        }
    )
    intent = VerifierPreparationIntent.create(
        work_item_id=waiting.claim.work_item.id,
        lease_id=waiting.claim.lease.id,
        task_id=request.task_id,
        task_snapshot_sha256=digest(waiting.repository.get(request.task_id).to_wire()),
        checkpoint_sequence=waiting.claim.work_item.checkpoint_sequence,
        dispatch_sequence=waiting.claim.work_item.dispatch_sequence,
        request=request,
        request_sha256=digest(request.to_wire()),
        started_at=waiting.now,
    )
    evidence = VerifierPreparationEvidence(
        candidate_revision=SOURCE,
        preparation_checkpoint_sha256="b" * 64,
        previous_run_id=request.run_id,
        previous_context_manifest_id=request.context_manifest_id,
        request_sha256=digest(request.to_wire()),
        native_execution_state="NOT_STARTED",
        prerequisite_facts_sha256="f" * 64,
    )
    resolution = reseal(
        waiting.resolution(DeliveryResolutionKind.RESUME_UNINVOKED),
        verifier_preparation=evidence.to_wire(),
    )
    ready = waiting.queue.resolve_wait(resolution)
    current = claim_step(waiting.queue, waiting.step.model_copy(update={"work_item": ready}))
    reopened = MySqlRoleQueue(waiting.dsn)
    assert reopened.preparation_resume_consumed(intent, current)
    changed_request = request.model_copy(update={"run_id": "run_wrong_preparation"})
    changed_intent = VerifierPreparationIntent.create(
        **{
            **intent.to_wire(),
            "request": changed_request.to_wire(),
            "request_sha256": digest(changed_request.to_wire()),
        },
    )
    assert not reopened.preparation_resume_consumed(changed_intent, current)
    # A further real reclaim cannot reuse an approval bound to the former generation.
    reclaim_time = current.lease.expires_at + timedelta(seconds=1)
    retry_time = reclaim_time + timedelta(seconds=1)
    reopened.reclaim_expired(now=reclaim_time, retry_at=retry_time)
    reopened.make_ready(ready.id, now=retry_time)
    reclaimed_item = reopened.get(ready.id)
    reclaimed = dispatcher(reopened).tick(now=retry_time, work_item_id=reclaimed_item.id).claim
    assert reclaimed is not None
    assert not reopened.preparation_resume_consumed(intent, reclaimed)


@pytest.mark.parametrize("waiting", [(AgentRole.QA, "STATIC_QA")], indirect=True)
@pytest.mark.parametrize(
    "case",
    [
        "ready",
        "missing_marker",
        "native_started",
        "native_finished",
        "invocation_started",
        "wrong_decision",
        "old_lease_active",
        "skipped_generation",
        "second_reclaim",
        "knowledge_gap_intermediate",
        "knowledge_gap_unresolved",
        "knowledge_gap_native_started",
        "knowledge_gap_role_started",
        "knowledge_gap_stale_preflight_wait",
        "knowledge_gap_then_engineering_wait",
        "wrong_claim",
    ],
)
def test_static_qa_reclaimed_ready_no_start_preparation_uses_consumed_decision(
    waiting: WaitingFixture, tmp_path: Path, case: str
) -> None:
    resolution = _static_qa_resolution(waiting)
    ready = waiting.queue.resolve_wait(resolution)
    first = (
        dispatcher(waiting.queue)
        .tick(now=waiting.now + timedelta(seconds=8), work_item_id=ready.id)
        .claim
    )
    assert first is not None
    task = waiting.repository.get(first.work_item.task_id)
    request = AgentRequest.model_validate(
        {
            **_coder_request().to_wire(),
            "task_id": task.id,
            "role": AgentRole.QA.value,
            "source_revision": SOURCE,
            "output_schema": "schemas/qa-report.schema.json",
            "run_id": "run_static_qa_reclaimed_ready",
            "context_manifest_id": "ctx_" + "e" * 64,
        }
    )
    intent = VerifierPreparationIntent.create(
        work_item_id=first.work_item.id,
        lease_id=first.lease.id,
        task_id=task.id,
        task_snapshot_sha256=digest(task.to_wire()),
        checkpoint_sequence=first.work_item.checkpoint_sequence,
        dispatch_sequence=first.work_item.dispatch_sequence,
        request=request,
        request_sha256=digest(request.to_wire()),
        started_at=first.claimed_at,
    )
    observation = VerifierPreparationObservation(native_execution_state="NOT_STARTED")
    marker = VerifierPreparationCheckpoint.create(
        work_item_id=first.work_item.id,
        lease_id=first.lease.id,
        task_id=task.id,
        task_snapshot_sha256=digest(task.to_wire()),
        checkpoint_sequence=first.work_item.checkpoint_sequence,
        dispatch_sequence=first.work_item.dispatch_sequence,
        wait_dispatch_sequence=first.work_item.dispatch_sequence,
        wait_lease_id=first.lease.id,
        intent_sha256=intent.intent_sha256,
        source_revision=request.source_revision,
        run_id=request.run_id,
        role=request.role,
        attempt=request.attempt,
        context_manifest_id=request.context_manifest_id,
        request_sha256=digest(request.to_wire()),
        request=request,
        result="READY",
        observation=observation,
        checked_at=first.claimed_at,
    )
    records = KnowledgeRecordStore(tmp_path / "preflight")
    records.put("verifier-preparation-intents", "first", intent)
    if case != "missing_marker":
        records.put("verifier-preparations", marker.checkpoint_sha256, marker)
    invocations = KnowledgeRecordStore(tmp_path / "invocations")
    if case == "invocation_started":
        start = DeliveryInvocationStart(
            work_item_id=first.work_item.id,
            checkpoint_sequence=first.work_item.checkpoint_sequence,
            request=request,
            lease_id=first.lease.id,
            started_at=first.claimed_at,
            start_sha256="0" * 64,
        )
        start = start.model_copy(
            update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
        )
        invocations.put("invocation-starts", first.work_item.id, start)
    waiting.queue.start(
        ready.id,
        lease_id=first.lease.id,
        owner_token=TOKEN,
        now=waiting.now + timedelta(seconds=9),
    )
    retry_at = first.lease.expires_at + timedelta(seconds=1)
    waiting.queue.reclaim_expired(now=first.lease.expires_at, retry_at=retry_at)
    second = (
        dispatcher(waiting.queue)
        .tick(now=retry_at + timedelta(seconds=1), work_item_id=ready.id)
        .claim
    )
    assert second is not None
    assert waiting.queue.static_qa_resolution_for_claim(second) == resolution
    assert not waiting.queue.preparation_resume_consumed(intent, second)
    if case == "old_lease_active":
        with closing(open_mysql_connection(waiting.dsn)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE work_queue_claims SET state='ACTIVE' WHERE lease_id=%s",
                    (first.lease.id,),
                )
            connection.commit()
    if case in {"skipped_generation", "second_reclaim"}:
        if case == "second_reclaim":
            later_request = request.model_copy(
                update={
                    "run_id": "run_static_qa_second_reclaim",
                    "context_manifest_id": "ctx_" + "c" * 64,
                }
            )
            later_intent = VerifierPreparationIntent.create(
                work_item_id=second.work_item.id,
                lease_id=second.lease.id,
                task_id=task.id,
                task_snapshot_sha256=digest(task.to_wire()),
                checkpoint_sequence=second.work_item.checkpoint_sequence,
                dispatch_sequence=second.work_item.dispatch_sequence,
                request=later_request,
                request_sha256=digest(later_request.to_wire()),
                started_at=second.claimed_at,
            )
            later_marker = VerifierPreparationCheckpoint.create(
                work_item_id=second.work_item.id,
                lease_id=second.lease.id,
                task_id=task.id,
                task_snapshot_sha256=digest(task.to_wire()),
                checkpoint_sequence=second.work_item.checkpoint_sequence,
                dispatch_sequence=second.work_item.dispatch_sequence,
                wait_dispatch_sequence=second.work_item.dispatch_sequence,
                wait_lease_id=second.lease.id,
                intent_sha256=later_intent.intent_sha256,
                source_revision=later_request.source_revision,
                run_id=later_request.run_id,
                role=later_request.role,
                attempt=later_request.attempt,
                context_manifest_id=later_request.context_manifest_id,
                request_sha256=digest(later_request.to_wire()),
                request=later_request,
                result="READY",
                observation=observation,
                checked_at=second.claimed_at,
            )
            records.put("verifier-preparation-intents", "second", later_intent)
            records.put("verifier-preparations", later_marker.checkpoint_sha256, later_marker)
            intent = later_intent
        next_retry = second.lease.expires_at + timedelta(seconds=1)
        waiting.queue.reclaim_expired(now=second.lease.expires_at, retry_at=next_retry)
        third = (
            dispatcher(waiting.queue)
            .tick(now=next_retry + timedelta(seconds=1), work_item_id=ready.id)
            .claim
        )
        assert third is not None
        second = third
    if case in {
        "knowledge_gap_intermediate",
        "knowledge_gap_unresolved",
        "knowledge_gap_native_started",
        "knowledge_gap_role_started",
        "knowledge_gap_stale_preflight_wait",
        "knowledge_gap_then_engineering_wait",
    }:
        # A later claim may stop at the knowledge gate before verifier preparation.
        # Its exact gap and approved resolution create another generation without
        # a verifier intent, while preserving the frozen Task and static decision.
        knowledge = KnowledgeRecordStore(tmp_path / "knowledge")
        knowledge_binding = bound(second)
        knowledge_route = route(knowledge, knowledge_binding)
        QueueKnowledgeWaitPort(
            waiting.queue,
            claim=second,
            owner_token=TOKEN,
            binding=knowledge_binding,
            records=knowledge,
            clock=lambda: second.claimed_at + timedelta(seconds=1),
        ).wait(knowledge_binding, knowledge_route)
        source = KnowledgeResolutionSource(
            uri="test://verified-static-qa-scope",
            content="Only proof-bound missing-entry FAIL is in scope; full checks remain NOT_RUN.",
            sha256=text_digest(
                "Only proof-bound missing-entry FAIL is in scope; full checks remain NOT_RUN."
            ),
        )
        knowledge_resolution = KnowledgeResolution(
            gap_id=knowledge_route.gap_id,
            previous_run_id=knowledge_binding.run_id,
            answer="Do proof-bound static QA only; real MySQL and browser checks remain NOT_RUN.",
            sources=(source,),
            approval_reference="test://human-approved-exact-gap",
            approved_by="human:local-console",
            resolution_id="0" * 64,
        )
        knowledge_resolution = knowledge_resolution.model_copy(
            update={
                "resolution_id": digest(
                    knowledge_resolution.model_dump(mode="json", exclude={"resolution_id"})
                )
            }
        )

        class _HumanApproval:
            def require_approval(self, candidate: KnowledgeResolution) -> None:
                assert candidate == knowledge_resolution

        if case != "knowledge_gap_unresolved":
            KnowledgeGapService(knowledge).resolve(knowledge_resolution, _HumanApproval())
        assert waiting.queue.get(ready.id).wait_reason == (
            f"KNOWLEDGE_GAP:{knowledge_route.gap_id}:{knowledge_route.routing_sha256}"
        )
        resumed = waiting.queue.make_ready(ready.id, now=second.claimed_at + timedelta(seconds=2))
        third = (
            dispatcher(waiting.queue)
            .tick(now=second.claimed_at + timedelta(seconds=3), work_item_id=resumed.id)
            .claim
        )
        assert third is not None
        # The existing K1 also persisted a failed preflight marker against the
        # old intent. It cannot replace the original READY/NOT_STARTED receipt.
        later_wait = VerifierPreparationCheckpoint.create(
            work_item_id=third.work_item.id,
            lease_id=first.lease.id,
            task_id=task.id,
            task_snapshot_sha256=digest(task.to_wire()),
            checkpoint_sequence=third.work_item.checkpoint_sequence,
            dispatch_sequence=first.work_item.dispatch_sequence,
            wait_dispatch_sequence=third.work_item.dispatch_sequence,
            wait_lease_id=third.lease.id,
            intent_sha256=intent.intent_sha256,
            source_revision=request.source_revision,
            run_id=request.run_id,
            role=request.role,
            attempt=request.attempt,
            context_manifest_id=request.context_manifest_id,
            request_sha256=digest(request.to_wire()),
            request=request,
            result="WAIT",
            observation=observation,
            failure_reason=NativeVerificationWaitReason.FACTS_CHANGED,
            checked_at=third.claimed_at,
        )
        if case in {"knowledge_gap_stale_preflight_wait", "knowledge_gap_then_engineering_wait"}:
            records.put("verifier-preparations", later_wait.checkpoint_sha256, later_wait)
            assert len(records.list("verifier-preparations", VerifierPreparationCheckpoint)) == 2
        if case == "knowledge_gap_role_started":
            start = DeliveryInvocationStart(
                work_item_id=ready.id,
                checkpoint_sequence=first.work_item.checkpoint_sequence,
                request=request,
                lease_id=third.lease.id,
                started_at=third.claimed_at,
                start_sha256="0" * 64,
            )
            invocations.put(
                "invocation-starts",
                ready.id,
                start.model_copy(
                    update={
                        "start_sha256": digest(
                            start.model_dump(mode="json", exclude={"start_sha256"})
                        )
                    }
                ),
            )
        second = third
        if case == "knowledge_gap_then_engineering_wait":
            # The production K1 wait itself became durable after the stale intent
            # was observed. Model the queue state after a trusted, disposition-bound
            # resume signal; the public engineering decision is tested separately.
            # A fresh claim must retain this failed preparation receipt.
            disposition = decide_delivery_disposition(
                waiting.disposition.facts.model_copy(
                    update={
                        "classification": "ENGINEERING_AUTHORIZATION",
                        "evidence_ids": ("verifier-preparation://" + later_wait.checkpoint_sha256,),
                    }
                )
            )
            waiting.queue.wait(
                ready.id,
                lease_id=third.lease.id,
                owner_token=TOKEN,
                status=WorkItemStatus.WAITING_DEPENDENCY,
                reason=disposition.reason,
                disposition=disposition,
                now=third.claimed_at + timedelta(seconds=1),
            )
            resumed_again = waiting.queue.make_ready(
                ready.id,
                now=third.claimed_at + timedelta(seconds=2),
                expected_disposition_sha256=disposition.disposition_sha256,
            )
            fourth = (
                dispatcher(waiting.queue)
                .tick(now=third.claimed_at + timedelta(seconds=3), work_item_id=resumed_again.id)
                .claim
            )
            assert fourth is not None
            # This queue-only resume is intentionally not an engineering
            # resolution; a stale FACTS_CHANGED marker must still fail closed.
            with pytest.raises(QueueCorruption):
                waiting.queue.static_qa_resolution_for_claim(
                    fourth,
                    knowledge_records=knowledge,
                    preflight_records=records,
                    invocation_records=invocations,
                    observe_verifier=lambda *_: observation,
                )
            return
    if case == "wrong_claim":
        second = second.model_copy(update={"worker_id": "worker_wrong_static_reclaim"})
    if case == "wrong_decision":
        with closing(open_mysql_connection(waiting.dsn)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE work_queue_events SET payload_json=JSON_SET(payload_json, "
                    "'$.detail.resolution.resolution_kind', 'RESUME_UNINVOKED') "
                    "WHERE work_item_id=%s AND event_type='WAIT_RESOLVED'",
                    (ready.id,),
                )
            connection.commit()
        with pytest.raises(QueueCorruption):
            static_qa_preparation_reclaimed(
                waiting.queue,
                waiting.dsn,
                records,
                invocations,
                lambda *_: observation,
                intent,
                second,
            )
        return
    observed = observation
    if case in {"native_started", "knowledge_gap_native_started"}:
        observed = VerifierPreparationObservation(
            native_execution_state="UNCERTAIN", native_started_sha256="f" * 64
        )
    elif case == "native_finished":
        observed = VerifierPreparationObservation(
            native_execution_state="FINISHED",
            native_binding_plan_sha256="f" * 64,
            native_started_sha256="e" * 64,
            native_finished_sha256="d" * 64,
        )
    if case == "wrong_claim":
        with pytest.raises(QueueConflict):
            static_qa_preparation_reclaimed(
                waiting.queue,
                waiting.dsn,
                records,
                invocations,
                lambda *_: observed,
                intent,
                second,
            )
        return
    knowledge_records = (
        knowledge
        if case
        in {
            "knowledge_gap_intermediate",
            "knowledge_gap_unresolved",
            "knowledge_gap_native_started",
            "knowledge_gap_role_started",
            "knowledge_gap_stale_preflight_wait",
            "knowledge_gap_then_engineering_wait",
        }
        else None
    )
    should_recover = case in {
        "ready",
        "knowledge_gap_intermediate",
    }
    if case == "knowledge_gap_intermediate":
        assert (
            waiting.queue.static_qa_resolution_for_claim(
                second,
                knowledge_records=knowledge,
                preflight_records=records,
                invocation_records=invocations,
                observe_verifier=lambda *_: observation,
            )
            == resolution
        )
    if case == "second_reclaim":
        # A second prepared generation is outside the one consumed static
        # decision. The exact lineage reader must fail closed.
        with pytest.raises(QueueCorruption):
            static_qa_preparation_reclaimed(
                waiting.queue,
                waiting.dsn,
                records,
                invocations,
                lambda *_: observation,
                intent,
                second,
            )
        assert waiting.resolution_events() == 1
        return
    if case in {
        "knowledge_gap_native_started",
        "knowledge_gap_role_started",
        "knowledge_gap_stale_preflight_wait",
    }:
        with pytest.raises(QueueCorruption):
            static_qa_preparation_reclaimed(
                waiting.queue,
                waiting.dsn,
                records,
                invocations,
                lambda *_: observed,
                intent,
                second,
                knowledge_records=knowledge_records,
            )
        assert waiting.resolution_events() == 1
        return
    recovered = static_qa_preparation_reclaimed(
        waiting.queue,
        waiting.dsn,
        records,
        invocations,
        lambda observed_request, lease_id: observed,
        intent,
        second,
        knowledge_records=knowledge_records,
    )
    assert recovered is should_recover
    if should_recover:
        next_request = request.model_copy(
            update={
                "run_id": "run_static_qa_reclaimed_next",
                "context_manifest_id": "ctx_" + "d" * 64,
            }
        )
        guard = _Guard(second)
        guard.lease = SimpleNamespace(claim=second)
        gate = PreflightInvocationControl(
            delegate=DurableInvocationControl(invocations, cast(WorkerExecutionGuard, guard)),
            guard=cast(WorkerExecutionGuard, guard),
            task_reader=lambda: task,
            inspect=lambda *_: None,
            records=records,
            failure_control=cast(
                WorkerDeliveryFailureControl,
                SimpleNamespace(wait=lambda *_args, **_kwargs: None),
            ),
            prepare_verifier=lambda *_: None,
            observe_verifier=lambda *_: observation,
            resumed_preparation=waiting.queue.preparation_resume_consumed,
            reclaimed_static_preparation=lambda prior, current: static_qa_preparation_reclaimed(
                waiting.queue,
                waiting.dsn,
                records,
                invocations,
                lambda *_: observation,
                prior,
                current,
                knowledge_records=knowledge_records,
            ),
            prepare_input=lambda *_: None,
        )
        assert gate.prepare(next_request) == next_request
        starts = invocations.list("invocation-starts", DeliveryInvocationStart)
        assert len(starts) == 1 and starts[0].request == next_request
        assert len(records.list("verifier-preparation-intents", VerifierPreparationIntent)) == 2
        assert any(
            marker.lease_id == second.lease.id and marker.result == "READY"
            for marker in records.list("verifier-preparations", VerifierPreparationCheckpoint)
        )
    assert waiting.resolution_events() == 1
    assert waiting.repository.get(task.id) == task


def test_restart_replays_exact_resolution_once_and_rejects_a_different_proof(
    waiting: WaitingFixture,
) -> None:
    resolution = waiting.resolution()
    next_item = waiting.queue.resolve_wait(resolution)
    reopened = MySqlRoleQueue(waiting.dsn)
    assert reopened.resolve_wait(resolution) == next_item
    with pytest.raises(QueueConflict, match="current wait"):
        reopened.resolve_wait(reseal(resolution, proof_sha256="f" * 64))
    assert waiting.repository.get(resolution.task_id).attempts == 2
    assert waiting.resolution_events() == 1


@pytest.mark.parametrize(
    "field",
    [
        "expected_source_revision",
        "expected_task_intent_sha256",
        "expected_disposition_sha256",
        "task_snapshot_sha256",
        "step_sha256",
    ],
)
def test_stale_source_scope_disposition_snapshot_or_step_keeps_the_wait(
    waiting: WaitingFixture,
    field: str,
) -> None:
    resolution = reseal(waiting.resolution(), **{field: "f" * 64})
    before = waiting.repository.get(resolution.task_id)
    with pytest.raises(QueueConflict):
        waiting.queue.resolve_wait(resolution)
    assert waiting.repository.get(resolution.task_id) == before
    assert waiting.queue.get(resolution.work_item_id).status is WorkItemStatus.WAITING_HUMAN
    assert waiting.resolution_events() == 0


def test_result_replay_cannot_replace_the_original_real_claim_identity(
    waiting: WaitingFixture,
) -> None:
    resolution = waiting.resolution(DeliveryResolutionKind.REPLAY_RECORDED_RESULT)
    assert resolution.original_authority is not None
    original = resolution.original_authority
    changed = original.model_copy(
        update={
            "assignment": original.assignment.model_copy(
                update={"agent_id": "agent_different_001"}
            ),
            "lease": original.lease.model_copy(update={"agent_id": "agent_different_001"}),
        }
    )
    with pytest.raises(QueueConflict, match="original frozen producer"):
        waiting.queue.resolve_wait(reseal(resolution, original_authority=changed.to_wire()))
    assert waiting.resolution_events() == 0
    assert waiting.repository.get(resolution.task_id).attempts == 1


def test_task_checkpoint_change_after_the_decision_cannot_be_consumed(
    waiting: WaitingFixture,
) -> None:
    resolution = waiting.resolution()
    waiting.repository.append_event(
        build_event(
            waiting.repository.get(resolution.task_id),
            TaskStatus.CONTINUE_REQUIRED,
            event_id="evt_wait_resolution_drift",
            reason="checkpoint advanced after investigation",
            source_revision=SOURCE,
            occurred_at=waiting.now + timedelta(seconds=4),
        )
    )
    with pytest.raises(QueueConflict, match="drifted"):
        waiting.queue.resolve_wait(resolution)
    assert waiting.queue.get(resolution.work_item_id).status is WorkItemStatus.WAITING_HUMAN
    assert waiting.repository.get(resolution.task_id).attempts == 1
    assert waiting.resolution_events() == 0
