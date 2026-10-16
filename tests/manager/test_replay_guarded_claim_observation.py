"""Current inspection of returned preparations behind an exact prior call fence."""

import json
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.agents import AgentRequest, AgentResult, AgentRunStatus
from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import AgentErrorCode, AgentFailure
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.git.mutation_capture import WorktreeMutationCapture
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.capacity_input_reader import (
    CapacityInputReader,
    PriorInvocationFence,
    UninvokedClaimBoundary,
)
from ai_software_engineer.manager.knowledge_invocation_proof import (
    ReplayGuardedClaimObservation,
    read_replay_guarded_claims,
)
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationAdmission,
    ContinuationRejected,
    ContinuationScope,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
    ExecutionInterruptionReceipt,
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
from tests.orchestration.test_continuation_records import make_admission, make_receipt
from tests.work_queue.test_mysql_queue import queued_item


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


@dataclass(frozen=True)
class IncomingAdmissionFacts:
    reader: CapacityInputReader
    marker: UninvokedClaimBoundary
    fence: PriorInvocationFence
    native: FileContinuationStore
    admission: ContinuationAdmission

    def read(self, fence: PriorInvocationFence | None = None) -> None:
        self.reader.require_claim_not_started(
            self.marker, prior_invocation_fence=fence or self.fence
        )


