"""A rejected native assessment can recover into independently verified delivery."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.agents.structured import StructuredModelClient
from ai_software_engineer.agents.structured_observation import StructuredNativeStopReceipt
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain import AgentRole, Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.artifact import (
    ImplementationReportArtifact,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    HandleDeliveryWait,
    InspectDeliveryWait,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.retry_policy import DeliveryRetryPolicy
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.knowledge.agents import KnowledgeConsultation
from ai_software_engineer.knowledge.assessment_rejection import read_rejected_assessment
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationIntent,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.runtime import KnowledgeRunContextBuilder
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
from ai_software_engineer.manager.production_backend import _terminal_delivery_result
from ai_software_engineer.orchestration import FileRunContextBuilder, RetryDeliveryResult
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.runtime import (
    RuntimeConfig,
    RuntimePaths,
    RuntimePersistence,
    RuntimeSession,
)
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.models import QueueClaim
from ai_software_engineer.work_queue.worker import (
    AcceptedArtifactStore,
    DeliveryWaiting,
    QueuedDeliverySupervisor,
    WorkerDeliveryFailureControl,
    WorkerExecutionGuard,
    WorkerKnowledgeWait,
)
from tests.domain.factories import make_task
from tests.git.test_worktree import _create_fixture_repository, _git
from tests.knowledge.test_invocation_native import _client
from tests.orchestration.test_runner import _definitions
from tests.work_queue.test_worker_mysql import (
    ALLOCATION_SHA,
    REPOSITORY_ID,
    ObservedAdapter,
    dispatcher,
    make_step,
)

pytestmark = pytest.mark.mysql


class NativeKnowledgeClients:
    """Run real native processes; the test changes only future model behavior."""

    def __init__(self, root: Path, executable: Path) -> None:
        self.root, self.executable = root, executable

    def for_project(self, repository_root: Path, role: TeamRole) -> StructuredModelClient:
        return _client(self.root, self.executable, role)


def _executable(root: Path, ready: Path, calls: Path) -> Path:
    executable = root / "knowledge-model"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\nfrom pathlib import Path\n"
        "payload = json.loads(sys.stdin.read().split('\\nINPUT=', 1)[1])\n"
        "schema = json.loads(Path(sys.argv[sys.argv.index('--output-schema') + 1]).read_text())\n"
        f"with Path({str(calls)!r}).open('a') as log: log.write(schema['title'] + '\\n')\n"
        "if schema['title'] == 'KnowledgeIntent':\n"
        "    result = {'queries': ['original payment']}\n"
        "else:\n"
        "    reads = [item['chunk'] for item in payload['knowledge_evidence']\n"
        "             if item.get('chunk')]\n"
        "    citation = reads[0]['citation']\n"
        f"    if not Path({str(ready)!r}).exists(): citation['document_id'] = 'doc_unread'\n"
        "    claim = {'statement': 'Use the original payment identity.', 'citations': [citation]}\n"
        "    result = {'status': 'SUFFICIENT', 'claims': [claim]}\n"
        "output = Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
        "output.write_text(json.dumps(result))\n"
    )
    executable.chmod(0o700)
    return executable


def _claim_source(claim: QueueClaim) -> ContextSource:
    return ContextSource(
        source_id="execution.claim",
        uri="claim://" + claim.lease.id,
        required=True,
        content=json.dumps(
            {
                "task_id": claim.work_item.task_id,
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


def test_native_rejected_assessment_replacement_runs_fresh_knowledge_and_independent_roles_to_done(
    tmp_path: Path,
) -> None:
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    root = _create_fixture_repository(tmp_path)
    source = _git(root, "rev-parse", "HEAD")
    sidecar = tmp_path / "sidecar"
    paths = RuntimePaths(
        database=str(sidecar / "unused.sqlite"),
        artifacts=str(sidecar / "artifacts"),
        contexts=str(sidecar / "contexts"),
        evaluation_events=str(sidecar / "evaluation"),
        handoffs=str(sidecar / "handoffs"),
        evidence=str(sidecar / "evidence"),
        runs=str(sidecar / "runs"),
    )
    config = RuntimeConfig(
        endpoint="https://runtime.invalid/v1/responses",
        model="model-standard",
        api_key_required=False,
        persistence=RuntimePersistence(backend="mysql"),
        paths=paths,
    )
    scope = EngineeringScope(
        team_id="team_replacement_knowledge",
        project_id="project_replacement_knowledge",
        repository_id=REPOSITORY_ID,
        repository_root=str(root),
    )
    policy = DeliveryRetryPolicy()
    original = make_task()
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
                scope=scope, principal=LocalOperatorPrincipal.trusted_local()
            ).to_wire(),
        }
    )
    git = GitWorktreeManager(root, tmp_path / "worktrees" / REPOSITORY_ID)
    worktree = git.create(
        WorktreeSpec(task_id=task.id, role=AgentRole.CODER, attempt=1, source_revision=source)
    )
    ready, calls = tmp_path / "future-model-ready", tmp_path / "native-calls"
    clients = NativeKnowledgeClients(worktree.path, _executable(tmp_path, ready, calls))
    queue, guard = MySqlRoleQueue(dsn), WorkerExecutionGuard()
    artifacts = AcceptedArtifactStore(FileArtifactStore(paths.artifacts), queue, task.id, guard)
    records = KnowledgeRecordStore(sidecar / "knowledge" / "runs")
    contexts = FileContextStore(paths.contexts)
    adapter = ObservedAdapter(queue)

    def step(boundary: RoleRunBoundary, parent: str | None, now: datetime) -> QueuedRoleStep:
        queued = make_step(boundary, parent, now)
        return queued.model_copy(
            update={
                "work_item": queued.work_item.model_copy(update={"repository_scopes": (str(root),)})
            }
        )

    def current_claim() -> QueueClaim:
        assert guard.lease is not None
        guard.lease.check()
        return guard.lease.claim

    observed_timeouts: list[tuple[str, int | None]] = []

    def current_timeout(current: Task, claim: QueueClaim) -> int | None:
        timeout = queue.knowledge_timeout(current, claim)
        observed_timeouts.append((claim.lease.id, timeout))
        return timeout

    source_document = ContextSource(
        source_id="native.rule.payments",
        uri="repository://rules/AGENTS.md",
        content="# Payment rules\nUse the original payment identity.",
    )
    knowledge = KnowledgeRunContextBuilder(
        FileRunContextBuilder(
            root,
            sources=(source_document,),
            context_store=contexts,
            claim_context=lambda: _claim_source(current_claim()),
        ),
        contexts=contexts,
        clients=clients,
        repository_root=root,
        records=records,
        team_id=scope.team_id,
        project_id=scope.project_id,
        repository_id=scope.repository_id,
        sources=(source_document,),
        wait_port=WorkerKnowledgeWait(guard, records),
        invocation_claim=current_claim,
        invocation_timeout=current_timeout,
    )
    supervisor = QueuedDeliverySupervisor(
        queue=queue,
        guard=guard,
        artifacts=artifacts,
        allocation_sha256=ALLOCATION_SHA,
        repository_id=REPOSITORY_ID,
        records=records,
        locks_root=sidecar / "locks",
        build_step=step,
        dispatcher=lambda _: dispatcher(queue),
    )
    definitions = {
        role: definition.model_copy(update={"provider": "codex", "model": "model-standard"})
        for role, definition in _definitions().items()
    }
    with RuntimeSession(
        config,
        environment={"ASE_MYSQL_DSN": dsn},
        agent_adapter=adapter,
        agent_definitions=definitions,
        repository_root=root,
        artifact_store=artifacts,
        context_builder=knowledge,
        delivery_failure_control=WorkerDeliveryFailureControl(guard),
    ) as runtime:
        repository = runtime.task_repository
        repository.create(task)

        def run() -> RetryDeliveryResult:
            result = supervisor.run(
                runtime,
                task.id,
                terminal_result=lambda: _terminal_delivery_result(repository, artifacts, task.id),
                close_worktrees=lambda: None,
            )
            assert isinstance(result, RetryDeliveryResult)
            return result

        with pytest.raises(DeliveryWaiting):
            run()
        waiting = queue.items_for_task(task.id)
        assert len(waiting) == 1
        old = waiting[0]
        assert old.status is WorkItemStatus.WAITING_DEPENDENCY
        assert old.wait_disposition is not None
        facts = old.wait_disposition.facts
        assert facts.classification == "INVALID_OUTPUT"
        assert repository.get(task.id).status is TaskStatus.IMPLEMENTING
        assert adapter.invocation_claims == []
        assert queue.list_active_leases(now=datetime.now(UTC)) == ()
        assert calls.read_text().splitlines() == ["KnowledgeIntent", "KnowledgeAssessment"]
        old_bytes = {
            path: path.read_bytes()
            for directory in (records.root, Path(paths.contexts))
            for path in directory.rglob("*.json")
        }
        old_claim = queue.claims_for_work_item(old.id)[0]
        authority_root = tmp_path / "authority"
        authority_root.mkdir()

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
            artifacts=artifacts,
            engineering_authority=EngineeringAuthority(authority_root),
            knowledge_requirement_id=task.id,
            knowledge_retry=queue.knowledge_preparation_retry,
        )
        command = InspectDeliveryWait(
            work_item_id=old.id,
            expected_disposition_sha256=old.wait_disposition.disposition_sha256,
            expected_task_intent_sha256=facts.task_intent_sha256,
            expected_source_revision=facts.source_revision,
            expected_checkpoint_sequence=facts.checkpoint_sequence,
        )
        inspection = entry.inspect(command)
        assert inspection.rejected_knowledge is not None
        rejected = read_rejected_assessment(
            records.root, inspection.rejected_knowledge.observation_sha256
        )
        handled = entry.handle(HandleDeliveryWait.model_validate(command.to_wire()))
        assert handled.status == "RESOLVED" and handled.resolution is not None
        successor = queue.resolve_wait(handled.resolution)
        assert successor.parent_work_item_id == old.id
        assert successor.attempt == 2 and successor.status is WorkItemStatus.READY
        assert queue.resolve_wait(handled.resolution) == successor
        assert repository.get(task.id).work_attempt == 2
        ready.write_text("Future calls now return exact READ citations.\n")
        result = run()
        assert result.task.status is TaskStatus.DONE
        assert result.task.attempts == result.task.work_attempt == 2
        assert result.task.retry_failures == task.retry_failures and not result.task.retry_failures
        assert [role for role, _ in adapter.invocation_claims] == [
            AgentRole.CODER,
            AgentRole.QA,
            AgentRole.REVIEWER,
        ]
        assert len({lease for _, lease in adapter.invocation_claims}) == 3
        fresh_claim = queue.claims_for_work_item(successor.id)[0]
        assert fresh_claim.lease.id != old_claim.lease.id
        assert fresh_claim.assignment.id != old_claim.assignment.id
        assert len(observed_timeouts) == 4
        assert observed_timeouts[1] == (fresh_claim.lease.id, None)
        assert all(timeout is None for _, timeout in observed_timeouts)
        consultations = records.list("consultations", KnowledgeConsultation)
        assert {receipt.binding.role for receipt in consultations} == {
            TeamRole.CODER,
            TeamRole.QA,
            TeamRole.REVIEWER,
        }
        for receipt in consultations:
            bound = receipt.binding
            assert bound.run_id != rejected.binding.run_id
            assert bound.context_manifest_id != rejected.binding.context_manifest_id
            lane = KnowledgeRecordStore(
                records.root / "invocations" / invocation_lane_sha256(bound)
            )
            for phase in ("intent", "assessment"):
                identity = bound.run_id + ":" + phase
                intent = lane.get(
                    "knowledge-invocation-intents", identity, KnowledgeInvocationIntent
                )
                outcome = lane.get(
                    "knowledge-invocation-outcomes", identity, KnowledgeInvocationOutcome
                )
                outcome.validate_integrity()
                assert intent.claim is not None and outcome.state == "RETURNED"
                assert intent.claim.lease.id != old_claim.lease.id
                assert (
                    intent.timeout_seconds
                    == definitions[AgentRole(bound.role.value)].timeout_seconds
                )
                assert isinstance(outcome.executions[-1].observation, StructuredNativeStopReceipt)
            if bound.role is TeamRole.CODER:
                assert intent.claim is not None and intent.claim == fresh_claim
        complete = artifacts.list_for_task(task.id)
        plan = next(artifact for artifact in complete if isinstance(artifact, PlanArtifact))
        implementation = next(
            artifact for artifact in complete if isinstance(artifact, ImplementationReportArtifact)
        )
        qa = next(artifact for artifact in complete if isinstance(artifact, QaReportArtifact))
        review = next(
            artifact for artifact in complete if isinstance(artifact, ReviewReportArtifact)
        )
        assert plan.artifact_id in implementation.parent_artifact_ids
        assert implementation.artifact_id in qa.parent_artifact_ids
        assert qa.artifact_id in review.parent_artifact_ids
        assert implementation.source_revision == qa.source_revision == review.source_revision
        assert len({artifact.producer.agent_id for artifact in (implementation, qa, review)}) == 3
        assert tuple(event.to_status for event in repository.list_events(task.id)) == (
            TaskStatus.PLANNING,
            TaskStatus.IMPLEMENTING,
            TaskStatus.QA,
            TaskStatus.REVIEW,
            TaskStatus.DONE,
        )
        assert all(item.status is WorkItemStatus.CLOSED for item in queue.items_for_task(task.id))
        assert queue.list_active_leases(now=datetime.now(UTC)) == ()
        assert calls.read_text().splitlines() == ["KnowledgeIntent", "KnowledgeAssessment"] * 4
        assert all(path.read_bytes() == content for path, content in old_bytes.items())
        assert read_rejected_assessment(records.root, rejected.observation_sha256) == rejected
        assert _git(worktree.path, "status", "--porcelain") == ""
        assert _git(worktree.path, "rev-parse", "HEAD") == source
