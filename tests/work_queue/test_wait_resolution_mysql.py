"""Isolated transactional engineering decisions; no providers or production facts."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure, DeliveryRetryPolicy
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.verifier_preparation import VerifierPreparationIntent
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
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueConflict
from tests.agents.test_openai_compatible import _coder_request
from tests.domain.factories import make_implementation_artifact, make_qa_artifact, make_task
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
    role = getattr(request, "param", AgentRole.CODER)
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
        queue = MySqlRoleQueue(dsn, clock=lambda: now + timedelta(seconds=5))
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
        if role is AgentRole.QA:
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
                classification="EXECUTION_UNCERTAIN",
                source_revision=SOURCE,
                task_intent_sha256=task_intent_sha256(task),
                checkpoint_sequence=revision,
                budget_available=True,
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
        yield WaitingFixture(dsn, repository, queue, step, claim, disposition, now)


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
