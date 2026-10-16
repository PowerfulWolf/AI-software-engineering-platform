"""Semantic model refusals retain exact output and independently verifiable reads."""

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured import StructuredModelError, StructuredModelResult
from ai_software_engineer.agents.structured_observation import (
    StructuredExecutionAdmission,
    StructuredNativeStopReceipt,
)
from ai_software_engineer.context import (
    ContextBundle,
    ContextSource,
    FileContextBuilder,
    FileContextStore,
)
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.assessment_rejection import (
    KnowledgeAssessmentRejected,
    RejectedAssessmentUnavailable,
    RejectedKnowledgeAssessment,
    derive_rejected_assessment,
    read_rejected_assessment,
)
from ai_software_engineer.knowledge.assessment_validation import (
    KnowledgeAssessment,
    assessment_rejection_reason,
)
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.knowledge.diagnostics import knowledge_error_code
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord,
    KnowledgeInvocationIntent,
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    KnowledgeInvocationUncertain,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeEvidence,
    KnowledgeRunBinding,
    KnowledgeRunManifest,
    KnowledgeSnapshot,
    digest,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from tests.agents.test_openai_compatible import _coder_request
from tests.domain.factories import make_task
from tests.knowledge.test_consultation import Model
from tests.knowledge.test_invocation_native import _actual_claim, _client
from tests.knowledge.test_retrieval_contract import binding, document, snapshot


class UnreadCitationModel(Model):
    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        if output_schema["title"] == "KnowledgeAssessment":
            self.calls.append("KnowledgeAssessment")
            evidence = tuple(
                KnowledgeEvidence.model_validate(value)
                for value in cast(list[object], input_payload["knowledge_evidence"])
            )
            read = next(item.chunk for item in evidence if item.chunk is not None)
            return StructuredModelResult(
                payload={
                    "status": "GAP",
                    "gap_owner": "REPOSITORY",
                    "claims": [
                        {
                            "statement": "A claim from an unread document.",
                            "citations": [{**read.citation.to_wire(), "document_id": "doc_unread"}],
                        }
                    ],
                },
                duration_ms=1,
            )
        return super().complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )


def test_unread_citation_is_typed_nontransient_and_preserves_returned_bytes(
    tmp_path: Path,
) -> None:
    frozen = snapshot(document())
    bound = binding(frozen)
    records = KnowledgeRecordStore(tmp_path)
    model = UnreadCitationModel()
    service = KnowledgeConsultationService(model, records, allow_repository_inspection=True)
    saved: dict[str, bytes] | None = None
    for _ in range(2):
        with pytest.raises(StructuredModelError) as raised:
            service.consult(bound, frozen, {"task": "original"}, timeout_seconds=30)
        error = raised.value
        assert isinstance(error, KnowledgeAssessmentRejected)
        assert error.code is AgentErrorCode.INVALID_OUTPUT
        assert not error.transient and not error.retryable
        assert error.reason == "CLAIM_WITHOUT_READ"
        assert error.observation is None
        contextual = error.with_context("Coder / 知识充分性评估")
        assert contextual.reason == error.reason and contextual.observation is None
        if saved is None:
            saved = _bytes(tmp_path)
        else:
            assert _bytes(tmp_path) == saved
    assert model.calls == ["KnowledgeIntent", "KnowledgeAssessment"]
    lane = KnowledgeRecordStore(tmp_path / "invocations" / invocation_lane_sha256(bound))
    outcome = lane.get(
        "knowledge-invocation-outcomes", bound.run_id + ":assessment", KnowledgeInvocationOutcome
    )
    outcome.validate_integrity()
    assert outcome.state == "RETURNED" and outcome.failure is None
    assert outcome.result is not None and outcome.result.payload["status"] == "GAP"
    assert knowledge_error_code(KnowledgeError("CLAIM_WITHOUT_READ")) == "CLAIM_WITHOUT_READ"


