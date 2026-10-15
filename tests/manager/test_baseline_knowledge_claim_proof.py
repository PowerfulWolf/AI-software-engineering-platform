"""A real claimed knowledge failure cannot be mistaken for an unknown main call."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.model_diagnostics import model_call_phase
from ai_software_engineer.agents.models import AgentErrorCode, AgentRequest
from ai_software_engineer.agents.openai_compatible import HttpResponse
from ai_software_engineer.agents.structured import (
    FallbackStructuredModelClient,
    StructuredModelError,
    StructuredModelResult,
    StructuredModelRoute,
)
from ai_software_engineer.agents.structured_observation import (
    StructuredCallIdentity,
    StructuredExecutionAdmission,
    StructuredHttpRoundTripReceipt,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextBundle, ContextSource, FileContextStore
from ai_software_engineer.domain import AgentDefinition, AgentRole, Artifact, Task
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import TaskStatus, TeamRole
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord,
    KnowledgeInvocationFailure,
    KnowledgeInvocationIntent,
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    KnowledgeInvocationResult,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeRunBinding,
    KnowledgeSnapshot,
)
from ai_software_engineer.knowledge.preparation_retry import claim_identity_sha256
from ai_software_engineer.knowledge.runtime import KnowledgeRunContextBuilder
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_production import (
    BaselineContinueCommand,
    BaselineExecuteCommand,
    BaselineProposeCommand,
    BaselineQuiescenceProof,
    ProductionBaselineFactCollector,
)
from ai_software_engineer.manager.capacity_input_reader import UninvokedClaimBoundary
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.orchestration.context import FileRunContextBuilder
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.claim_snapshot import OriginalClaimRecord
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.worker import AcceptedArtifactStore
from tests.domain.factories import make_task
from tests.knowledge.test_invocation_native import _client, _http_client, _HttpTransport
from tests.manager.test_execution_baseline_invocations import _allocation, _claim
from tests.manager.test_execution_baseline_reservation import reservation_fixture
from tests.manager.test_production_backend import _git, _git_output, _ScriptedClientFactory
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_public_context_capacity_baseline import public_capacity_host
from tests.orchestration.test_native_continuation import NOW
from tests.orchestration.test_runner import _definitions
from tests.work_queue.test_mysql_queue import queued_item


@dataclass(frozen=True)
class Facts:
    collector: ProductionBaselineFactCollector
    task: Task
    item: QueuedWorkItem
    claim: QueueClaim
    records: KnowledgeRecordStore
    intent: KnowledgeInvocationIntent
    outcome: KnowledgeInvocationOutcome


def knowledge_failure(
    tmp_path: Path, *, returned: bool = False, dispatch_sequence: int = 0
) -> Facts:
    repository = tmp_path / "repository"
    repository.mkdir()
    task = make_task().model_copy(
        update={"repository": str(repository), "status": TaskStatus.IMPLEMENTING, "attempts": 1}
    )
    item = queued_item(checkpoint_sequence=3).model_copy(
        update={
            "task_id": task.id,
            "repository_scopes": (task.repository,),
            "dispatch_sequence": dispatch_sequence,
        }
    )
    claim = _claim(item, "lease_knowledge_failed")
    step = QueuedRoleStep(
        work_item=item,
        boundary=RoleRunBoundary(task.id, AgentRole.CODER, 1, 3, "a" * 40),
        allocation_sha256="b" * 64,
    )

    class Queue(MySqlRoleQueue):
        def __init__(self) -> None:
            pass

        def claims_for_work_item(self, identity: str) -> tuple[QueueClaim, ...]:
            assert identity == item.id
            return (claim,)

        def original_claim(self, identity: str) -> QueueClaim:
            if identity != claim.lease.id:
                raise ValueError("foreign historical claim")
            return claim

        def original_claim_record(self, identity: str) -> OriginalClaimRecord:
            return OriginalClaimRecord(self.original_claim(identity), has_immutable_snapshot=False)

        def step_for_claim(self, actual: QueueClaim) -> QueuedRoleStep:
            assert claim_identity_sha256(actual) == claim_identity_sha256(claim)
            return step

        def step(self, identity: str) -> QueuedRoleStep:
            assert identity == item.id
            return step

        def step_for_invocation(self, identity: str, baseline: str | None) -> QueuedRoleStep:
            assert identity == item.id and baseline is None
            return step

    class Accepted(AcceptedArtifactStore):
        def __init__(self) -> None:
            pass

        def list_for_task(self, task_id: str) -> tuple[Artifact, ...]:
            assert task_id == task.id
            return ()

    scope = EngineeringScope(
        team_id="team_knowledge",
        project_id="project_knowledge",
        repository_id=item.repository_id,
        repository_root=task.repository,
    )
    context = FileRunContextBuilder(
        Path(task.repository),
        context_store=FileContextStore(tmp_path / "contexts"),
        claim_context=lambda: ContextSource(
            source_id="execution.claim",
            uri="claim://" + claim.lease.id,
            content=json.dumps(
                {
                    "task_id": task.id,
                    "work_item_id": item.id,
                    "lease_id": claim.lease.id,
                    "assignment_id": claim.assignment.id,
                    "dispatch_sequence": item.dispatch_sequence,
                    "role": item.role.value,
                    "attempt": item.attempt,
                    "checkpoint_sequence": item.checkpoint_sequence,
                }
            ),
            roles=(AgentRole.CODER,),
            required=True,
        ),
    ).build(task, _definitions()[AgentRole.CODER], attempt=1, candidate_revision="a" * 40)
    frozen = KnowledgeSnapshot.create(
        team_id=scope.team_id,
        project_id=scope.project_id,
        requirement_id="delivery_knowledge",
        repository_ids=(item.repository_id,),
    )
    knowledge = KnowledgeRecordStore(tmp_path / "knowledge/runs")
    knowledge.put("snapshots", frozen.snapshot_sha256, frozen)
    bound = KnowledgeRunBinding(
        run_id="run_knowledge_" + digest((context.context_id, frozen.snapshot_sha256))[:32],
        role=TeamRole.CODER,
        team_id=scope.team_id,
        project_id=scope.project_id,
        requirement_id=frozen.requirement_id,
        repository_ids=(item.repository_id,),
        task_id=task.id,
        source_revision=context.source_revision,
        context_manifest_id=context.context_id,
        snapshot_sha256=frozen.snapshot_sha256,
    )
    intent = KnowledgeInvocationIntent.create(
        binding=bound,
        phase="assessment",
        request_sha256="c" * 64,
        timeout_seconds=2,
        claim=claim,
        created_at=NOW + timedelta(seconds=1),
    )
    admission = StructuredExecutionAdmission.create(
        observation_id="d" * 32,
        call=StructuredCallIdentity(
            invocation_id="e" * 32,
            route_index=1,
            provider="fixture",
            model="fixture",
            reasoning_effort="medium",
            role=bound.role,
            phase="knowledge_assessment",
            request_sha256=intent.request_sha256,
        ),
        execution_kind="http",
        transport_request_sha256="f" * 64,
        timeout_seconds=2,
        admitted_at=NOW + timedelta(seconds=2),
    )
    receipt = StructuredHttpRoundTripReceipt.create(
        admission=admission,
        outcome="returned",
        http_status=200 if returned else 503,
        response_body_sha256="a" * 64,
        completed_at=NOW + timedelta(seconds=3),
    )
    executions = tuple(
        KnowledgeExecutionRecord.create(intent_sha256=intent.intent_sha256, observation=value)
        for value in (admission, receipt)
    )
    outcome = KnowledgeInvocationOutcome.create(
        intent=intent,
        state="RETURNED" if returned else "FAILED",
        result=KnowledgeInvocationResult(payload={"checked": True}, duration_ms=0)
        if returned
        else None,
        failure=None
        if returned
        else KnowledgeInvocationFailure(
            code=AgentErrorCode.PROVIDER_UNAVAILABLE,
            safe_message="知识提供方暂不可用",
            transient=True,
        ),
        executions=executions,
        completed_at=NOW + timedelta(seconds=4),
    )
    records = KnowledgeRecordStore(knowledge.root / "invocations" / invocation_lane_sha256(bound))
    records.put("knowledge-invocation-intents", bound.run_id + ":assessment", intent)
    records.put("knowledge-invocation-outcomes", bound.run_id + ":assessment", outcome)
    for execution in executions:
        records.put("knowledge-execution-records", execution.record_sha256, execution)
    collector = ProductionBaselineFactCollector.__new__(ProductionBaselineFactCollector)
    collector.state = tmp_path / "state"
    collector.queue = Queue()
    collector.scope = scope
    collector.requirement_id = frozen.requirement_id
    collector.allocation = _allocation(task, "b" * 64)
    collector.artifacts = Accepted()
    collector.capacity_artifacts = FileArtifactStore(tmp_path / "artifacts")
    collector.inputs = StoredCoderExecutionInputResolver(None)
    collector.permissions = _definitions()[AgentRole.CODER].permissions
    collector.route_root = tmp_path / "model-routes"
    collector._scope_held = True
    return Facts(collector, task, item, claim, records, intent, outcome)


def test_exact_failed_knowledge_claim_participates_in_baseline_quiescence(tmp_path: Path) -> None:
    facts = knowledge_failure(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    (proof,) = facts.collector._invocations(facts.task, (facts.item,), (), ())
    assert proof.proof_kind == "claimed_knowledge_failure"
    (knowledge,) = proof.knowledge_only_claims
    assert knowledge.lease_id == facts.claim.lease.id
    assert knowledge.claim_sha256 == claim_identity_sha256(facts.claim)
    assert knowledge.outcome_sha256s == (facts.outcome.outcome_sha256,)
    assert proof.start_sha256 is proof.outcome_sha256 is None
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}


def test_real_native_failed_preparation_is_verified_with_complete_local_stop(
    tmp_path: Path,
) -> None:
    facts = knowledge_failure(tmp_path)
    executable = tmp_path / "offline-knowledge"
    executable.write_text(f"#!{sys.executable}\nraise SystemExit(7)\n")
    executable.chmod(0o700)
    root = tmp_path / "knowledge/runs"
    with pytest.raises(StructuredModelError), model_call_phase("knowledge_intent"):
        KnowledgeInvocationJournal(KnowledgeRecordStore(root), claimed=lambda: facts.claim).call(
            facts.intent.binding,
            "intent",
            client=_client(Path(facts.task.repository), executable, TeamRole.CODER),
            instructions="Read-only offline knowledge fixture",
            input_payload={},
            output_schema={"type": "object", "properties": {}},
            timeout_seconds=2,
        )
    (proof,) = facts.collector._invocations(facts.task, (facts.item,), (), ())
    (knowledge,) = proof.knowledge_only_claims
    assert len(knowledge.outcome_sha256s) == 2
    assert len(knowledge.execution_record_sha256s) == 4


@pytest.mark.parametrize(
    "problem",
    [
        "wrong_key",
        "orphan_outcome",
        "orphan_execution",
        "foreign_claim",
        "appended_foreign_claim",
        "source",
        "snapshot",
    ],
)
def test_resealed_or_orphan_knowledge_proof_cannot_replace_original_facts(
    tmp_path: Path, problem: str
) -> None:
    facts = knowledge_failure(tmp_path)
    records, intent, outcome = facts.records, facts.intent, facts.outcome
    intent_path = records.root / records._name(
        "knowledge-invocation-intents", intent.binding.run_id + ":" + intent.phase
    )
    outcome_path = records.root / records._name(
        "knowledge-invocation-outcomes", intent.binding.run_id + ":" + intent.phase
    )
    if problem == "wrong_key":
        intent_path.rename(records.root / records._name("knowledge-invocation-intents", "other"))
    elif problem == "orphan_outcome":
        intent_path.unlink()
    elif problem == "orphan_execution":
        record = KnowledgeExecutionRecord.create(
            intent_sha256="f" * 64, observation=outcome.executions[0].observation
        )
        records.put("knowledge-execution-records", record.record_sha256, record)
    else:
        if problem in {"foreign_claim", "appended_foreign_claim"}:
            changed = intent.model_copy(update={"claim": _claim(facts.item, "lease_other")})
            if problem == "appended_foreign_claim":
                changed = changed.model_copy(
                    update={
                        "binding": changed.binding.model_copy(
                            update={"run_id": "run_knowledge_foreign_claim"}
                        )
                    }
                )
        else:
            changed = intent.model_copy(
                update={
                    "binding": intent.binding.model_copy(
                        update={
                            "source_revision" if problem == "source" else "snapshot_sha256": "f"
                            * (40 if problem == "source" else 64)
                        }
                    )
                }
            )
        changed = changed.model_copy(update={"intent_sha256": changed.recompute_sha256()})
        if problem != "appended_foreign_claim":
            intent_path.unlink()
            outcome_path.unlink()
            for path in records.root.glob("knowledge-execution-records-*.json"):
                path.unlink()
        executions = tuple(
            KnowledgeExecutionRecord.create(
                intent_sha256=changed.intent_sha256, observation=value.observation
            )
            for value in outcome.executions
        )
        rewritten = KnowledgeInvocationOutcome.create(
            intent=changed,
            state="FAILED",
            failure=outcome.failure,
            executions=executions,
            completed_at=outcome.completed_at,
        )
        records.put(
            "knowledge-invocation-intents", changed.binding.run_id + ":" + changed.phase, changed
        )
        records.put(
            "knowledge-invocation-outcomes", changed.binding.run_id + ":" + changed.phase, rewritten
        )
        for record in executions:
            records.put("knowledge-execution-records", record.record_sha256, record)
    with pytest.raises((ValueError, KnowledgeError)):
        facts.collector._invocations(facts.task, (facts.item,), (), ())


def test_later_start_cannot_borrow_a_valid_claim_returned_under_a_foreign_lease_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = knowledge_failure(tmp_path)
    later = _claim(
        facts.item.model_copy(update={"dispatch_sequence": 1}), "lease_real_later"
    ).model_copy(update={"claimed_at": NOW + timedelta(seconds=10)})
    later = QueueClaim.model_validate(later.to_wire())
    original_lookup = facts.collector.queue.original_claim

    def aliased_lookup(identity: str) -> QueueClaim:
        return later if identity == "lease_nonexistent_alias" else original_lookup(identity)

    monkeypatch.setattr(facts.collector.queue, "original_claim", aliased_lookup)
    request = AgentRequest(
        run_id="run_later_alias",
        task_id=facts.task.id,
        role=AgentRole.CODER,
        attempt=1,
        source_revision="a" * 40,
        context_manifest_id="ctx_" + "e" * 64,
        input_artifact_ids=(),
        permissions=facts.collector.permissions,
        output_schema="schemas/coder-output.schema.json",
        timeout_seconds=2,
    )
    start = DeliveryInvocationStart(
        work_item_id=facts.item.id,
        checkpoint_sequence=facts.item.checkpoint_sequence,
        request=request,
        lease_id="lease_nonexistent_alias",
        started_at=later.claimed_at,
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    KnowledgeRecordStore(facts.collector.state / "invocations").put(
        "invocation-starts",
        start.work_item_id,
        start,
    )
    with pytest.raises(ValueError, match="模型开始或结果"):
        facts.collector._capacity_input_reader().require_claim_not_started(
            UninvokedClaimBoundary(
                task_id=facts.task.id,
                work_item_id=facts.item.id,
                lease_id=facts.claim.lease.id,
                role=AgentRole.CODER,
                attempt=1,
                checkpoint_sequence=facts.item.checkpoint_sequence,
                dispatch_sequence=0,
                observed_at=facts.outcome.completed_at,
                run_id=facts.intent.binding.run_id,
                context_manifest_id=facts.intent.binding.context_manifest_id,
            ),
            allow_later_claims=True,
        )


def test_main_invocation_cannot_borrow_a_valid_claim_under_a_foreign_lease_key(
    tmp_path: Path,
) -> None:
    collector, task, item, receipt = reservation_fixture(tmp_path)
    task = task.model_copy(update={"id": item.task_id})
    actual = _claim(item, "lease_real_main")
    alias = _claim(item, receipt.claim_lease_id)
    step = QueuedRoleStep(
        work_item=item,
        boundary=RoleRunBoundary(
            task.id,
            AgentRole.CODER,
            item.attempt,
            item.checkpoint_sequence,
            receipt.request.source_revision,
        ),
        allocation_sha256="b" * 64,
    )

    class Queue(MySqlRoleQueue):
        def __init__(self) -> None:
            pass

        def claims_for_work_item(self, identity: str) -> tuple[QueueClaim, ...]:
            assert identity == item.id
            return (alias,)

        def original_claim(self, identity: str) -> QueueClaim:
            assert identity == receipt.claim_lease_id
            return actual

        def step_for_invocation(self, identity: str, baseline: str | None) -> QueuedRoleStep:
            assert identity == item.id
            return step

    collector.queue = Queue()
    collector.allocation = _allocation(task, "b" * 64)
    with pytest.raises(ValueError, match="真实历史 claim"):
        collector._invocations(task, (item,), (receipt,), ())


@pytest.mark.parametrize(
    "namespace", ["knowledge-invocation-outcomes", "knowledge-execution-records"]
)
def test_missing_independent_knowledge_record_refuses_baseline(
    tmp_path: Path, namespace: str
) -> None:
    facts = knowledge_failure(tmp_path)
    next(facts.records.root.glob(namespace + "-*.json")).unlink()
    with pytest.raises((ValueError, KnowledgeError)):
        facts.collector._invocations(facts.task, (facts.item,), (), ())


@pytest.mark.mysql
def test_public_baseline_after_real_knowledge_failure_preserves_original_delivery(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real structured HTTP failure, next claimed capacity stop, exact PAUSE/RESUME."""
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    capacity = True
    preparation: list[AgentRequest] = []
    invoked: list[AgentRequest] = []
    failed_once = False

    original_build = KnowledgeRunContextBuilder.build

    class RecordedClients:
        def for_project(
            self, repository_root: Path, role: TeamRole
        ) -> FallbackStructuredModelClient:
            scripted = _ScriptedClientFactory().for_project(repository_root, role)

            class Client:
                def complete(
                    self,
                    *,
                    instructions: str,
                    input_payload: Mapping[str, object],
                    output_schema: Mapping[str, object],
                    timeout_seconds: int,
                    input_images: tuple[Path, ...] = (),
                ) -> StructuredModelResult:
                    result = scripted.complete(
                        instructions=instructions,
                        input_payload=input_payload,
                        output_schema=output_schema,
                        timeout_seconds=timeout_seconds,
                        input_images=input_images,
                    )
                    payload = {
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": json.dumps(dict(result.payload)),
                                    }
                                ],
                            }
                        ]
                    }
                    transport = _HttpTransport(
                        HttpResponse(status_code=200, body=json.dumps(payload).encode()),
                        before_return=lambda: None,
                    )
                    return _http_client(transport, "fixture-model").complete(
                        instructions=instructions,
                        input_payload=input_payload,
                        output_schema=output_schema,
                        timeout_seconds=timeout_seconds,
                        input_images=input_images,
                    )

            return FallbackStructuredModelClient(
                (
                    StructuredModelRoute(
                        provider="fixture",
                        model="fixture-model",
                        client=Client(),
                    ),
                ),
                role=role,
            )

    def prepare(
        self: KnowledgeRunContextBuilder,
        task: Task,
        agent: AgentDefinition,
        *,
        attempt: int,
        candidate_revision: str | None = None,
        input_artifacts: tuple[Artifact, ...] = (),
    ) -> ContextBundle:
        nonlocal failed_once
        base = self.delegate.build(
            task,
            agent,
            attempt=attempt,
            candidate_revision=candidate_revision,
            input_artifacts=input_artifacts,
        )
        if failed_once or agent.role is not AgentRole.CODER:
            self.clients = RecordedClients()
            return original_build(
                self,
                task,
                agent,
                attempt=attempt,
                candidate_revision=candidate_revision,
                input_artifacts=input_artifacts,
            )
        failed_once = True
        frozen = KnowledgeSnapshot.create(
            team_id=self.team_id,
            project_id=self.project_id,
            requirement_id=task.id,
            repository_ids=(self.repository_id,),
        )
        self.records.put("snapshots", frozen.snapshot_sha256, frozen)
        bound = KnowledgeRunBinding(
            run_id="run_knowledge_" + digest((base.context_id, frozen.snapshot_sha256))[:32],
            task_id=task.id,
            role=TeamRole.CODER,
            team_id=self.team_id,
            project_id=self.project_id,
            requirement_id=task.id,
            repository_ids=(self.repository_id,),
            source_revision=base.source_revision,
            context_manifest_id=base.context_id,
            snapshot_sha256=frozen.snapshot_sha256,
        )
        transport = _HttpTransport(
            HttpResponse(status_code=503, body=b'{"error":{"message":"Unavailable"}}'),
            before_return=lambda: None,
        )
        client = FallbackStructuredModelClient(
            (
                StructuredModelRoute(
                    provider="fixture",
                    model="fixture-model",
                    client=_http_client(transport, "fixture-model"),
                ),
            ),
            role=TeamRole.CODER,
        )
        with model_call_phase("knowledge_assessment"):
            KnowledgeInvocationJournal(self.records, claimed=self.invocation_claim).call(
                bound,
                "assessment",
                client=client,
                instructions="Read-only preparation",
                input_payload={},
                output_schema={"type": "object", "properties": {}},
                timeout_seconds=2,
            )
        raise AssertionError("the real HTTP 503 preparation must fail before main invocation")

    monkeypatch.setattr(KnowledgeRunContextBuilder, "build", prepare)
    host = public_capacity_host(
        tmp_path=tmp_path,
        repository=repository,
        mysql_dsn=mysql_dsn,
        monkeypatch=monkeypatch,
        preparation_requests=preparation,
        invoked=invoked,
        should_reject=lambda request: request.role is AgentRole.CODER and capacity,
    )
    entry = host.project_entry()
    product = entry.start(
        StartProjectDelivery(repository_root=str(repository), requirement="Update the greeting.")
    ).checkpoint
    checkpoint = entry.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-product",
        )
    ).checkpoint
    assert checkpoint.task_id is not None
    tasks = MySqlTaskRepository(mysql_dsn)
    try:
        original = tasks.get(checkpoint.task_id)
        events = tasks.list_events(original.id)
        revision = tasks.current_revision(original.id)
        assert original.attempts == 2 and not invoked
        assert original.retry_failures is not None and len(original.retry_failures) == 1
        current = max(host.work_queue.items_for_task(original.id), key=lambda item: item.attempt)
        assert current.wait_disposition is not None
        assert current.wait_disposition.facts.classification == "CONTEXT_CAPACITY"
        (repository / "platform.txt").write_text("new source prerequisite\n")
        _git("add", "platform.txt", cwd=repository)
        _git("commit", "-m", "new platform baseline", cwd=repository)
        target = _git_output("rev-parse", "HEAD", cwd=repository)
        plan = host.propose_execution_baseline(
            BaselineProposeCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=original.id,
                expected_task_intent_sha256=task_intent_sha256(original),
                expected_task_revision=revision,
                expected_work_item_id=current.id,
                expected_source_revision=current.wait_disposition.facts.source_revision,
                target_base_ref=target,
            ),
            project_id="project_test",
        )
        sidecar = host.projects()[0].root / "repositories" / checkpoint.repository_id
        proof = KnowledgeRecordStore(
            sidecar / "state/execution-baselines" / original.id,
            read_only=True,
        ).get("baseline-quiescence", plan.facts.quiescence_proof_sha256, BaselineQuiescenceProof)
        assert [
            value.proof_kind
            for value in sorted(
                proof.invocations, key=lambda value: value.work_item_id == current.id
            )
        ] == ["claimed_knowledge_failure", "claimed_context_capacity"]
        assert plan.facts.continuation is not None
        assert plan.facts.continuation.current_attempt == 2
        binding = host.execute_execution_baseline(
            BaselineExecuteCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=original.id,
                expected_plan_sha256=plan.plan_sha256,
                reference="exact-pause",
                continuation_mode=BaselineContinuationMode.PAUSE,
            ),
            project_id="project_test",
        )
        assert tasks.get(original.id) == original and tasks.list_events(original.id) == events
        paused = host.work_queue.get(current.id)
        assert paused.wait_disposition is not None
        capacity = False
        host.continue_execution_baseline(
            BaselineContinueCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=original.id,
                expected_task_intent_sha256=task_intent_sha256(original),
                expected_task_revision=revision,
                expected_work_item_id=paused.id,
                expected_source_revision=binding.execution_source_revision,
                expected_execution_baseline_sha256=binding.binding_sha256,
                expected_disposition_sha256=paused.wait_disposition.disposition_sha256,
                reference="exact-resume",
            ),
            project_id="project_test",
        )
        delivered = entry.status(checkpoint.delivery_id).checkpoint
        assert delivered.stage is DeliveryStage.DONE and delivered.task_id == original.id
        final = tasks.get(original.id)
        assert final.attempts == 2 and final.retry_failures == original.retry_failures
        assert [request.role for request in invoked] == [
            AgentRole.CODER,
            AgentRole.QA,
            AgentRole.REVIEWER,
        ]
        assert (
            len(
                {
                    claim.assignment.agent_id
                    for item in host.work_queue.items_for_task(original.id)
                    for claim in host.work_queue.claims_for_work_item(item.id)
                }
            )
            == 3
        )
    finally:
        tasks.close()
