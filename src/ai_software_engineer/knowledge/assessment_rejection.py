"""Exact rejected RETURNED facts, without granting replacement execution authority."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator

from ai_software_engineer.agents.execution import current_execution_guard, execution_scope
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured import StructuredModelError
from ai_software_engineer.agents.structured_observation import (
    StructuredNativeStopReceipt,
    structured_request_digest,
)
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.assessment_validation import (
    KNOWLEDGE_ASSESSMENT_INSTRUCTIONS,
    KNOWLEDGE_INTENT_INSTRUCTIONS,
    AssessmentRejectionReason,
    KnowledgeAssessment,
    KnowledgeConsultationInput,
    KnowledgeIntent,
    assessment_rejection_reason,
)
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.knowledge.gaps import KnowledgeGap, KnowledgeResolution
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord,
    KnowledgeInvocationIntent,
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import (
    Digest,
    KnowledgeError,
    KnowledgeEvidence,
    KnowledgeReadRequest,
    KnowledgeRunBinding,
    KnowledgeRunManifest,
    KnowledgeSearchRequest,
    KnowledgeSnapshot,
    digest,
)
from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.owned_sessions import (
    OwnedSessionUnknown,
    require_recorded_session_empty,
)
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.work_queue.models import QueueClaim

_REJECTIONS = "assessment-rejections"
_MESSAGES: dict[AssessmentRejectionReason, str] = {
    "CLAIM_WITHOUT_READ": "知识评估引用了本次未精确读取的来源, 结果未接受。",
    "ASSESSMENT_REQUIRES_REDACTION": "知识评估未通过敏感信息检查, 结果未接受。",
}


class RejectedAssessmentUnavailable(KnowledgeError):
    """A typed refusal remains valid, but these facts grant no recovery proof."""


class RejectedKnowledgeAssessment(DomainModel):
    kind: Literal["rejected_knowledge_assessment"] = "rejected_knowledge_assessment"
    schema_version: Literal["v0.1"] = "v0.1"
    binding: KnowledgeRunBinding
    input_sha256: Digest
    original_claim: QueueClaim
    original_claim_sha256: Digest
    intent_outcome_sha256: Digest
    assessment_outcome_sha256: Digest
    intent_execution_record_sha256s: tuple[Digest, ...]
    assessment_execution_record_sha256s: tuple[Digest, ...]
    manifest: KnowledgeRunManifest
    reason: AssessmentRejectionReason
    observation_sha256: Digest

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        self.manifest.validate_integrity()
        claim = self.original_claim
        if (
            self.manifest.binding != self.binding
            or self.manifest.snapshot_sha256 != self.binding.snapshot_sha256
            or self.original_claim_sha256 != claim_identity_sha256(claim)
            or self.binding.task_id != claim.work_item.task_id
            or self.binding.repository_ids != (claim.work_item.repository_id,)
            or self.binding.role.value != claim.work_item.role.value
            or not self.intent_execution_record_sha256s
            or not self.assessment_execution_record_sha256s
        ):
            raise ValueError("rejected assessment must retain exact claimed preparation facts")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "observation_sha256": "0" * 64})
        return value.model_copy(update={"observation_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"observation_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.observation_sha256 != self.recompute_sha256():
            raise KnowledgeError("ASSESSMENT_REJECTION_INTEGRITY")


class KnowledgeAssessmentRejected(StructuredModelError):
    """Nontransient semantic failure; an optional proof is data, never retry authority."""

    def __init__(
        self,
        reason: AssessmentRejectionReason,
        observation: RejectedKnowledgeAssessment | None = None,
        *,
        safe_message: str | None = None,
    ) -> None:
        if observation is not None:
            observation.validate_integrity()
            if observation.reason != reason:
                raise KnowledgeError("ASSESSMENT_REJECTION_REASON_CHANGED")
        self.reason, self.observation = reason, observation
        super().__init__(
            AgentErrorCode.INVALID_OUTPUT,
            safe_message or f"{reason}: {_MESSAGES[reason]}",
            transient=False,
        )

    def with_context(self, context: str) -> KnowledgeAssessmentRejected:
        return KnowledgeAssessmentRejected(
            self.reason, self.observation, safe_message=f"{context}: {self.safe_message}"
        )


def _returned(
    lane: KnowledgeRecordStore, binding: KnowledgeRunBinding, phase: Literal["intent", "assessment"]
) -> KnowledgeInvocationOutcome:
    key = binding.run_id + ":" + phase
    intent = lane.get("knowledge-invocation-intents", key, KnowledgeInvocationIntent)
    intent.validate_integrity()
    outcome = lane.get("knowledge-invocation-outcomes", key, KnowledgeInvocationOutcome)
    KnowledgeInvocationJournal._require_outcome(lane, intent, outcome)
    if intent.binding != binding or intent.phase != phase or outcome.state != "RETURNED":
        raise KnowledgeError("ASSESSMENT_REJECTION_OUTCOME_CHANGED")
    if outcome.result is None:
        raise KnowledgeError("ASSESSMENT_REJECTION_OUTCOME_CHANGED")
    rendered = outcome.result.model_dump_json()
    if redact_text(rendered).text != rendered:
        raise KnowledgeError("ASSESSMENT_REJECTION_UNSAFE_RETURNED")
    if intent.claim is None or not outcome.executions:
        raise RejectedAssessmentUnavailable("ASSESSMENT_REJECTION_CLAIM_OR_EXECUTION_REQUIRED")
    actual = tuple(
        record
        for record in lane.list(
            "knowledge-execution-records", KnowledgeExecutionRecord, limit=16_384
        )
        if record.intent_sha256 == intent.intent_sha256
    )
    for record in actual:
        record.validate_integrity()
    if len(actual) != len(outcome.executions) or set(record.record_sha256 for record in actual) != {
        record.record_sha256 for record in outcome.executions
    }:
        raise KnowledgeError("ASSESSMENT_REJECTION_EXECUTIONS_CHANGED")
    stops = tuple(
        record.observation
        for record in outcome.executions
        if isinstance(record.observation, StructuredNativeStopReceipt)
    )
    if not stops:
        raise RejectedAssessmentUnavailable("ASSESSMENT_REJECTION_NATIVE_STOP_REQUIRED")
    for stopped in stops:
        stop = stopped.process_stop
        if stop.session_proof is None:
            raise RejectedAssessmentUnavailable("ASSESSMENT_REJECTION_OWNED_STOP_REQUIRED")
        if stop.stopped_at > outcome.completed_at:
            raise KnowledgeError("ASSESSMENT_REJECTION_STOP_TIME_CHANGED")
        try:
            require_recorded_session_empty(stop.session_proof)
        except (OSError, ValueError, OwnedSessionUnknown) as error:
            raise KnowledgeError("ASSESSMENT_REJECTION_EXECUTION_UNKNOWN") from error
    return outcome


def _manifest(
    records: KnowledgeRecordStore, binding: KnowledgeRunBinding, intent: KnowledgeIntent
) -> tuple[KnowledgeRunManifest, tuple[KnowledgeEvidence, ...]]:
    if records.get("bindings", binding.run_id, KnowledgeRunBinding) != binding:
        raise KnowledgeError("ASSESSMENT_REJECTION_BINDING_CHANGED")
    snapshot = records.get("snapshots", binding.snapshot_sha256, KnowledgeSnapshot)
    snapshot.validate_integrity()
    if (
        snapshot.team_id,
        snapshot.project_id,
        snapshot.requirement_id,
        snapshot.repository_ids,
        snapshot.snapshot_sha256,
    ) != (
        binding.team_id,
        binding.project_id,
        binding.requirement_id,
        binding.repository_ids,
        binding.snapshot_sha256,
    ):
        raise KnowledgeError("ASSESSMENT_REJECTION_SNAPSHOT_CHANGED")
    allowed = KnowledgeSnapshot.create(
        team_id=snapshot.team_id,
        project_id=snapshot.project_id,
        requirement_id=snapshot.requirement_id,
        repository_ids=snapshot.repository_ids,
        documents=tuple(
            doc for doc in snapshot.documents if not doc.roles or binding.role in doc.roles
        ),
    )
    operations = tuple(
        item for item in records.list("operations", KnowledgeEvidence) if item.binding == binding
    )
    selected = {item.operation_id: item for item in operations}
    if len(selected) != len(operations) or len(operations) > 20:
        raise KnowledgeError("ASSESSMENT_REJECTION_OPERATIONS_CHANGED")
    expected: set[str] = set()
    ordered: list[KnowledgeEvidence] = []
    for index, query in enumerate(intent.queries):
        search_id = f"search_{index:03d}"
        expected.add(search_id)
        search = selected.get(search_id)
        request = KnowledgeSearchRequest(
            binding=binding, operation_id=search_id, query=query, limit=4
        )
        if (
            search is None
            or search.operation != "search_knowledge"
            or search.request_sha256 != digest(request.to_wire())
            or search.query != query
            or search.scopes
            or search.chunk is not None
            or search.status not in {"HIT", "MISS", "REJECTED"}
            or (search.status == "HIT") != bool(search.hits)
            or len(search.hits) > 4
        ):
            raise KnowledgeError("ASSESSMENT_REJECTION_SEARCH_CHANGED")
        ordered.append(search)
        for hit_index, hit in enumerate(search.hits):
            exact = MarkdownKnowledgeRetrieval().read(allowed, hit.citation)
            if hit.snippet != exact.content[:800]:
                raise KnowledgeError("ASSESSMENT_REJECTION_SEARCH_CHANGED")
            read_id = f"read_{index:03d}_{hit_index:03d}"
            expected.add(read_id)
            read = selected.get(read_id)
            read_request = KnowledgeReadRequest(
                binding=binding,
                operation_id=read_id,
                search_evidence_id=search.evidence_id,
                citation=hit.citation,
            )
            if (
                read is None
                or read.operation != "read_knowledge"
                or read.request_sha256 != digest(read_request.to_wire())
                or read.query
                or read.scopes
                or read.hits
                or read.status not in {"READ", "REJECTED"}
                or (read.status == "READ") != (read.chunk is not None)
                or (read.chunk is not None and read.chunk != exact)
            ):
                raise KnowledgeError("ASSESSMENT_REJECTION_READ_CHANGED")
            ordered.append(read)
    if set(selected) != expected:
        raise KnowledgeError("ASSESSMENT_REJECTION_OPERATIONS_CHANGED")
    for item in operations:
        item.validate_integrity()
        if (
            records.get("operations", binding.run_id + ":" + item.operation_id, KnowledgeEvidence)
            != item
            or records.get("evidence", item.evidence_id, KnowledgeEvidence) != item
        ):
            raise KnowledgeError("ASSESSMENT_REJECTION_EVIDENCE_CHANGED")
    provisional = KnowledgeRunManifest(
        binding=binding,
        snapshot_sha256=binding.snapshot_sha256,
        evidence_ids=tuple(sorted(item.evidence_id for item in operations)),
        citations=tuple(
            item.chunk.citation
            for item in sorted(operations, key=lambda value: value.operation_id)
            if item.status == "READ" and item.chunk is not None
        ),
        manifest_sha256="0" * 64,
    )
    manifest = provisional.model_copy(
        update={
            "manifest_sha256": digest(
                provisional.model_dump(mode="json", exclude={"manifest_sha256"})
            )
        }
    )
    if records.get("manifests", manifest.manifest_sha256, KnowledgeRunManifest) != manifest:
        raise KnowledgeError("ASSESSMENT_REJECTION_MANIFEST_CHANGED")
    return manifest, tuple(ordered)


def _request_payload(
    records: KnowledgeRecordStore, binding: KnowledgeRunBinding, input_sha256: str
) -> dict[str, object]:
    context = FileContextStore(records.root.parent.parent / "contexts", read_only=True).get(
        binding.context_manifest_id
    )
    tasks = tuple(section for section in context.sections if section.name == "task")
    if (
        len(tasks) != 1
        or tasks[0].truncated
        or (
            context.task_id != binding.task_id
            or context.role.value != binding.role.value
            or context.source_revision != binding.source_revision
        )
    ):
        raise KnowledgeError("ASSESSMENT_REJECTION_CONTEXT_CHANGED")
    task = Task.model_validate_json(tasks[0].content)
    payload: dict[str, object] = {"task": task.to_wire(), "context": context.to_wire()}
    if digest(payload) != input_sha256:
        raise KnowledgeError("ASSESSMENT_REJECTION_INPUT_CHANGED")
    resolved = []
    for gap in records.list("gaps", KnowledgeGap):
        if (
            gap.binding.team_id,
            gap.binding.project_id,
            gap.binding.requirement_id,
            gap.binding.task_id,
            gap.binding.snapshot_sha256,
        ) != (
            binding.team_id,
            binding.project_id,
            binding.requirement_id,
            binding.task_id,
            binding.snapshot_sha256,
        ) or (gap.binding.role != binding.role and binding.task_id is not None):
            continue
        resolution = records.find("gap-resolutions", gap.gap_id, KnowledgeResolution)
        if resolution is None or gap.binding.run_id == binding.run_id:
            continue
        gap.validate_integrity()
        resolution.validate_integrity()
        if resolution.previous_run_id != gap.binding.run_id or resolution.gap_id != gap.gap_id:
            raise KnowledgeError("ASSESSMENT_REJECTION_RESOLUTION_CHANGED")
        if (
            gap.binding.role != binding.role
            and gap.binding.source_revision != binding.source_revision
        ):
            continue
        resolved.append(resolution.to_wire())
    payload["design_rechecks"] = []
    payload["approved_knowledge_resolutions"] = resolved
    return payload


def _require_requests(
    records: KnowledgeRecordStore,
    binding: KnowledgeRunBinding,
    input_sha256: str,
    intent_outcome: KnowledgeInvocationOutcome,
    assessment_outcome: KnowledgeInvocationOutcome,
    evidence: tuple[KnowledgeEvidence, ...],
) -> None:
    payload = _request_payload(records, binding, input_sha256)
    snapshot = records.get("snapshots", binding.snapshot_sha256, KnowledgeSnapshot)
    intent_request_sha = structured_request_digest(
        instructions=KNOWLEDGE_INTENT_INSTRUCTIONS,
        input_payload={
            "binding": binding.to_wire(),
            "task": payload,
            "available_documents": [
                {"id": doc.document_id, "scope": doc.scope, "title": doc.title}
                for doc in snapshot.documents
                if not doc.roles or binding.role in doc.roles
            ],
        },
        output_schema=KnowledgeIntent.model_json_schema(),
        timeout_seconds=intent_outcome.intent.timeout_seconds,
    )
    assessment_request_sha = structured_request_digest(
        instructions=KNOWLEDGE_ASSESSMENT_INSTRUCTIONS,
        input_payload={
            "binding": binding.to_wire(),
            "task": payload,
            "knowledge_evidence": [item.to_wire() for item in evidence],
        },
        output_schema=KnowledgeAssessment.model_json_schema(),
        timeout_seconds=assessment_outcome.intent.timeout_seconds,
    )
    if (
        intent_request_sha != intent_outcome.intent.request_sha256
        or assessment_request_sha != assessment_outcome.intent.request_sha256
    ):
        raise KnowledgeError("ASSESSMENT_REJECTION_REQUEST_CHANGED")


def derive_rejected_assessment(
    records_root: Path, binding: KnowledgeRunBinding
) -> RejectedKnowledgeAssessment:
    """Read-only current recomputation; no queue, result or historical facts are written."""
    records = KnowledgeRecordStore(records_root, read_only=True)
    lane = KnowledgeRecordStore(
        records_root / "invocations" / invocation_lane_sha256(binding), read_only=True
    )
    intent_outcome = _returned(lane, binding, "intent")
    assessment_outcome = _returned(lane, binding, "assessment")
    claim = assessment_outcome.intent.claim
    previous_claim = intent_outcome.intent.claim
    assert claim is not None and previous_claim is not None
    if (
        claim_identity_sha256(claim) != claim_identity_sha256(previous_claim)
        or assessment_outcome.intent.created_at < intent_outcome.completed_at
    ):
        raise KnowledgeError("ASSESSMENT_REJECTION_CLAIM_CHANGED")
    assert intent_outcome.result is not None and assessment_outcome.result is not None
    intent = KnowledgeIntent.model_validate(intent_outcome.result.payload)
    intent = KnowledgeIntent(queries=tuple(redact_text(query).text for query in intent.queries))
    if (
        not intent.queries
        or records.get("knowledge-intents", binding.run_id, KnowledgeIntent) != intent
    ):
        raise KnowledgeError("ASSESSMENT_REJECTION_INTENT_CHANGED")
    original_input = records.get("consultation-inputs", binding.run_id, KnowledgeConsultationInput)
    if original_input.binding != binding:
        raise KnowledgeError("ASSESSMENT_REJECTION_INPUT_CHANGED")
    manifest, evidence = _manifest(records, binding, intent)
    _require_requests(
        records, binding, original_input.input_sha256, intent_outcome, assessment_outcome, evidence
    )
    assessment = KnowledgeAssessment.model_validate(assessment_outcome.result.payload)
    reason = assessment_rejection_reason(assessment, manifest)
    if reason is None:
        raise KnowledgeError("ASSESSMENT_REJECTION_NOT_REJECTED")
    return RejectedKnowledgeAssessment.create(
        binding=binding,
        input_sha256=original_input.input_sha256,
        original_claim=claim,
        original_claim_sha256=claim_identity_sha256(claim),
        intent_outcome_sha256=intent_outcome.outcome_sha256,
        assessment_outcome_sha256=assessment_outcome.outcome_sha256,
        intent_execution_record_sha256s=tuple(r.record_sha256 for r in intent_outcome.executions),
        assessment_execution_record_sha256s=tuple(
            r.record_sha256 for r in assessment_outcome.executions
        ),
        manifest=manifest,
        reason=reason,
    )


def record_rejected_assessment(
    records: KnowledgeRecordStore, binding: KnowledgeRunBinding
) -> RejectedKnowledgeAssessment:
    observation = derive_rejected_assessment(records.root, binding)
    with execution_scope(current_execution_guard()):
        return records.put(_REJECTIONS, observation.observation_sha256, observation)


def read_rejected_assessment(
    records_root: Path, observation_sha256: str
) -> RejectedKnowledgeAssessment:
    records = KnowledgeRecordStore(records_root, read_only=True)
    observation = records.get(_REJECTIONS, observation_sha256, RejectedKnowledgeAssessment)
    observation.validate_integrity()
    if observation.observation_sha256 != observation_sha256 or (
        derive_rejected_assessment(records_root, observation.binding) != observation
    ):
        raise KnowledgeError("ASSESSMENT_REJECTION_FACTS_CHANGED")
    return observation