@pytest.mark.parametrize("redaction", [False, True])
def test_shared_semantics_keep_exact_read_and_redaction_checks(redaction: bool) -> None:
    frozen = snapshot(document())
    bound = binding(frozen)
    provisional = KnowledgeRunManifest(
        binding=bound,
        snapshot_sha256=bound.snapshot_sha256,
        evidence_ids=(),
        citations=(),
        manifest_sha256="0" * 64,
    )
    manifest = provisional.model_copy(
        update={
            "manifest_sha256": digest(
                provisional.model_dump(mode="json", exclude={"manifest_sha256"})
            )
        }
    )
    secret = "sk-" + "A1b2C3d4" * 6
    assessment = KnowledgeAssessment(
        status="GAP", gap_owner="REPOSITORY", gap_question=secret if redaction else None
    )
    reason = assessment_rejection_reason(assessment, manifest)
    if redaction:
        assert reason == "ASSESSMENT_REQUIRES_REDACTION"
        refusal = KnowledgeAssessmentRejected(reason)
        assert secret not in refusal.safe_message
        assert not refusal.retryable and refusal.code is AgentErrorCode.INVALID_OUTPUT
        assert knowledge_error_code(KnowledgeError(reason)) == reason
    else:
        assert reason is None


def _native_executable(root: Path, *, unsafe: bool = False) -> Path:
    executable = root / "knowledge-fixture"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\nfrom pathlib import Path\n"
        "prompt = sys.stdin.read()\n"
        "payload = json.loads(prompt.split('\\nINPUT=', 1)[1])\n"
        "schema = json.loads(Path(sys.argv[sys.argv.index('--output-schema') + 1]).read_text())\n"
        "with Path('calls').open('a') as calls: calls.write(schema['title'] + '\\n')\n"
        "if schema['title'] == 'KnowledgeIntent':\n"
        "    result = {'queries': ['original payment']}\n"
        "else:\n"
        "    evidence = payload['knowledge_evidence']\n"
        "    reads = [item['chunk'] for item in evidence if item.get('chunk')]\n"
        "    citation = reads[0]['citation']\n"
        "    citation['document_id'] = 'doc_unread'\n"
        "    claim = {'statement': 'Unread fact', 'citations': [citation]}\n"
        "    result = {'status': 'GAP', 'gap_owner': 'REPOSITORY', 'claims': [claim]}\n"
        + ("    result['gap_question'] = 'sk-' + 'A1b2C3d4' * 6\n" if unsafe else "")
        + "output = Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
        "output.write_text(json.dumps(result))\n"
    )
    executable.chmod(0o700)
    return executable


@dataclass(frozen=True)
class NativeRejection:
    root: Path
    records: KnowledgeRecordStore
    bound: KnowledgeRunBinding
    observation: RejectedKnowledgeAssessment
    context: ContextBundle
    task: Task

    @property
    def lane(self) -> KnowledgeRecordStore:
        return KnowledgeRecordStore(
            self.records.root / "invocations" / invocation_lane_sha256(self.bound)
        )


@pytest.fixture
def native_rejection(tmp_path: Path) -> NativeRejection:
    frozen = snapshot(document())
    bound = binding(frozen)
    claim = _actual_claim(bound)
    task = make_task().model_copy(
        update={
            "id": bound.task_id,
            "repository": str(tmp_path),
            "base_ref": bound.source_revision,
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
        }
    )
    context = FileContextBuilder(
        tmp_path,
        _coder_request().permissions,
        sources=(
            ContextSource(
                source_id="execution.claim",
                uri="claim://" + claim.lease.id,
                content=json.dumps(
                    {
                        "task_id": task.id,
                        "work_item_id": claim.work_item.id,
                        "lease_id": claim.lease.id,
                        "assignment_id": claim.assignment.id,
                        "dispatch_sequence": claim.work_item.dispatch_sequence,
                        "role": AgentRole.CODER.value,
                        "attempt": claim.work_item.attempt,
                        "checkpoint_sequence": claim.work_item.checkpoint_sequence,
                    }
                ),
                required=True,
            ),
        ),
    ).build(task, AgentRole.CODER, attempt=1)
    FileContextStore(tmp_path / "contexts").put(context)
    bound = bound.model_copy(
        update={
            "context_manifest_id": context.context_id,
            "run_id": "run_knowledge_" + digest((context.context_id, frozen.snapshot_sha256))[:32],
        }
    )
    records = KnowledgeRecordStore(tmp_path / "knowledge" / "runs")
    records.put("snapshots", frozen.snapshot_sha256, frozen)
    service = KnowledgeConsultationService(
        _client(tmp_path, _native_executable(tmp_path), bound.role),
        records,
        allow_repository_inspection=True,
        invocation_journal=KnowledgeInvocationJournal(records, claimed=lambda: claim),
    )
    with pytest.raises(KnowledgeAssessmentRejected) as raised:
        service.consult(
            bound, frozen, {"task": task.to_wire(), "context": context.to_wire()}, timeout_seconds=5
        )
    observation = raised.value.observation
    assert observation is not None
    assert raised.value.with_context("Coder").observation == observation
    assert observation.reason == "CLAIM_WITHOUT_READ"
    return NativeRejection(tmp_path, records, bound, observation, context, task)