def incoming_admission_facts(tmp_path: Path) -> IncomingAdmissionFacts:
    receipt = make_receipt(tmp_path)
    mutations = CapturedMutations.from_capture(
        WorktreeMutationCapture(
            worktree=receipt.capture.to_capture().worktree,
            patch=b"",
            index_diff_sha256=receipt.capture.index_diff_sha256,
            mutations=(),
        )
    )
    empty = receipt.inventory_before
    receipt = ExecutionInterruptionReceipt.create(
        **{
            **receipt.to_wire(),
            "schema_version": "v2",
            "capture": mutations,
            "inventory_after": empty,
            "inventory_after_sha256": empty.sha256,
            "mutation_paths": (),
        }
    )
    admission = ContinuationAdmission.create(
        **{
            **make_admission(receipt).to_wire(),
            "schema_version": "v2",
            "interrupted_attempt": 1,
        }
    )
    admission = admission.model_copy(
        update={"created_at": admission.created_at + timedelta(hours=1)}
    )
    admission = admission.model_copy(update={"admission_sha256": admission.recompute_sha256()})
    request = admission.new_request
    item = queued_item(
        "incoming",
        attempt=request.attempt,
        checkpoint_sequence=3,
        parent=receipt.original_work_item_id,
    ).model_copy(
        update={
            "id": admission.next_work_item_id,
            "task_id": request.task_id,
            "repository_id": admission.scope.repository_id,
        }
    )
    prior = _claim(item, admission.next_lease_id).model_copy(
        update={
            "claimed_at": admission.created_at - timedelta(seconds=1),
        }
    )
    current = _claim(
        item.model_copy(update={"dispatch_sequence": 1}), "lease_current_guard"
    ).model_copy(
        update={
            "claimed_at": admission.created_at + timedelta(seconds=3),
        }
    )
    start = DeliveryInvocationStart(
        work_item_id=item.id,
        checkpoint_sequence=item.checkpoint_sequence,
        request=request,
        lease_id=prior.lease.id,
        started_at=admission.created_at - timedelta(milliseconds=500),
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    root = tmp_path / "sidecar"
    state = root / "state"
    records = KnowledgeRecordStore(state / "invocations")
    records.put("invocation-starts", item.id, start)
    capture = ExecutionCaptureStart.create(
        scope=admission.scope,
        request=request,
        claim=prior,
        task_intent_sha256=receipt.task_intent_sha256,
        task_revision=item.checkpoint_sequence,
        policy_sha256=receipt.policy_sha256,
        worktree_path=receipt.capture.worktree_path,
        inventory_before=receipt.inventory_after,
        started_at=admission.created_at + timedelta(seconds=1),
    )
    stop = ExecutionCaptureStop.create(
        task_id=request.task_id,
        run_id=request.run_id,
        capture_start_sha256=capture.start_sha256,
        cause=None,
        original_error_code=AgentErrorCode.PROVIDER_ERROR,
        process_stop=NativeProcessStop.create(
            process_id=12346,
            group_id=12346,
            returncode=-15,
            kind="failed",
            stopped_at=capture.started_at + timedelta(seconds=1),
        ),
        output_present=False,
    )
    (state / "continuations").mkdir()
    native = FileContinuationStore.initialize(
        state / "continuations" / request.task_id, task_id=request.task_id
    )
    native.put_receipt(receipt)
    native.put_admission(admission)
    native.put_capture_start(capture)
    native.put_capture_stop(stop)

    class Queue:
        def original_claim(self, lease_id: str) -> QueueClaim:
            if lease_id == prior.lease.id:
                return prior
            assert lease_id == current.lease.id
            return current

        def step_for_invocation(self, identity: str, baseline: str | None) -> QueuedRoleStep:
            from ai_software_engineer.orchestration.steps import RoleRunBoundary

            assert identity == item.id and baseline == request.execution_baseline_sha256
            return QueuedRoleStep(
                work_item=item,
                boundary=RoleRunBoundary(
                    request.task_id,
                    AgentRole.CODER,
                    request.attempt,
                    item.checkpoint_sequence,
                    request.source_revision,
                ),
                allocation_sha256=admission.scope.dispatch_sha256,
            )

    reader = CapacityInputReader(
        state=state,
        queue=Queue(),
        artifacts=FileArtifactStore(root / "artifacts"),
        route_root=root / "model-routes",
        baselines=None,
        permissions=request.permissions,
    )
    marker = UninvokedClaimBoundary(
        task_id=request.task_id,
        work_item_id=item.id,
        lease_id=current.lease.id,
        role=AgentRole.CODER,
        attempt=request.attempt,
        checkpoint_sequence=item.checkpoint_sequence,
        dispatch_sequence=current.work_item.dispatch_sequence,
        observed_at=current.claimed_at + timedelta(seconds=1),
        run_id="run_guard_knowledge_only",
        context_manifest_id="ctx_" + "f" * 64,
    )
    return IncomingAdmissionFacts(
        reader, marker, PriorInvocationFence(start, capture, stop), native, admission
    )


def test_exact_incoming_native_admission_preserves_prior_unknown_and_bytes(tmp_path: Path) -> None:
    fixture = incoming_admission_facts(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    fixture.read()
    fixture.read()
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}


def _write_native(path: Path, value: DomainModel) -> None:
    # Deliberately build self-consistent hostile fixture envelopes: a valid
    # envelope digest must not override the independently proven call identity.
    record = value.to_wire()
    path.write_text(json.dumps({"record": record, "sha256": digest(record)}))


@pytest.mark.parametrize(
    "problem",
    [
        "no-fence",
        "no-capture-start",
        "no-capture-stop",
        "missing-receipt",
        "request-run",
        "request-context",
        "request-source",
        "request-permissions",
        "work-item",
        "lease",
        "current-lease",
        "canonical-admission",
        "receipt-digest",
        "admission-scope",
        "admission-policy",
        "before-start",
        "after-capture",
        "after-guard",
        "capture-after-guard",
        "capture-policy",
        "capture-scope",
        "capture-intent",
        "parent-work-item",
        "current-native-capture",
        "outgoing-admission",
        "late-artifact",
    ],
)
def test_incoming_admission_does_not_weaken_other_execution_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    fixture = incoming_admission_facts(tmp_path)
    reader, marker, native = fixture.reader, fixture.marker, fixture.native
    fence: PriorInvocationFence | None = fixture.fence
    admission, start = fixture.admission, fixture.fence.start
    capture, stop = fixture.fence.capture_start, fixture.fence.capture_stop
    assert capture is not None and stop is not None
    root = reader.state / "continuations" / marker.task_id
    admission_path = root / f"admission-{admission.new_request.run_id}.json"
    if problem == "no-fence":
        fence = None
    elif problem == "no-capture-start":
        fence = replace(fixture.fence, capture_start=None)
    elif problem == "no-capture-stop":
        fence = replace(fixture.fence, capture_stop=None)
    elif problem == "missing-receipt":
        (root / f"receipt-{admission.interrupted_run_id}.json").unlink()
    elif problem.startswith("request-"):
        request = admission.new_request
        if problem == "request-run":
            request = request.model_copy(update={"run_id": "run_aliased_incoming"})
        elif problem == "request-context":
            request = request.model_copy(update={"context_manifest_id": "ctx_" + "e" * 64})
        elif problem == "request-source":
            request = request.model_copy(update={"source_revision": "e" * 40})
        else:
            request = request.model_copy(
                update={
                    "permissions": request.permissions.model_copy(update={"write_paths": ("**",)})
                }
            )
        admission = admission.model_copy(update={"new_request": request})
    elif problem in {"work-item", "lease", "current-lease"}:
        admission = admission.model_copy(
            update={
                "next_work_item_id" if problem == "work-item" else "next_lease_id": (
                    "work_aliased_incoming"
                    if problem == "work-item"
                    else marker.lease_id
                    if problem == "current-lease"
                    else "lease_aliased_incoming"
                ),
            }
        )
    elif problem == "canonical-admission":
        monkeypatch.setattr(FileContinuationStore, "admission_for_run", lambda *_: None)
    elif problem == "receipt-digest":
        admission = admission.model_copy(update={"receipt_sha256": "e" * 64})
    elif problem == "admission-scope":
        admission = admission.model_copy(
            update={
                "scope": admission.scope.model_copy(update={"requirement_id": "delivery_aliased"})
            }
        )
    elif problem == "admission-policy":
        admission = admission.model_copy(update={"policy_sha256": "e" * 64})
    elif problem in {"before-start", "after-capture", "after-guard"}:
        admission = admission.model_copy(
            update={
                "created_at": (
                    start.started_at - timedelta(milliseconds=1)
                    if problem == "before-start"
                    else capture.started_at + timedelta(milliseconds=1)
                    if problem == "after-capture"
                    else reader.queue.original_claim(marker.lease_id).claimed_at
                    + timedelta(milliseconds=1)
                )
            }
        )
    elif problem in {
        "capture-after-guard",
        "capture-policy",
        "capture-scope",
        "capture-intent",
        "parent-work-item",
    }:
        if problem == "capture-after-guard":
            capture = capture.model_copy(
                update={"started_at": reader.queue.original_claim(marker.lease_id).claimed_at}
            )
        elif problem == "capture-policy":
            capture = capture.model_copy(update={"policy_sha256": "e" * 64})
        elif problem == "capture-scope":
            capture = capture.model_copy(
                update={
                    "scope": capture.scope.model_copy(update={"requirement_id": "delivery_aliased"})
                }
            )
        elif problem == "capture-intent":
            capture = capture.model_copy(update={"task_intent_sha256": "e" * 64})
        else:
            changed = capture.claim.model_copy(
                update={
                    "work_item": capture.claim.work_item.model_copy(
                        update={"parent_work_item_id": "work_aliased_parent"}
                    )
                }
            )
            capture = capture.model_copy(update={"claim": changed})
            original_claim = reader.queue.original_claim
            monkeypatch.setattr(
                reader.queue,
                "original_claim",
                lambda identity: (
                    changed if identity == start.lease_id else original_claim(identity)
                ),
            )
        capture = capture.model_copy(update={"start_sha256": capture.recompute_sha256()})
        stop = stop.model_copy(update={"capture_start_sha256": capture.start_sha256})
        stop = stop.model_copy(update={"observation_sha256": stop.recompute_sha256()})
        _write_native(root / f"capture-start-{start.request.run_id}.json", capture)
        _write_native(root / f"capture-stop-{start.request.run_id}.json", stop)
        fence = replace(fixture.fence, capture_start=capture, capture_stop=stop)
    elif problem == "current-native-capture":
        current = reader.queue.original_claim(marker.lease_id)
        native.put_capture_start(
            ExecutionCaptureStart.create(
                **{
                    **capture.to_wire(),
                    "request": start.request.model_copy(
                        update={
                            "run_id": marker.run_id,
                            "context_manifest_id": marker.context_manifest_id,
                        }
                    ),
                    "claim": current,
                    "started_at": current.claimed_at,
                }
            )
        )
    elif problem == "outgoing-admission":
        receipt = native.get_receipt(admission.interrupted_run_id)
        process_stop = NativeProcessStop.create(
            process_id=12346,
            group_id=12346,
            returncode=-15,
            kind="local_execution_limit",
            stopped_at=stop.process_stop.stopped_at,
        )
        outgoing_receipt = ExecutionInterruptionReceipt.create(
            **{
                **receipt.to_wire(),
                "request": start.request,
                "original_work_item_id": start.work_item_id,
                "claim_lease_id": start.lease_id,
                "task_revision": start.checkpoint_sequence,
                "process_stop": process_stop,
                "process_stop_sha256": process_stop.stop_sha256,
                "created_at": process_stop.stopped_at,
                "previous_admission_sha256": admission.admission_sha256,
            }
        )
        native.put_receipt(outgoing_receipt)
        native.put_admission(
            ContinuationAdmission.create(
                **{
                    **admission.to_wire(),
                    "interrupted_run_id": start.request.run_id,
                    "receipt_sha256": outgoing_receipt.receipt_sha256,
                    "interrupted_attempt": start.request.attempt,
                    "new_request": start.request.model_copy(
                        update={
                            "run_id": "run_outgoing_successor",
                            "attempt": start.request.attempt + 1,
                            "context_manifest_id": "ctx_" + "e" * 64,
                        }
                    ),
                    "next_work_item_id": "work_outgoing_successor",
                    "next_lease_id": "lease_outgoing_successor",
                    "created_at": process_stop.stopped_at + timedelta(milliseconds=1),
                }
            )
        )
    else:
        reader.artifacts.put(
            seal_artifact(
                make_plan_artifact().model_copy(update={"task_id": marker.task_id}),
                validated_at=marker.observed_at,
            )
        )
        artifact = make_coder_progress_artifact()
        reader.artifacts.put(
            seal_artifact(
                artifact.model_copy(
                    update={
                        "task_id": marker.task_id,
                        "context_manifest_id": marker.context_manifest_id,
                    }
                ),
                validated_at=marker.observed_at,
            )
        )
    if admission != fixture.admission:
        admission = admission.model_copy(update={"admission_sha256": admission.recompute_sha256()})
        _write_native(admission_path, admission)
    with pytest.raises((ValueError, KnowledgeError, ContinuationRejected)):
        reader.require_claim_not_started(marker, prior_invocation_fence=fence)


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
