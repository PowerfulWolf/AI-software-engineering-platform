"""Real SQL fences consume trusted workspace-refusal decisions exactly once."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ai_software_engineer.domain import AgentRole, RiskTier, Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.artifact import CoderProgressArtifact
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    RejectedWorkspaceAdmissionEvidence,
)
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.work_queue.ports import QueueError
from tests.work_queue.test_rejected_workspace_admission_contract import evidence_wire
from tests.work_queue.test_wait_resolution_mysql import WaitingFixture, reseal, waiting
from tests.work_queue.test_worker_mysql import dispatcher

if TYPE_CHECKING:
    from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
    from ai_software_engineer.work_queue.models import QueueClaim
    from ai_software_engineer.work_queue.worker import WorkerExecutionGuard, WorkerLease
    from tests.manager.test_rejected_workspace_admission import _Fixture

__all__ = ["waiting"]
pytestmark = pytest.mark.mysql


def resolution(waiting: WaitingFixture) -> DeliveryResolution:
    original = waiting.resolution(DeliveryResolutionKind.RESUME_UNINVOKED)
    claim = waiting.queue.original_claim(waiting.claim.lease.id)
    task = waiting.repository.get(original.task_id)
    assert task.engineering_policy is not None
    evidence = RejectedWorkspaceAdmissionEvidence.model_validate(
        {
            **evidence_wire(),
            "scope": task.engineering_policy.scope.to_wire(),
            "requirement_id": task.id,
            "task_id": task.id,
            "work_item_id": original.work_item_id,
            "checkpoint_sequence": original.expected_checkpoint_sequence,
            "attempt": task.attempts,
            "dispatch_sequence": claim.work_item.dispatch_sequence,
            "lease_id": claim.lease.id,
            "claim_sha256": claim_identity_sha256(claim),
            "source_revision": original.expected_source_revision,
        }
    )
    evidence = evidence.model_copy(update={"observation_sha256": evidence.recompute_sha256()})
    return reseal(
        original,
        resolution_kind=DeliveryResolutionKind.RETRY_REJECTED_WORKSPACE_ADMISSION,
        rejected_workspace_admission=evidence.to_wire(),
    )


@pytest.mark.parametrize("waiting", [(AgentRole.CODER, "NONTRANSIENT_INFRA")], indirect=True)
def test_workspace_refusal_consumes_one_ordinary_work_and_replay_does_not_consume_twice(
    waiting: WaitingFixture,
) -> None:
    before = waiting.repository.get(waiting.step.boundary.task_id)
    decision = resolution(waiting)
    old = waiting.queue.get(waiting.step.work_item.id)
    accepted = waiting.queue.accepted(before.id)
    item = waiting.queue.resolve_wait(decision)
    assert waiting.queue.resolve_wait(decision) == item
    after = waiting.repository.get(before.id)
    assert after.status is TaskStatus.IMPLEMENTING and after.base_ref == before.base_ref
    assert after.attempts == before.attempts + 1 and after.work_attempt == before.work_attempt + 1
    assert after.retry_failures == before.retry_failures and not after.retry_failures
    assert item.id != old.id and item.parent_work_item_id == old.id
    assert waiting.queue.get(old.id).status is WorkItemStatus.CLOSED
    assert waiting.queue.accepted(before.id) == accepted and waiting.resolution_events() == 1
    tick = dispatcher(waiting.queue).tick(
        now=waiting.now + timedelta(seconds=6), work_item_id=item.id
    )
    new_claim = tick.claim
    assert new_claim is not None
    assert (
        new_claim.lease.id != waiting.claim.lease.id
        and new_claim.assignment.id != waiting.claim.assignment.id
    )
    assert new_claim.work_item.attempt == after.attempts


@pytest.mark.parametrize("waiting", [(AgentRole.CODER, "NONTRANSIENT_INFRA")], indirect=True)
@pytest.mark.parametrize("mutation", ["claim", "lease", "dispatch", "attempt", "scope"])
def test_workspace_refusal_changed_claim_identity_cannot_create_new_work(
    waiting: WaitingFixture, mutation: str
) -> None:
    before = waiting.repository.get(waiting.step.boundary.task_id)
    decision = resolution(waiting)
    evidence = decision.rejected_workspace_admission
    assert evidence is not None
    wire = evidence.to_wire()
    if mutation == "claim":
        wire["claim_sha256"] = "a" * 64
    elif mutation == "lease":
        wire["lease_id"] = "lease_nonexistent"
    elif mutation == "dispatch":
        wire["dispatch_sequence"] = evidence.dispatch_sequence + 1
    elif mutation == "attempt":
        wire["attempt"] = evidence.attempt + 1
    else:
        wire["scope"] = {**evidence.scope.to_wire(), "repository_id": "repository_wrong"}
    changed = RejectedWorkspaceAdmissionEvidence.model_validate(wire)
    changed = changed.model_copy(update={"observation_sha256": changed.recompute_sha256()})
    decision = reseal(decision, rejected_workspace_admission=changed.to_wire())
    with pytest.raises(QueueError):
        waiting.queue.resolve_wait(decision)
    assert waiting.repository.get(before.id) == before and waiting.resolution_events() == 0


@pytest.mark.parametrize(
    "waiting",
    [(AgentRole.QA, "NONTRANSIENT_INFRA"), (AgentRole.REVIEWER, "NONTRANSIENT_INFRA")],
    indirect=True,
)
def test_workspace_refusal_does_not_authorize_verifier_recovery(waiting: WaitingFixture) -> None:
    before = waiting.repository.get(waiting.step.boundary.task_id)
    decision = resolution(waiting)
    with pytest.raises(QueueError):
        waiting.queue.resolve_wait(decision)
    assert waiting.repository.get(before.id) == before and waiting.resolution_events() == 0


def test_real_adapter_refusal_public_declaration_and_resolution_create_new_claim_and_context(
    tmp_path: Path,
) -> None:
    """Real Git/baseline/adapter refusal + public recovery + real MySQL ownership."""
    import os
    from datetime import UTC, datetime

    from ai_software_engineer.artifacts import FileArtifactStore, artifact_digest
    from ai_software_engineer.context import FileContextStore
    from ai_software_engineer.context.execution_baseline import (
        ExecutionBaselineContext,
        PreservedWorktreeBaselineContext,
    )
    from ai_software_engineer.domain.continuation import task_intent_sha256
    from ai_software_engineer.domain.delivery_disposition import (
        DeliveryFailureFacts,
        decide_delivery_disposition,
    )
    from ai_software_engineer.domain.delivery_resolution import (
        HandleDeliveryWait,
        InspectDeliveryWait,
        ResolveDeliveryWait,
    )
    from ai_software_engineer.domain.engineering_authority import (
        EngineeringScope,
        LocalOperatorPrincipal,
    )
    from ai_software_engineer.manager.baseline_admission import BaselineInitialWorkspaceAdmission
    from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
    from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
    from ai_software_engineer.manager.rejected_workspace_admission import (
        rejected_workspace_admission_evidence,
    )
    from ai_software_engineer.orchestration.state_machine import build_event
    from ai_software_engineer.orchestration.steps import RoleRunBoundary
    from ai_software_engineer.store import MySqlTaskRepository
    from ai_software_engineer.work_queue.baseline import (
        TABLE,
        BaselineQueueConsumption,
        _consumption_cursor,
    )
    from ai_software_engineer.work_queue.execution_store import (
        MySqlRoleQueue,
        QueuedRoleStep,
        RoleQueueAdmission,
        _put,
        record_digest,
    )
    from ai_software_engineer.work_queue.models import (
        QueueArtifactReceipt,
        QueuedWorkItem,
    )
    from ai_software_engineer.work_queue.worker import WorkerExecutionGuard, WorkerLease
    from tests.git.test_worktree import _git
    from tests.manager.test_rejected_workspace_admission import _context, _fixture
    from tests.work_queue.test_worker_mysql import ALLOCATION_SHA, TOKEN, claim_step

    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("isolated MySQL is not configured")
    with MySqlTaskRepository(dsn) as repository:
        queue = MySqlRoleQueue(dsn)

        def claim_factory(
            task: Task, scope: EngineeringScope, attempt: int, at: datetime
        ) -> QueueClaim:
            del at
            if attempt == 1:
                repository.create(task.model_copy(update={"status": TaskStatus.NEW, "attempts": 0}))
                repository.record_attempt(task.id, 1)
                for index, status in enumerate((TaskStatus.PLANNING, TaskStatus.IMPLEMENTING)):
                    repository.append_event(
                        build_event(
                            repository.get(task.id),
                            status,
                            event_id=f"evt_admission_public_{index}",
                            reason="public workspace refusal recovery fixture",
                            source_revision=task.base_ref,
                            occurred_at=datetime.now(UTC),
                        )
                    )
            else:
                repository.record_attempt(task.id, attempt)
            item = QueuedWorkItem(
                id="work_baseline_wait" if attempt == 1 else f"work_admission_sql_{attempt}",
                task_id=task.id,
                repository_id=scope.repository_id,
                role=AgentRole.CODER,
                attempt=attempt,
                checkpoint_sequence=repository.current_revision(task.id),
                repository_scopes=(task.repository,),
                status=WorkItemStatus.READY,
                priority=500,
                risk=RiskTier.NORMAL,
                required_capabilities=("delivery",),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                parent_work_item_id="work_baseline_wait" if attempt > 1 else None,
            )
            source = _git(
                tmp_path / "worktrees" / task.id / "coder-attempt-01", "rev-parse", "HEAD"
            )
            step = QueuedRoleStep(
                work_item=item,
                allocation_sha256=ALLOCATION_SHA,
                boundary=RoleRunBoundary(
                    task.id, AgentRole.CODER, attempt, item.checkpoint_sequence, source
                ),
            )
            queue.admit(
                RoleQueueAdmission(
                    task_id=task.id,
                    repository_id=scope.repository_id,
                    allocation_sha256=ALLOCATION_SHA,
                    legacy_artifacts=tuple(
                        QueueArtifactReceipt(
                            artifact_id=artifact.artifact_id,
                            sha256=artifact_digest(artifact),
                        )
                        for artifact in FileArtifactStore(
                            tmp_path / "accepted-artifacts", read_only=True
                        ).list_for_task(task.id)
                        if not isinstance(artifact, CoderProgressArtifact)
                    ),
                ),
                step,
            )
            return claim_step(queue, step)

        def publish_progress(
            claim: QueueClaim, progress: CoderProgressArtifact, artifacts: FileArtifactStore
        ) -> None:
            queue.accept_artifact(claim, TOKEN, artifacts, progress)
            for index, status in enumerate(
                (TaskStatus.CONTINUE_REQUIRED, TaskStatus.QUEUED, TaskStatus.IMPLEMENTING)
            ):
                if status is TaskStatus.IMPLEMENTING:
                    repository.record_attempt(claim.work_item.task_id, 2)
                repository.append_event(
                    build_event(
                        repository.get(claim.work_item.task_id),
                        status,
                        event_id=f"evt_admission_progress_{index}",
                        reason="historical accepted progress continuation",
                        source_revision=progress.source_revision,
                        artifact_ids=(progress.artifact_id,),
                        attempt=2 if status is TaskStatus.IMPLEMENTING else 1,
                        occurred_at=datetime.now(UTC),
                    )
                )
            queue.finish(claim, TOKEN, next_step=None, now=datetime.now(UTC))

        f = _fixture(
            tmp_path,
            seal_declaration=False,
            claim_factory=claim_factory,
            progress_published=publish_progress,
        )
        # The historical fixture's baseline was already sealed by its trusted
        # service. Seed its typed immutable SQL history so the real queue can
        # authenticate descendants through the exact original step.
        baseline_plan = f.preserved.source.service.store.plan(f.preserved.binding.plan_sha256)
        baseline_record = BaselineQueueConsumption(
            task_id=f.task.id,
            work_item_id=baseline_plan.facts.work_item_id,
            next_work_item_id=baseline_plan.facts.work_item_id,
            prior_step_sha256=record_digest(queue.original_step(baseline_plan.facts.work_item_id)),
            plan=baseline_plan,
            binding=f.preserved.binding,
        )
        with _consumption_cursor(queue, None) as cursor:
            _put(cursor, TABLE, f.preserved.binding.binding_sha256, f.task.id, baseline_record)
        (accepted_progress,) = queue.accepted(f.task.id)
        assert f.provider_calls == 0 and accepted_progress.receipt.sha256 == artifact_digest(
            f.artifacts.get(accepted_progress.receipt.artifact_id)
        )
        task = repository.get(f.task.id)
        disposition = decide_delivery_disposition(
            DeliveryFailureFacts(
                task_id=task.id,
                work_item_id=f.item.id,
                role=AgentRole.CODER,
                classification="NONTRANSIENT_INFRA",
                source_revision=f.request.source_revision,
                task_intent_sha256=task_intent_sha256(task),
                checkpoint_sequence=f.item.checkpoint_sequence,
                budget_available=True,
            )
        )
        queue.wait(
            f.item.id,
            lease_id=f.claim.lease.id,
            owner_token=TOKEN,
            status=WorkItemStatus.WAITING_DEPENDENCY,
            reason=disposition.reason,
            disposition=disposition,
            now=datetime.now(UTC),
        )

        def consume(decision: DeliveryResolution) -> None:
            queue.resolve_wait(decision)

        entry = DeliveryWaitService(
            repository=repository,
            queue=queue,
            scope=f.scope,
            sidecar_state=f.state,
            git=f.preserved.source.manager,
            principal=LocalOperatorPrincipal.trusted_local(),
            consume=consume,
            artifacts=f.artifacts,
            knowledge_requirement_id=f.declaration.requirement_id,
        )
        command = InspectDeliveryWait(
            work_item_id=f.item.id,
            expected_disposition_sha256=disposition.disposition_sha256,
            expected_task_intent_sha256=disposition.facts.task_intent_sha256,
            expected_source_revision=f.request.source_revision,
            expected_checkpoint_sequence=f.item.checkpoint_sequence,
        )
        old_records = {path: path.read_bytes() for path in (f.state / "invocations").glob("*.json")}
        handling = entry.handle(
            HandleDeliveryWait.model_validate(
                {
                    **command.to_wire(),
                    "workspace_admission_adapter_contract": f.declaration.to_wire(),
                }
            )
        )
        rejected_workspace_admission_evidence(
            task=task,
            item=queue.get(f.item.id),
            step=queue.step(f.item.id),
            scope=f.scope,
            requirement_id=f.declaration.requirement_id,
            state=f.state,
            route_root=f.route_root,
            queue=queue,
            artifacts=f.artifacts,
            git=f.preserved.source.manager,
        )
        assert handling.status == "NEEDS_AUTHORIZATION" and not handling.investigation.missing, (
            handling.status,
            handling.investigation.missing,
        )
        assert handling.investigation.permitted_resolutions == (
            DeliveryResolutionKind.RETRY_REJECTED_WORKSPACE_ADMISSION,
        )
        assert handling.investigation.process_stop_sha256 is None
        assert entry.records.get("wait-handlings", handling.record_key, type(handling)) == handling
        decision = entry.resolve(
            ResolveDeliveryWait.model_validate(
                {
                    **command.to_wire(),
                    "resolution_kind": "RETRY_REJECTED_WORKSPACE_ADMISSION",
                    "proof_sha256": handling.investigation.proof_sha256,
                    "submitted_at": datetime.now(UTC),
                }
            )
        )
        successor = queue.resolve_wait(decision)
        assert queue.resolve_wait(decision) == successor
        replayed = entry.handle(HandleDeliveryWait.model_validate(command.to_wire()))
        assert replayed.status == "RESOLVED" and replayed.resolution == decision
        assert entry.records.get("wait-handlings", handling.record_key, type(handling)) == handling
        after = repository.get(task.id)
        assert after.attempts == task.attempts + 1 and after.work_attempt == task.work_attempt + 1
        assert (
            after.status is task.status
            and after.base_ref == task.base_ref
            and after.retry_failures == task.retry_failures
        )
        next_claim = claim_step(queue, queue.step(successor.id))
        assert (
            next_claim.lease.id != f.claim.lease.id
            and next_claim.assignment.id != f.claim.assignment.id
        )
        complete = ExecutionBaselineContext.from_required_context(
            f.preserved.binding,
            f.preserved.source.service.store.required_context(f.preserved.binding),
        )
        context = FileContextStore(f.state.parent / "contexts").put(
            _context(
                after,
                next_claim,
                f.request.source_revision,
                f.request.permissions,
                baseline=PreservedWorktreeBaselineContext.from_complete(complete),
            )
        )
        request = f.request.model_copy(
            update={
                "attempt": after.attempts,
                "run_id": "run_public_workspace_retry",
                "context_manifest_id": context.context_id,
            }
        )
        assert (
            request.run_id != f.request.run_id
            and request.context_manifest_id != f.request.context_manifest_id
        )
        lease = WorkerLease(queue, next_claim, TOKEN)
        guard = WorkerExecutionGuard()
        guard.lease = lease
        lease.start()
        try:
            BaselineInitialWorkspaceAdmission(
                inputs=StoredCoderExecutionInputResolver(f.preserved.source.service.store),
                task_reader=lambda: repository.get(task.id),
                artifacts=f.artifacts,
                git=f.preserved.source.manager,
                guard=guard,
            ).authorize(request, f.preserved.source.worktree.path)
            _deliver_refusal_successor(tmp_path, dsn, f, queue, next_claim, guard, lease)
        finally:
            lease.stop()
            guard.lease = None
        assert all(path.read_bytes() == before for path, before in old_records.items())
        assert f.provider_calls == 0


def _deliver_refusal_successor(
    tmp_path: Path,
    dsn: str,
    f: _Fixture,
    queue: MySqlRoleQueue,
    next_claim: QueueClaim,
    guard: WorkerExecutionGuard,
    lease: WorkerLease,
) -> None:
    """Resume this exact claimed SQL successor through independent checked roles."""
    import hashlib
    import json
    from datetime import UTC, datetime

    from ai_software_engineer.agents import AgentRequest
    from ai_software_engineer.agents.execution import bind_execution_guard
    from ai_software_engineer.context import FileContextStore
    from ai_software_engineer.domain import Artifact, Evidence, EvidenceType
    from ai_software_engineer.domain.artifact import (
        ImplementationReportArtifact,
        QaReportArtifact,
        QaTestRun,
        ReviewReportArtifact,
    )
    from ai_software_engineer.domain.enums import ChangeType, QaTestStatus
    from ai_software_engineer.execution import SubprocessCommandExecutor
    from ai_software_engineer.git import WorktreeSpec
    from ai_software_engineer.git.candidate_commit import (
        CandidateCommitRequest,
        GitCandidateCommitSkill,
    )
    from ai_software_engineer.knowledge.store import KnowledgeRecordStore
    from ai_software_engineer.manager.baseline_admission import BaselineInitialWorkspaceAdmission
    from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
    from ai_software_engineer.manager.production_backend import _terminal_delivery_result
    from ai_software_engineer.orchestration import FileRunContextBuilder, RetryDeliveryResult
    from ai_software_engineer.orchestration.steps import BoundedRunControl, RoleRunBoundary
    from ai_software_engineer.runtime import (
        RuntimeConfig,
        RuntimePaths,
        RuntimePersistence,
        RuntimeSession,
    )
    from ai_software_engineer.store import MySqlTaskRepository
    from ai_software_engineer.work_queue.execution_store import QueuedRoleStep
    from ai_software_engineer.work_queue.worker import (
        AcceptedArtifactStore,
        QueuedDeliverySupervisor,
        WorkerDeliveryFailureControl,
    )
    from tests.git.test_worktree import _git
    from tests.orchestration.test_runner import _definitions
    from tests.work_queue.test_rejected_knowledge_replacement_mysql import _claim_source
    from tests.work_queue.test_worker_mysql import ALLOCATION_SHA, ObservedAdapter, make_step

    inputs = StoredCoderExecutionInputResolver(f.preserved.source.service.store)
    sidecar = f.state.parent
    paths = RuntimePaths(
        database=str(sidecar / "unused.sqlite"),
        artifacts=str(sidecar / "artifacts"),
        contexts=str(sidecar / "contexts"),
        evaluation_events=str(sidecar / "evaluation"),
        handoffs=str(sidecar / "handoffs"),
        evidence=str(sidecar / "evidence"),
        runs=str(sidecar / "runs"),
    )
    artifacts = AcceptedArtifactStore(f.artifacts, queue, f.task.id, guard)
    expected_bodies = {
        "src/app.py": "VALUE = 2\nEXTRA = 3\n",
        "src/retained.py": "RETAINED = 3\n",
    }

    class IndependentAdapter(ObservedAdapter):
        def _artifact(self, request: AgentRequest) -> Artifact:
            artifact = super()._artifact(request)
            assert guard.lease is not None
            assert guard.lease.claim.assignment.agent_id == artifact.producer.agent_id
            if request.role is AgentRole.CODER:
                assert isinstance(artifact, ImplementationReportArtifact)
                assert request.execution_baseline_sha256 == f.preserved.binding.binding_sha256
                assert request.continuation_checkpoint_id == f.preserved.progress.artifact_id
                assert request.source_revision == f.request.source_revision
                assert request.attempt == next_claim.work_item.attempt
                assert request.run_id != f.request.run_id
                assert request.context_manifest_id != f.request.context_manifest_id
                worktree = f.preserved.source.worktree
                BaselineInitialWorkspaceAdmission(
                    inputs=inputs,
                    task_reader=lambda: queue_task(),
                    artifacts=artifacts,
                    git=f.preserved.source.manager,
                    guard=guard,
                ).authorize(request, worktree.path)
                for path, body in expected_bodies.items():
                    assert (worktree.path / path).read_text() == body
                committed = GitCandidateCommitSkill(worktree.path).finalize(
                    CandidateCommitRequest(
                        task_id=request.task_id,
                        source_revision=request.source_revision,
                        reported_paths=tuple(sorted(expected_bodies)),
                        permissions=request.permissions,
                    )
                )
                commit_path = tmp_path / f"candidate-{request.run_id}.json"
                commit_path.write_text(committed.model_dump_json())
                commit_evidence = Evidence(
                    evidence_id=f"ev_{request.run_id.removeprefix('run_')}",
                    type=EvidenceType.DIFF,
                    uri=commit_path.as_uri(),
                    description="Platform committed the exact two approved retained draft files.",
                    sha256=hashlib.sha256(commit_path.read_bytes()).hexdigest(),
                )
                return artifact.model_copy(
                    update={
                        "source_revision": committed.candidate_revision,
                        "evidence": (commit_evidence,),
                        "content": artifact.content.model_copy(
                            update={
                                "commit_sha": committed.candidate_revision,
                                "changed_files": tuple(
                                    artifact.content.changed_files[0].model_copy(
                                        update={
                                            "path": path,
                                            "change": ChangeType.MODIFIED
                                            if path == "src/app.py"
                                            else ChangeType.ADDED,
                                            "lines_added": 1,
                                            "lines_deleted": 0,
                                        }
                                    )
                                    for path in committed.changed_paths
                                ),
                                "acceptance_mapping": tuple(
                                    value.model_copy(
                                        update={
                                            "implementation": "Retained and committed the exact "
                                            "approved complete draft for independent checks.",
                                            "tests": (),
                                        }
                                    )
                                    for value in artifact.content.acceptance_mapping
                                ),
                                "tests_run": (),
                            }
                        ),
                    }
                )
            assert isinstance(artifact, (QaReportArtifact, ReviewReportArtifact))
            verifier = f.preserved.source.manager.create(
                WorktreeSpec(
                    task_id=request.task_id,
                    role=request.role,
                    attempt=request.attempt,
                    source_revision=request.source_revision,
                )
            )
            assert verifier.path != f.preserved.source.worktree.path
            assert _git(verifier.path, "rev-parse", "HEAD") == request.source_revision
            executor = SubprocessCommandExecutor(
                verifier.path, request.permissions, execution_guard=guard
            )
            observed = []
            qa_runs = []
            evidence_id = f"ev_{request.run_id.removeprefix('run_')}"
            for path, body in expected_bodies.items():
                command = ("git", "show", f"{request.source_revision}:{path}")
                result = executor.run(command, timeout_seconds=5)
                assert result.returncode == 0 and result.stdout == body
                observed.append(result.to_wire())
                qa_runs.append(
                    QaTestRun(
                        command=" ".join(command),
                        status=QaTestStatus.PASS,
                        evidence_id=evidence_id,
                        duration_ms=result.duration_ms,
                    )
                )
            evidence_path = tmp_path / f"checked-{request.run_id}.json"
            evidence_path.write_text(json.dumps(observed, sort_keys=True, separators=(",", ":")))
            evidence = Evidence(
                evidence_id=evidence_id,
                type=EvidenceType.TEST if request.role is AgentRole.QA else EvidenceType.COMMAND,
                uri=evidence_path.as_uri(),
                description="Independent role read both retained files at the exact candidate SHA.",
                sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            )
            if isinstance(artifact, QaReportArtifact):
                return artifact.model_copy(
                    update={
                        "evidence": (evidence,),
                        "content": artifact.content.model_copy(
                            update={
                                "criteria_results": tuple(
                                    value.model_copy(
                                        update={"evidence_ids": (evidence.evidence_id,)}
                                    )
                                    for value in artifact.content.criteria_results
                                ),
                                "tests_run": tuple(qa_runs),
                            }
                        ),
                    }
                )
            return artifact.model_copy(
                update={
                    "evidence": (evidence,),
                    "content": artifact.content.model_copy(
                        update={
                            "evidence": (evidence.evidence_id,),
                            "summary": "Both retained draft files match their approved complete "
                            "bodies in the exact committed candidate.",
                        }
                    ),
                }
            )

    adapter = IndependentAdapter(queue)

    def step(boundary: RoleRunBoundary, parent: str | None, now: datetime) -> QueuedRoleStep:
        queued = make_step(boundary, parent, now)
        return queued.model_copy(
            update={
                "work_item": queued.work_item.model_copy(
                    update={
                        "repository_id": f.scope.repository_id,
                        "repository_scopes": (f.task.repository,),
                    }
                )
            }
        )

    supervisor = QueuedDeliverySupervisor(
        queue=queue,
        guard=guard,
        artifacts=artifacts,
        allocation_sha256=ALLOCATION_SHA,
        repository_id=f.scope.repository_id,
        records=KnowledgeRecordStore(sidecar / "knowledge"),
        locks_root=sidecar / "locks",
        build_step=step,
        dispatcher=lambda _: dispatcher(queue),
    )
    definitions = {
        role: definition.model_copy(
            update={
                "provider": "codex",
                "model": "model-standard",
                "permissions": f.request.permissions
                if role is AgentRole.CODER
                else definition.permissions.model_copy(
                    update={
                        "write_paths": ("tests/**",) if role is AgentRole.QA else (),
                        "commands": ("git show", "git diff", "git status"),
                    }
                ),
            }
        )
        for role, definition in _definitions().items()
    }

    def current_claim() -> QueueClaim:
        assert guard.lease is not None
        guard.lease.check()
        return guard.lease.claim

    contexts = FileContextStore(paths.contexts)
    builder = FileRunContextBuilder(
        f.preserved.source.repository,
        context_store=contexts,
        claim_context=lambda: _claim_source(current_claim()),
    )
    config = RuntimeConfig(
        endpoint="https://runtime.invalid/v1/responses",
        model="model-standard",
        api_key_required=False,
        persistence=RuntimePersistence(backend="mysql"),
        paths=paths,
    )
    with RuntimeSession(
        config,
        environment={"ASE_MYSQL_DSN": dsn},
        agent_adapter=adapter,
        agent_definitions=definitions,
        repository_root=f.preserved.source.repository,
        artifact_store=artifacts,
        context_builder=builder,
        coder_execution_inputs=inputs,
        delivery_failure_control=WorkerDeliveryFailureControl(guard),
    ) as runtime:
        runtime_tasks = runtime.task_repository
        assert isinstance(runtime_tasks, MySqlTaskRepository)

        def queue_task() -> Task:
            return runtime_tasks.get(f.task.id)

        runtime_tasks.mutation_fence = lease.mutation_fence
        try:
            with (
                guard.task_scope(sidecar / "locks", f.task.id),
                bind_execution_guard(guard),
            ):
                boundary = runtime.run_step(
                    f.task.id,
                    BoundedRunControl(
                        runtime.task_repository,
                        permit=queue.step(next_claim.work_item.id).boundary,
                        guard=lease.check,
                    ),
                )
            assert isinstance(boundary, RoleRunBoundary), getattr(boundary.result, "reason", "")
            assert boundary.role is AgentRole.QA
            finished_at = datetime.now(UTC)
            lease.finish(step(boundary, next_claim.work_item.id, finished_at), finished_at)
        finally:
            runtime_tasks.mutation_fence = None
            guard.lease = None
            lease.stop()
        delivered = supervisor.run(
            runtime,
            f.task.id,
            terminal_result=lambda: _terminal_delivery_result(
                runtime.task_repository, artifacts, f.task.id
            ),
            close_worktrees=lambda: None,
        )
        assert isinstance(delivered, RetryDeliveryResult)
        assert delivered.task.status is TaskStatus.DONE
        assert (
            delivered.task.attempts == delivered.task.work_attempt == next_claim.work_item.attempt
        )
        assert not delivered.task.retry_failures
        assert [role for role, _ in adapter.invocation_claims] == [
            AgentRole.CODER,
            AgentRole.QA,
            AgentRole.REVIEWER,
        ]
        assert len({identity for _, identity in adapter.invocation_claims}) == 3
        roles = (ImplementationReportArtifact, QaReportArtifact, ReviewReportArtifact)
        completed = tuple(
            artifact
            for artifact in artifacts.list_for_task(f.task.id)
            if isinstance(artifact, roles)
        )
        assert len(completed) == 3
        assert len({artifact.source_revision for artifact in completed}) == 1
        assert len({artifact.producer.agent_id for artifact in completed}) == 3
        assert len({artifact.producer.run_id for artifact in completed}) == 3
        assert len({artifact.context_manifest_id for artifact in completed}) == 3
        assert delivered.candidate_revision != f.request.source_revision
        assert _git(f.preserved.source.worktree.path, "status", "--porcelain") == ""