def _bytes(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*.json")}


def test_native_rejection_reopens_full_original_facts_without_mutation(
    native_rejection: NativeRejection,
) -> None:
    case = native_rejection
    observation = case.observation
    before = _bytes(case.root)
    for _ in range(2):
        assert derive_rejected_assessment(case.records.root, case.bound) == observation
        assert (
            read_rejected_assessment(case.records.root, observation.observation_sha256)
            == observation
        )
    frozen = case.records.get("snapshots", case.bound.snapshot_sha256, KnowledgeSnapshot)
    replay = KnowledgeConsultationService(
        _client(case.root, case.root / "knowledge-fixture", case.bound.role),
        case.records,
        allow_repository_inspection=True,
        invocation_journal=KnowledgeInvocationJournal(
            case.records, claimed=lambda: observation.original_claim
        ),
    )
    with pytest.raises(KnowledgeAssessmentRejected) as raised:
        replay.consult(
            case.bound,
            frozen,
            {
                "task": case.task.to_wire(),
                "context": case.context.to_wire(),
            },
            timeout_seconds=5,
        )
    assert raised.value.observation == observation
    assert _bytes(case.root) == before
    assert observation.original_claim_sha256 == claim_identity_sha256(observation.original_claim)
    assert observation.original_claim.work_item.task_id == observation.binding.task_id
    assert len(observation.intent_execution_record_sha256s) == 2
    assert len(observation.assessment_execution_record_sha256s) == 2
    assert observation.manifest.citations
    assert (case.root / "calls").read_text().splitlines() == [
        "KnowledgeIntent",
        "KnowledgeAssessment",
    ]
    for phase in ("intent", "assessment"):
        outcome = case.lane.get(
            "knowledge-invocation-outcomes",
            case.bound.run_id + ":" + phase,
            KnowledgeInvocationOutcome,
        )
        assert outcome.state == "RETURNED" and outcome.failure is None


def test_legacy_unowned_native_stop_does_not_grant_recovery(
    native_rejection: NativeRejection,
) -> None:
    case = native_rejection
    key = case.bound.run_id + ":assessment"
    outcome = case.lane.get("knowledge-invocation-outcomes", key, KnowledgeInvocationOutcome)
    original_record = outcome.executions[-1]
    original = original_record.observation
    assert isinstance(original, StructuredNativeStopReceipt)
    values = original.process_stop.model_dump(exclude={"session_proof", "stop_sha256"})
    legacy_stop = NativeProcessStop.create(**values)
    legacy_receipt = StructuredNativeStopReceipt.create(
        **original.model_dump(exclude={"process_stop", "receipt_sha256"}), process_stop=legacy_stop
    )
    changed_record = KnowledgeExecutionRecord.create(
        intent_sha256=original_record.intent_sha256, observation=legacy_receipt
    )
    case.lane.put("knowledge-execution-records", changed_record.record_sha256, changed_record)
    (
        case.lane.root
        / case.lane._name("knowledge-execution-records", original_record.record_sha256)
    ).unlink()
    changed = KnowledgeInvocationOutcome.create(
        **outcome.model_dump(exclude={"executions", "outcome_sha256"}),
        executions=(*outcome.executions[:-1], changed_record),
    )
    _replace_record(case.lane, "knowledge-invocation-outcomes", key, changed.to_wire())
    before = _bytes(case.root)
    with pytest.raises(RejectedAssessmentUnavailable, match="OWNED_STOP_REQUIRED"):
        derive_rejected_assessment(case.records.root, case.bound)
    assert _bytes(case.root) == before


@pytest.mark.parametrize("phase", ["intent", "assessment"])
def test_recomputed_request_refuses_self_consistently_resealed_wrong_input(
    native_rejection: NativeRejection,
    phase: str,
) -> None:
    case = native_rejection
    key = case.bound.run_id + ":" + phase
    outcome = case.lane.get("knowledge-invocation-outcomes", key, KnowledgeInvocationOutcome)
    intent = KnowledgeInvocationIntent.create(
        **outcome.intent.model_dump(exclude={"request_sha256", "intent_sha256"}),
        request_sha256="f" * 64,
    )
    admission_record, stopped_record = outcome.executions
    admission = admission_record.observation
    stopped = stopped_record.observation
    assert isinstance(admission, StructuredExecutionAdmission)
    assert isinstance(stopped, StructuredNativeStopReceipt)
    changed_admission = StructuredExecutionAdmission.create(
        **admission.model_dump(exclude={"call", "admission_sha256"}),
        call=admission.call.model_copy(update={"request_sha256": "f" * 64}),
    )
    changed_stop = StructuredNativeStopReceipt.create(
        **stopped.model_dump(exclude={"admission", "receipt_sha256"}),
        admission=changed_admission,
    )
    executions = tuple(
        KnowledgeExecutionRecord.create(
            intent_sha256=intent.intent_sha256,
            observation=value,
        )
        for value in (changed_admission, changed_stop)
    )
    for old, new in zip(outcome.executions, executions, strict=True):
        (
            case.lane.root / case.lane._name("knowledge-execution-records", old.record_sha256)
        ).unlink()
        case.lane.put("knowledge-execution-records", new.record_sha256, new)
    changed_outcome = KnowledgeInvocationOutcome.create(
        **outcome.model_dump(exclude={"intent", "executions", "outcome_sha256"}),
        intent=intent,
        executions=executions,
    )
    _replace_record(case.lane, "knowledge-invocation-intents", key, intent.to_wire())
    _replace_record(case.lane, "knowledge-invocation-outcomes", key, changed_outcome.to_wire())
    before = _bytes(case.root)
    with pytest.raises(KnowledgeError, match="REQUEST_CHANGED"):
        derive_rejected_assessment(case.records.root, case.bound)
    assert _bytes(case.root) == before


def _replace_record(records: KnowledgeRecordStore, namespace: str, key: str, value: object) -> None:
    """Deliberately self-consistent hostile envelope, beyond simple checksum tampering."""
    (records.root / records._name(namespace, key)).write_text(
        json.dumps({"record": value, "sha256": digest(value)}, ensure_ascii=False)
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-outcome",
        "missing-execution",
        "missing-evidence",
        "missing-operation",
        "missing-manifest",
        "snapshot",
        "input",
        "binding",
        "manifest",
        "claim",
        "reason",
        "additional-operation",
        "native-unknown",
        "extra-execution",
    ],
)
def test_reopen_refuses_changed_original_or_current_facts(
    native_rejection: NativeRejection, mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = native_rejection
    observation = case.observation
    if mutation == "missing-outcome":
        (
            case.lane.root
            / case.lane._name("knowledge-invocation-outcomes", case.bound.run_id + ":assessment")
        ).unlink()
    elif mutation == "missing-execution":
        identity = observation.assessment_execution_record_sha256s[0]
        (case.lane.root / case.lane._name("knowledge-execution-records", identity)).unlink()
    elif mutation == "missing-evidence":
        identity = observation.manifest.evidence_ids[0]
        (case.records.root / case.records._name("evidence", identity)).unlink()
    elif mutation == "missing-operation":
        (
            case.records.root
            / case.records._name("operations", case.bound.run_id + ":read_000_000")
        ).unlink()
    elif mutation == "missing-manifest":
        (
            case.records.root
            / case.records._name("manifests", observation.manifest.manifest_sha256)
        ).unlink()
    elif mutation == "snapshot":
        frozen = case.records.get("snapshots", case.bound.snapshot_sha256, KnowledgeSnapshot)
        _replace_record(
            case.records,
            "snapshots",
            case.bound.snapshot_sha256,
            frozen.model_copy(update={"documents": ()}).to_wire(),
        )
    elif mutation == "input":
        value = {"binding": case.bound.to_wire(), "input_sha256": "f" * 64}
        _replace_record(case.records, "consultation-inputs", case.bound.run_id, value)
    elif mutation == "binding":
        _replace_record(
            case.records,
            "bindings",
            case.bound.run_id,
            case.bound.model_copy(update={"source_revision": "f" * 40}).to_wire(),
        )
    elif mutation == "manifest":
        changed = observation.manifest.model_copy(update={"citations": ()})
        _replace_record(
            case.records, "manifests", observation.manifest.manifest_sha256, changed.to_wire()
        )
    elif mutation in {"claim", "reason"}:
        changed_value: dict[str, object] = (
            {"original_claim_sha256": "f" * 64}
            if mutation == "claim"
            else {"reason": "ASSESSMENT_REQUIRES_REDACTION"}
        )
        changed_observation = observation.model_copy(update=changed_value)
        changed_observation = changed_observation.model_copy(
            update={"observation_sha256": changed_observation.recompute_sha256()}
        )
        _replace_record(
            case.records,
            "assessment-rejections",
            observation.observation_sha256,
            changed_observation.to_wire(),
        )
    elif mutation == "additional-operation":
        previous = case.records.get(
            "operations", case.bound.run_id + ":read_000_000", KnowledgeEvidence
        )
        added = previous.model_copy(update={"operation_id": "read_late"})
        added = added.model_copy(
            update={"evidence_id": digest(added.model_dump(mode="json", exclude={"evidence_id"}))}
        )
        case.records.put("operations", case.bound.run_id + ":read_late", added)
        case.records.put("evidence", added.evidence_id, added)
    elif mutation == "extra-execution":
        identity = observation.assessment_execution_record_sha256s[0]
        record = case.lane.get("knowledge-execution-records", identity, KnowledgeExecutionRecord)
        _replace_record(
            case.lane, "knowledge-execution-records", "duplicate-record", record.to_wire()
        )
    else:

        def unknown(*args: object, **kwargs: object) -> None:
            raise ValueError("fixture owned-session state unknown")

        monkeypatch.setattr(
            "ai_software_engineer.knowledge.assessment_rejection.require_recorded_session_empty",
            unknown,
        )
    before = _bytes(case.root)
    with pytest.raises((KnowledgeError, ValueError)):
        read_rejected_assessment(case.records.root, observation.observation_sha256)
    assert _bytes(case.root) == before
    assert (case.root / "calls").read_text().splitlines() == [
        "KnowledgeIntent",
        "KnowledgeAssessment",
    ]


def test_raw_secret_never_becomes_returned_or_recovery_proof(tmp_path: Path) -> None:
    frozen = snapshot(document())
    bound = binding(frozen)
    claim = _actual_claim(bound)
    records = KnowledgeRecordStore(tmp_path / "knowledge")
    records.put("snapshots", frozen.snapshot_sha256, frozen)
    service = KnowledgeConsultationService(
        _client(tmp_path, _native_executable(tmp_path, unsafe=True), bound.role),
        records,
        invocation_journal=KnowledgeInvocationJournal(records, claimed=lambda: claim),
    )
    with pytest.raises(KnowledgeInvocationUncertain):
        service.consult(bound, frozen, {}, timeout_seconds=5)
    lane = KnowledgeRecordStore(records.root / "invocations" / invocation_lane_sha256(bound))
    assert (
        lane.find(
            "knowledge-invocation-outcomes",
            bound.run_id + ":assessment",
            KnowledgeInvocationOutcome,
        )
        is None
    )
    assert records.list("assessment-rejections", RejectedKnowledgeAssessment) == ()
    secret = ("sk-" + "A1b2C3d4" * 6).encode()
    assert all(secret not in payload for payload in _bytes(tmp_path).values())
    with pytest.raises(KnowledgeError):
        derive_rejected_assessment(records.root, bound)
