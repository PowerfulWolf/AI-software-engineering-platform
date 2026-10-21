"""Public exact engineering recovery after a real SQL accepted Coder progress."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import JsonValue, TypeAdapter
from pymysql.cursors import DictCursor

from ai_software_engineer.artifacts import FileArtifactStore, artifact_digest
from ai_software_engineer.domain import AgentRole, Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.artifact import CoderProgressArtifact
from ai_software_engineer.domain.delivery_resolution import (
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
from ai_software_engineer.domain.retry_policy import DeliveryRetryPolicy
from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
from ai_software_engineer.manager.rejected_knowledge_draft import RejectedKnowledgeDraftAdmission
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
)
from ai_software_engineer.work_queue.models import QueueArtifactReceipt, QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.worker import (
    DeliveryWaiting,
    WorkerDeliveryFailureControl,
    WorkerExecutionGuard,
    WorkerLease,
)
from tests.domain.factories import make_plan_artifact
from tests.manager.test_rejected_knowledge_current_draft import (
    CurrentDraftFixture,
    current_draft_fixture,
)
from tests.manager.test_rejected_workspace_admission import _claim
from tests.work_queue.test_worker_mysql import TOKEN, claim_step

pytestmark = pytest.mark.mysql


@pytest.fixture
def sql_current_draft(
    tmp_path: Path,
) -> Iterator[tuple[CurrentDraftFixture, MySqlTaskRepository, MySqlRoleQueue, DeliveryWaitService]]:
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    queue = MySqlRoleQueue(dsn)
    claims: list[QueueClaim] = []
    with MySqlTaskRepository(dsn) as repository:

        def event(task_id: str, status: TaskStatus, ids: tuple[str, ...] = ()) -> None:
            task = repository.get(task_id)
            sequence = repository.current_revision(task_id) + 1
            repository.append_event(
                build_event(
                    task,
                    status,
                    event_id=f"evt_current_draft_{sequence}",
                    reason="current draft fixture",
                    source_revision=task.base_ref,
                    artifact_ids=ids,
                    occurred_at=datetime.now(UTC),
                )
            )

        def prepare(task: Task, scope: EngineeringScope) -> Task:
            policy = DeliveryRetryPolicy()
            assert task.constraints is not None
            initial = Task.model_validate(
                {
                    **task.to_wire(),
                    "status": "NEW",
                    "attempts": 0,
                    "retry_policy": policy.to_wire(),
                    "max_attempts": policy.execution_limit,
                    "constraints": {
                        **task.constraints.to_wire(),
                        "max_attempts": policy.execution_limit,
                    },
                    "engineering_policy": EngineeringPolicy.bounded_local(
                        scope=scope, principal=LocalOperatorPrincipal.trusted_local()
                    ).to_wire(),
                }
            )
            repository.create(initial)
            repository.record_attempt(initial.id, 1)
            event(initial.id, TaskStatus.PLANNING)
            event(initial.id, TaskStatus.IMPLEMENTING)
            return repository.get(initial.id)

        def step(task: Task, scope: EngineeringScope, attempt: int, at: datetime) -> QueuedRoleStep:
            item = _claim(task, scope, attempt, at).work_item.model_copy(
                update={
                    "status": WorkItemStatus.READY,
                    "checkpoint_sequence": repository.current_revision(task.id),
                    "required_capabilities": ("delivery",),
                    "parent_work_item_id": claims[0].work_item.id if claims else None,
                }
            )
            return QueuedRoleStep(
                work_item=item,
                allocation_sha256="1" * 64,
                boundary=RoleRunBoundary(
                    task.id, AgentRole.CODER, attempt, item.checkpoint_sequence, task.base_ref
                ),
            )

        def claim_factory(
            task: Task, scope: EngineeringScope, attempt: int, at: datetime
        ) -> QueueClaim:
            if attempt == 1:
                queued = step(task, scope, attempt, at)
                queue.admit(
                    RoleQueueAdmission(
                        task_id=task.id,
                        repository_id=scope.repository_id,
                        allocation_sha256="1" * 64,
                        legacy_artifacts=(
                            QueueArtifactReceipt(
                                artifact_id="art_plan_001",
                                sha256=artifact_digest(
                                    make_plan_artifact().model_copy(
                                        update={
                                            "source_revision": task.base_ref,
                                            "context_manifest_id": "ctx_" + "a" * 64,
                                        }
                                    )
                                ),
                            ),
                        ),
                    ),
                    queued,
                )
            else:
                queued = queue.step("work_admission_2")
            claim = claim_step(queue, queued)
            claims.append(claim)
            return claim

        def publish(
            claim: QueueClaim, progress: CoderProgressArtifact, artifacts: FileArtifactStore
        ) -> None:
            queue.accept_artifact(claim, TOKEN, artifacts, progress)

        def advance(task: Task, progress: CoderProgressArtifact) -> Task:
            event(task.id, TaskStatus.CONTINUE_REQUIRED, (progress.artifact_id,))
            event(task.id, TaskStatus.QUEUED, (progress.artifact_id,))
            repository.record_attempt(task.id, 2)
            event(task.id, TaskStatus.IMPLEMENTING, (progress.artifact_id,))
            current = repository.get(task.id)
            scope = current.engineering_policy.scope if current.engineering_policy else None
            assert scope is not None
            completed_at = datetime.now(UTC)
            queue.finish(
                claims[0],
                TOKEN,
                next_step=step(current, scope, 2, completed_at),
                now=completed_at,
            )
            return current

        f = current_draft_fixture(
            tmp_path,
            prepare_task=prepare,
            claim_factory=claim_factory,
            progress_published=publish,
            advance_task=advance,
        )
        assert queue.accepted(f.task.id) == f.queue.publications
        lease = WorkerLease(queue, f.claim, TOKEN)
        guard = WorkerExecutionGuard()
        guard.lease = lease
        lease.start()
        try:
            with pytest.raises(DeliveryWaiting):
                WorkerDeliveryFailureControl(guard).wait(
                    f.task,
                    classification="PLATFORM_BUG",
                    reason="historical opaque preparation failure",
                    source_revision=f.task.base_ref,
                    artifact_ids=(),
                )
        finally:
            lease.stop()
            guard.lease = None
        authority_root = tmp_path / "authority"
        authority_root.mkdir()

        def consume(resolution: DeliveryResolution) -> None:
            queue.resolve_wait(resolution)

        entry = DeliveryWaitService(
            repository=repository,
            queue=queue,
            scope=f.scope,
            sidecar_state=f.state,
            git=f.git,
            principal=LocalOperatorPrincipal.trusted_local(),
            consume=consume,
            artifacts=f.artifacts,
            engineering_authority=EngineeringAuthority(authority_root),
            knowledge_requirement_id=f.task.id,
            knowledge_retry=queue.knowledge_preparation_retry,
        )
        yield f, repository, queue, entry


def _command(f: CurrentDraftFixture, queue: MySqlRoleQueue) -> InspectDeliveryWait:
    item = queue.get(f.claim.work_item.id)
    assert item.wait_disposition is not None
    facts = item.wait_disposition.facts
    return InspectDeliveryWait(
        work_item_id=item.id,
        expected_disposition_sha256=item.wait_disposition.disposition_sha256,
        expected_task_intent_sha256=facts.task_intent_sha256,
        expected_source_revision=facts.source_revision,
        expected_checkpoint_sequence=facts.checkpoint_sequence,
    )


def test_current_progress_requires_exact_resolve_then_one_normal_attempt_and_fresh_claim(
    sql_current_draft: tuple[
        CurrentDraftFixture, MySqlTaskRepository, MySqlRoleQueue, DeliveryWaitService
    ],
) -> None:
    f, repository, queue, entry = sql_current_draft
    original = queue.get(f.claim.work_item.id)
    before = repository.get(f.task.id)
    assert original.wait_disposition is not None
    assert original.wait_disposition.facts.classification == "PLATFORM_BUG"
    assert original.wait_disposition.facts.evidence_ids == ()
    historical = {path: path.read_bytes() for path in f.state.rglob("*.json")}
    handling = entry.handle(HandleDeliveryWait.model_validate(_command(f, queue).to_wire()))
    assert handling.status == "NEEDS_AUTHORIZATION" and handling.resolution is None
    proof = handling.investigation
    assert proof.rejected_knowledge is not None
    assert proof.rejected_knowledge.current_draft_sha256 is not None
    assert proof.permitted_resolutions == (
        DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION,
    )
    assert repository.get(f.task.id) == before
    resolution = entry.resolve(
        ResolveDeliveryWait.model_validate(
            {
                **_command(f, queue).to_wire(),
                "resolution_kind": DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION,
                "proof_sha256": proof.proof_sha256,
                "submitted_at": datetime.now(UTC),
            }
        )
    )
    assert resolution.authorization_source == "engineering_operator_decision"
    successor = queue.resolve_wait(resolution)
    assert queue.resolve_wait(resolution) == successor
    after = repository.get(f.task.id)
    assert after.attempts == before.attempts + 1
    assert after.work_attempt == before.work_attempt + 1
    assert after.retry_failures == before.retry_failures
    assert after.base_ref == before.base_ref
    assert successor.parent_work_item_id == original.id and successor.id != original.id
    assert queue.get(original.id).status is WorkItemStatus.CLOSED
    assert queue.rejected_knowledge_retry(successor.id) == proof.rejected_knowledge
    assert queue.rejected_knowledge_retry(original.id) is None
    fresh = claim_step(queue, queue.step(successor.id))
    assert fresh.lease.id != f.claim.lease.id
    assert fresh.assignment.id != f.claim.assignment.id
    request = f.request.model_copy(
        update={
            "attempt": fresh.work_item.attempt,
            "run_id": "run_current_draft_new_claim",
            "context_manifest_id": "ctx_" + "c" * 64,
            "input_artifact_ids": (f.progress.artifact_id,),
            "continuation_checkpoint_id": f.progress.artifact_id,
            "continuation_changed_paths": ("src/app.py",),
        }
    )
    RejectedKnowledgeDraftAdmission(
        state=f.state,
        git=f.git,
        task_reader=lambda: repository.get(f.task.id),
        claim_reader=lambda: fresh,
        retry_reader=queue.rejected_knowledge_retry,
    ).authorize(request, f.worktree)
    assert all(path.read_bytes() == data for path, data in historical.items())
    # The live CLOSED item clears its wait cursor. Its durable WAITING fact and
    # exact consumed resolution retain the original disposition unchanged.
    assert queue.get(original.id).wait_disposition is None
    with (
        closing(open_mysql_connection(os.environ["ASE_TEST_MYSQL_DSN"])) as connection,
        connection.cursor(DictCursor) as cursor,
    ):
        cursor.execute(
            "SELECT event_type,payload_json FROM work_queue_events "
            "WHERE work_item_id=%s AND event_type IN ('WAITING','WAIT_RESOLVED') "
            "ORDER BY sequence",
            (original.id,),
        )
        history = cursor.fetchall()
    assert [row["event_type"] for row in history] == ["WAITING", "WAIT_RESOLVED"]
    waiting_payload = TypeAdapter(dict[str, JsonValue]).validate_json(history[0]["payload_json"])
    waiting_snapshot = QueuedWorkItem.model_validate(waiting_payload["work_item"])
    assert waiting_snapshot == original
    resolved_payload = TypeAdapter(dict[str, JsonValue]).validate_json(history[1]["payload_json"])
    resolved_detail = TypeAdapter(dict[str, JsonValue]).validate_python(resolved_payload["detail"])
    consumed = DeliveryResolution.model_validate(resolved_detail["resolution"])
    assert consumed == resolution
    assert consumed.expected_disposition_sha256 == original.wait_disposition.disposition_sha256


@pytest.mark.parametrize("change", ["body", "mode", "extra"])
def test_current_draft_drift_after_inspect_does_not_consume_original_wait(
    sql_current_draft: tuple[
        CurrentDraftFixture, MySqlTaskRepository, MySqlRoleQueue, DeliveryWaitService
    ],
    change: str,
) -> None:
    f, repository, queue, entry = sql_current_draft
    command = _command(f, queue)
    proof = entry.inspect(command)
    before = repository.get(f.task.id)
    if change == "body":
        (f.worktree / "src/app.py").write_text("VALUE = 99\n")
    elif change == "mode":
        (f.worktree / "src/app.py").chmod(0o755)
    else:
        (f.worktree / "src/unreported.py").write_text("UNREPORTED = True\n")
    with pytest.raises(ValueError):
        entry.resolve(
            ResolveDeliveryWait.model_validate(
                {
                    **command.to_wire(),
                    "resolution_kind": DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION,
                    "proof_sha256": proof.proof_sha256,
                    "submitted_at": datetime.now(UTC),
                }
            )
        )
    assert repository.get(f.task.id) == before
    assert queue.get(f.claim.work_item.id).status is WorkItemStatus.WAITING_DEPENDENCY
    assert len(queue.items_for_task(f.task.id)) == 2


def test_current_draft_resolution_runs_fresh_native_knowledge_and_independent_delivery_to_done(
    sql_current_draft: tuple[
        CurrentDraftFixture, MySqlTaskRepository, MySqlRoleQueue, DeliveryWaitService
    ],
    tmp_path: Path,
) -> None:
    from ai_software_engineer.agents.models import AgentRequest, AgentResult
    from ai_software_engineer.context import ContextSource, FileContextStore
    from ai_software_engineer.domain.artifact import (
        ImplementationReportArtifact,
        QaReportArtifact,
        ReviewReportArtifact,
    )
    from ai_software_engineer.domain.enums import TeamRole
    from ai_software_engineer.knowledge.agents import KnowledgeConsultation
    from ai_software_engineer.knowledge.runtime import KnowledgeRunContextBuilder
    from ai_software_engineer.knowledge.store import KnowledgeRecordStore
    from ai_software_engineer.manager.production_backend import _terminal_delivery_result
    from ai_software_engineer.orchestration import FileRunContextBuilder, RetryDeliveryResult
    from ai_software_engineer.runtime import (
        RuntimeConfig,
        RuntimePaths,
        RuntimePersistence,
        RuntimeSession,
    )
    from ai_software_engineer.work_queue.worker import (
        AcceptedArtifactStore,
        QueuedDeliverySupervisor,
        WorkerKnowledgeWait,
    )
    from tests.orchestration.test_runner import _definitions
    from tests.work_queue.test_rejected_knowledge_replacement_mysql import (
        NativeKnowledgeClients,
        _claim_source,
        _executable,
    )
    from tests.work_queue.test_worker_mysql import ObservedAdapter, dispatcher, make_step

    f, repository, queue, entry = sql_current_draft
    dsn = os.environ["ASE_TEST_MYSQL_DSN"]
    command = _command(f, queue)
    proof = entry.inspect(command)
    assert proof.rejected_knowledge is not None
    assert proof.rejected_knowledge.current_draft_sha256 is not None
    resolution = entry.resolve(
        ResolveDeliveryWait.model_validate(
            {
                **command.to_wire(),
                "resolution_kind": DeliveryResolutionKind.RETRY_REJECTED_KNOWLEDGE_PREPARATION,
                "proof_sha256": proof.proof_sha256,
                "submitted_at": datetime.now(UTC),
            }
        )
    )
    successor = queue.resolve_wait(resolution)
    guard = WorkerExecutionGuard()
    artifacts = AcceptedArtifactStore(f.artifacts, queue, f.task.id, guard)
    records = KnowledgeRecordStore(f.state.parent / "knowledge/runs")
    contexts = FileContextStore(f.state.parent / "contexts")
    ready, calls = tmp_path / "new-knowledge-ready", tmp_path / "new-knowledge-calls"
    ready.write_text("Only future knowledge calls use the exact READ citation.\n")
    clients = NativeKnowledgeClients(f.worktree, _executable(tmp_path, ready, calls))

    def claim() -> QueueClaim:
        assert guard.lease is not None
        guard.lease.check()
        return guard.lease.claim

    admission = RejectedKnowledgeDraftAdmission(
        state=f.state,
        git=f.git,
        task_reader=lambda: repository.get(f.task.id),
        claim_reader=claim,
        retry_reader=queue.rejected_knowledge_retry,
    )

    class AdmittedAdapter(ObservedAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            if request.role is AgentRole.CODER:
                admission.authorize(request, f.worktree)
            return super().run(request)

    adapter = AdmittedAdapter(queue)
    source_document = ContextSource(
        source_id="native.rule.payments",
        uri="repository://rules/AGENTS.md",
        content="# Payment rules\nUse the original payment identity.",
    )
    knowledge = KnowledgeRunContextBuilder(
        FileRunContextBuilder(
            Path(f.scope.repository_root),
            sources=(source_document,),
            context_store=contexts,
            claim_context=lambda: _claim_source(claim()),
        ),
        contexts=contexts,
        clients=clients,
        repository_root=Path(f.scope.repository_root),
        records=records,
        team_id=f.scope.team_id,
        project_id=f.scope.project_id,
        repository_id=f.scope.repository_id,
        sources=(source_document,),
        wait_port=WorkerKnowledgeWait(guard, records),
        invocation_claim=claim,
        invocation_timeout=lambda current, owned: queue.knowledge_timeout(current, owned),
    )

    def step(boundary: RoleRunBoundary, parent: str | None, now: datetime) -> QueuedRoleStep:
        queued = make_step(boundary, parent, now)
        return queued.model_copy(
            update={
                "allocation_sha256": "1" * 64,
                "work_item": queued.work_item.model_copy(
                    update={
                        "repository_id": f.scope.repository_id,
                        "repository_scopes": (f.scope.repository_root,),
                    }
                ),
            }
        )

    supervisor = QueuedDeliverySupervisor(
        queue=queue,
        guard=guard,
        artifacts=artifacts,
        allocation_sha256="1" * 64,
        repository_id=f.scope.repository_id,
        records=records,
        locks_root=f.state.parent / "locks",
        build_step=step,
        dispatcher=lambda queued: dispatcher(queue),
    )
    paths = RuntimePaths(
        database=str(f.state / "unused.sqlite"),
        artifacts=str(f.state.parent / "artifacts"),
        contexts=str(f.state.parent / "contexts"),
        evaluation_events=str(f.state.parent / "evaluation"),
        handoffs=str(f.state.parent / "handoffs"),
        evidence=str(f.state.parent / "evidence"),
        runs=str(f.state.parent / "runs"),
    )
    config = RuntimeConfig(
        endpoint="https://runtime.invalid/v1/responses",
        model="model-standard",
        api_key_required=False,
        persistence=RuntimePersistence(backend="mysql"),
        paths=paths,
    )
    definitions = {
        role: definition.model_copy(
            update={
                "provider": "codex",
                "model": "model-standard",
                **({"permissions": f.request.permissions} if role is AgentRole.CODER else {}),
            }
        )
        for role, definition in _definitions().items()
    }
    with RuntimeSession(
        config,
        environment={"ASE_MYSQL_DSN": dsn},
        agent_adapter=adapter,
        agent_definitions=definitions,
        repository_root=Path(f.scope.repository_root),
        artifact_store=artifacts,
        context_builder=knowledge,
        delivery_failure_control=WorkerDeliveryFailureControl(guard),
    ) as runtime:
        result = supervisor.run(
            runtime,
            f.task.id,
            terminal_result=lambda: _terminal_delivery_result(repository, artifacts, f.task.id),
            close_worktrees=lambda: None,
        )
    assert isinstance(result, RetryDeliveryResult)
    assert result.task.id == f.task.id and result.task.status is TaskStatus.DONE
    assert result.task.attempts == result.task.work_attempt == 3
    assert result.task.retry_failures == f.task.retry_failures
    assert [role for role, _ in adapter.invocation_claims] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    assert len({lease for _, lease in adapter.invocation_claims}) == 3
    actual = queue.claims_for_work_item(successor.id)
    assert len(actual) == 1 and actual[0].lease.id != f.claim.lease.id
    consultations = records.list("consultations", KnowledgeConsultation)
    assert {value.binding.role for value in consultations} == {
        TeamRole.CODER,
        TeamRole.QA,
        TeamRole.REVIEWER,
    }
    assert all(
        value.binding.run_id != f.observation.binding.run_id
        and value.binding.context_manifest_id != f.observation.binding.context_manifest_id
        for value in consultations
    )
    complete = artifacts.list_for_task(f.task.id)
    implementation = next(
        value for value in complete if isinstance(value, ImplementationReportArtifact)
    )
    qa = next(value for value in complete if isinstance(value, QaReportArtifact))
    review = next(value for value in complete if isinstance(value, ReviewReportArtifact))
    assert f.progress.artifact_id in implementation.parent_artifact_ids
    assert implementation.artifact_id in qa.parent_artifact_ids
    assert qa.artifact_id in review.parent_artifact_ids
    assert implementation.source_revision == qa.source_revision == review.source_revision
    assert len({value.producer.agent_id for value in (implementation, qa, review)}) == 3
    assert all(item.status is WorkItemStatus.CLOSED for item in queue.items_for_task(f.task.id))
    assert queue.list_active_leases(now=datetime.now(UTC)) == ()
    assert calls.read_text().splitlines() == ["KnowledgeIntent", "KnowledgeAssessment"] * 3
