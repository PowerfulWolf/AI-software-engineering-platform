"""Current inspection of returned preparations behind an exact prior call fence."""

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.agents import AgentRequest, AgentResult, AgentRunStatus
from ai_software_engineer.agents.models import AgentErrorCode, AgentFailure
from ai_software_engineer.artifacts import seal_artifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.capacity_input_reader import PriorInvocationFence
from ai_software_engineer.manager.knowledge_invocation_proof import (
    ReplayGuardedClaimObservation,
    read_replay_guarded_claims,
)
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationScope,
    ExecutionCaptureStart,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim
from tests.domain.factories import make_coder_progress_artifact, make_plan_artifact
from tests.manager.test_baseline_knowledge_claim_proof import Facts, knowledge_failure
from tests.manager.test_execution_baseline_invocations import _claim


@dataclass(frozen=True)
class ReplayFacts:
    facts: Facts
    prior: QueueClaim
    start: DeliveryInvocationStart
    records: KnowledgeRecordStore


def replay_facts(tmp_path: Path) -> ReplayFacts:
    facts = knowledge_failure(tmp_path, returned=True, dispatch_sequence=1)
    prior = _claim(facts.item.model_copy(update={"dispatch_sequence": 0}), "lease_prior_call")
    prior = prior.model_copy(update={"claimed_at": facts.claim.claimed_at - timedelta(seconds=10)})
    original_queue = facts.collector.queue

    class Queue(MySqlRoleQueue):
        def __init__(self) -> None:
            pass

        def original_claim(self, lease_id: str) -> QueueClaim:
            return prior if lease_id == prior.lease.id else original_queue.original_claim(lease_id)

        def step_for_claim(self, claim: QueueClaim) -> QueuedRoleStep:
            return original_queue.step(facts.item.id).model_copy(
                update={"work_item": claim.work_item}
            )

        def step_for_invocation(self, identity: str, baseline: str | None) -> QueuedRoleStep:
            return original_queue.step_for_invocation(identity, baseline)

    facts.collector.queue = Queue()
    request = AgentRequest(
        run_id="run_prior_unknown",
        task_id=facts.task.id,
        role=facts.item.role,
        attempt=facts.item.attempt,
        source_revision="a" * 40,
        context_manifest_id="ctx_" + "a" * 64,
        input_artifact_ids=(),
        permissions=facts.collector.permissions,
        output_schema="schemas/coder-output.schema.json",
        timeout_seconds=2,
    )
    start = DeliveryInvocationStart(
        work_item_id=facts.item.id,
        checkpoint_sequence=facts.item.checkpoint_sequence,
        request=request,
        lease_id=prior.lease.id,
        started_at=prior.claimed_at + timedelta(seconds=1),
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    records = KnowledgeRecordStore(facts.collector.state / "invocations")
    records.put("invocation-starts", facts.item.id, start)
    return ReplayFacts(facts, prior, start, records)


def observe(
    fixture: ReplayFacts, *, start: DeliveryInvocationStart | None = None
) -> tuple[ReplayGuardedClaimObservation, ...]:
    facts = fixture.facts
    return read_replay_guarded_claims(
        state=facts.collector.state,
        task=facts.task,
        item=facts.item,
        claims=(facts.claim,),
        scope=facts.collector.scope,
        requirement_id=facts.collector.requirement_id,
        queue=facts.collector.queue,
        require_step=facts.collector._require_step,
        no_start_reader=facts.collector._capacity_input_reader(),
        fence=PriorInvocationFence(start or fixture.start),
    )


def test_current_replay_observation_preserves_all_historical_bytes(tmp_path: Path) -> None:
    fixture = replay_facts(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    (proof,) = observe(fixture)
    proof.validate_integrity()
    Draft202012Validator(
        json.loads(
            (
                Path(__file__).parents[2] / "schemas/replay-guarded-claim-observation.schema.json"
            ).read_text()
        )
    ).validate(proof.to_wire())
    assert proof.blocking_start_sha256 == fixture.start.start_sha256
    assert proof.lease_id == fixture.facts.claim.lease.id
    assert proof.outcome_sha256s == (fixture.facts.outcome.outcome_sha256,)
    assert proof.context_sha256s and "refused_at" not in proof.to_wire()
    assert observe(fixture) == (proof,)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*.json")}


@pytest.mark.parametrize(
    "problem",
    [
        "same_lease",
        "late_start",
        "same_dispatch",
        "alias_prior",
        "alias_current",
        "different_start",
        "missing_start",
        "outcome",
        "raw_artifact",
        "capture",
        "unfinished_knowledge",
        "missing_knowledge_outcome",
    ],
)
def test_replay_observation_refuses_ambiguous_or_later_execution_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    fixture = replay_facts(tmp_path)
    facts, start = fixture.facts, fixture.start
    if problem in {"same_lease", "late_start", "different_start"}:
        changes: dict[str, dict[str, object]] = {
            "same_lease": {"lease_id": facts.claim.lease.id},
            "late_start": {"started_at": facts.claim.claimed_at + timedelta(seconds=1)},
            "different_start": {"work_item_id": "work_foreign_observation"},
        }
        start = start.model_copy(update=changes[problem])
        start = start.model_copy(
            update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
        )
    elif problem in {"same_dispatch", "alias_prior", "alias_current"}:
        original = facts.collector.queue.original_claim

        def changed(identity: str) -> QueueClaim:
            if problem == "alias_prior" and identity == fixture.prior.lease.id:
                return facts.claim
            if problem == "alias_current" and identity == facts.claim.lease.id:
                return fixture.prior
            result = original(identity)
            return (
                result.model_copy(
                    update={
                        "work_item": result.work_item.model_copy(update={"dispatch_sequence": 1})
                    }
                )
                if identity == fixture.prior.lease.id
                else result
            )

        monkeypatch.setattr(facts.collector.queue, "original_claim", changed)
    elif problem == "missing_start":
        (fixture.records.root / fixture.records._name("invocation-starts", facts.item.id)).unlink()
    elif problem == "outcome":
        request = start.request
        outcome = DeliveryInvocationOutcome(
            start=start,
            result=AgentResult(
                run_id=request.run_id,
                task_id=request.task_id,
                role=request.role,
                attempt=request.attempt,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                status=AgentRunStatus.FAILED,
                error=AgentFailure(
                    code=AgentErrorCode.PROVIDER_ERROR, message="old failure", transient=False
                ),
            ),
            outcome_sha256="0" * 64,
        )
        outcome = outcome.model_copy(
            update={
                "outcome_sha256": digest(
                    outcome.model_dump(mode="json", exclude={"outcome_sha256"})
                )
            }
        )
        fixture.records.put("invocation-outcomes", facts.item.id, outcome)
    elif problem == "raw_artifact":
        store = facts.collector.capacity_artifacts
        plan = make_plan_artifact().model_copy(update={"task_id": facts.task.id})
        store.put(seal_artifact(plan, validated_at=facts.outcome.completed_at))
        progress = make_coder_progress_artifact()
        progress = progress.model_copy(
            update={
                "task_id": facts.task.id,
                "context_manifest_id": facts.intent.binding.context_manifest_id,
                "producer": progress.producer.model_copy(update={"run_id": "run_new_unexpected"}),
            }
        )
        store.put(seal_artifact(progress, validated_at=facts.outcome.completed_at))
    elif problem == "capture":
        request = start.request.model_copy(
            update={
                "run_id": "run_new_unexpected",
                "context_manifest_id": facts.intent.binding.context_manifest_id,
            }
        )
        capture = ExecutionCaptureStart.create(
            scope=ContinuationScope(
                **facts.collector.scope.model_dump(exclude={"repository_root"}),
                requirement_id=facts.collector.requirement_id,
                dispatch_sha256="b" * 64,
            ),
            request=request,
            claim=facts.claim,
            task_intent_sha256=task_intent_sha256(facts.task),
            task_revision=facts.item.checkpoint_sequence,
            policy_sha256="c" * 64,
            worktree_path=facts.task.repository,
            inventory_before=capture_mutation_inventory(Path(facts.task.repository)),
            started_at=facts.outcome.completed_at,
        )
        root = facts.collector.state / "continuations" / facts.task.id
        root.mkdir(parents=True, mode=0o700)
        FileContinuationStore(root, task_id=facts.task.id).put_capture_start(capture)
    elif problem == "unfinished_knowledge":
        execution = facts.outcome.executions[-1]
        (
            facts.records.root
            / facts.records._name("knowledge-execution-records", execution.record_sha256)
        ).unlink()
    else:
        (
            facts.records.root
            / facts.records._name(
                "knowledge-invocation-outcomes",
                facts.intent.binding.run_id + ":" + facts.intent.phase,
            )
        ).unlink()
    with pytest.raises((ValueError, KnowledgeError)):
        observe(fixture, start=start)
