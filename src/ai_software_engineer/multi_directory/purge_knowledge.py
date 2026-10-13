"""Select sealed knowledge records by typed scope and declared reference chains."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.administration import KnowledgeHumanActionEvent
from ai_software_engineer.knowledge.agents import (
    KnowledgeConsultation,
    KnowledgeConsultationInput,
    KnowledgeIntent,
    KnowledgeModelCall,
    consultation_integrity_matches,
)
from ai_software_engineer.knowledge.delivery import DeliveryWorkflowAdmission, DeliveryWorkflowProof
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGap,
    KnowledgeGapRouting,
    KnowledgeResolution,
    KnowledgeResume,
)
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord,
    KnowledgeInvocationIntent,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeEvidence,
    KnowledgeRunBinding,
    KnowledgeRunManifest,
    KnowledgeSnapshot,
    digest,
)
from ai_software_engineer.knowledge.stages import StageWorkflowProof
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.knowledge.workflow import WorkflowSkillEvidence
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.safe_files import _read_regular, _reject_symlinks
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)

_MODELS: Mapping[str, type[DomainModel]] = {
    "bindings": KnowledgeRunBinding,
    "consultation-inputs": KnowledgeConsultationInput,
    "knowledge-intents": KnowledgeIntent,
    "consultations": KnowledgeConsultation,
    "model-calls": KnowledgeModelCall,
    "operations": KnowledgeEvidence,
    "evidence": KnowledgeEvidence,
    "manifests": KnowledgeRunManifest,
    "snapshots": KnowledgeSnapshot,
    "workflow-evidence": WorkflowSkillEvidence,
    "gaps": KnowledgeGap,
    "gap-routes": KnowledgeGapRouting,
    "resolutions": KnowledgeResolution,
    "gap-resolutions": KnowledgeResolution,
    "gap-resumes": KnowledgeResume,
    "human-actions": KnowledgeHumanActionEvent,
    "stage-contexts": JointCheckpoint,
    "stage-checkpoints": JointCheckpoint,
    "stage-proofs": StageWorkflowProof,
    "delivery-admissions": DeliveryWorkflowAdmission,
    "delivery-proofs": DeliveryWorkflowProof,
    "knowledge-local-limit-intents": KnowledgeInvocationIntent,
}


def _decode(path: Path, namespace: str, model: type[DomainModel]) -> DomainModel:
    _reject_symlinks(path)
    return KnowledgeRecordStore._decode_payload(_read_regular(path, 20_000_000), model)


def _integrity(record: DomainModel) -> None:
    validate = getattr(record, "validate_integrity", None)
    if callable(validate):
        validate()
    elif isinstance(record, KnowledgeConsultation):
        if not consultation_integrity_matches(record) or record.manifest.binding != record.binding:
            raise ValueError("knowledge consultation integrity differs")
        record.manifest.validate_integrity()
    else:
        field = {
            KnowledgeModelCall: "call_id",
            KnowledgeGapRouting: "routing_sha256",
            KnowledgeResume: "resume_sha256",
            KnowledgeHumanActionEvent: "event_sha256",
        }.get(type(record))
        if field is not None and getattr(record, field) != digest(
            record.model_dump(mode="json", exclude={field})
        ):
            raise ValueError("knowledge record integrity differs")


def select_knowledge(
    root: Path,
    checkpoint: JointCheckpoint,
    *,
    identities: set[str],
    task_repositories: Mapping[str, str],
    repository_id: str,
) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    selected: set[Path] = set()
    repositories = {preparation.result.repository_id for preparation in checkpoint.preparations}
    repositories.update(task_repositories.values())

    def binding_owned(binding: KnowledgeRunBinding) -> bool:
        matched = binding.requirement_id in identities or binding.task_id in identities
        if not matched:
            return False
        if (
            (binding.team_id, binding.project_id) != (checkpoint.team_id, checkpoint.project_id)
            or (
                not set(binding.repository_ids) <= repositories
                or repository_id not in binding.repository_ids
            )
            or (
                binding.task_id is not None
                and task_repositories.get(binding.task_id) != repository_id
            )
        ):
            raise ValueError("knowledge binding belongs to another owner")
        return True

    records: list[tuple[Path, str, DomainModel]] = []
    for path in sorted(root.glob("*.json")):
        namespace = path.name.rsplit("-", 1)[0]
        if namespace not in _MODELS:
            raise ValueError("unknown knowledge record namespace")
        record = _decode(path, namespace, _MODELS[namespace])
        _integrity(record)
        records.append((path, namespace, record))
    bindings = {
        record.run_id: record
        for _, namespace, record in records
        if namespace == "bindings"
        and isinstance(record, KnowledgeRunBinding)
        and binding_owned(record)
    }
    gaps = {
        record.gap_id: record
        for _, _, record in records
        if isinstance(record, KnowledgeGap) and binding_owned(record.binding)
    }
    resolutions = {
        record.resolution_id: record
        for _, _, record in records
        if isinstance(record, KnowledgeResolution) and record.gap_id in gaps
    }
    for resolution in resolutions.values():
        if resolution.previous_run_id != gaps[resolution.gap_id].binding.run_id:
            raise ValueError("knowledge gap resolution owner differs")

    def select(path: Path, namespace: str, key: str) -> None:
        if path.name != KnowledgeRecordStore._name(namespace, key):
            raise ValueError("knowledge record indexed identity differs")
        selected.add(path)

    for path, namespace, record in records:
        key: str | None = None
        binding = getattr(record, "binding", None)
        if isinstance(record, WorkflowSkillEvidence):
            binding = record.facts.binding
        if isinstance(record, KnowledgeResume):
            owned = binding_owned(record.previous_binding) or binding_owned(record.new_binding)
            if owned:
                if (
                    not binding_owned(record.previous_binding)
                    or not binding_owned(record.new_binding)
                    or (
                        record.gap_id not in gaps
                        or record.resolution_id not in resolutions
                        or resolutions[record.resolution_id].gap_id != record.gap_id
                    )
                ):
                    raise ValueError("knowledge resume chain owner differs")
                key = record.new_binding.run_id + ":" + record.gap_id
        elif isinstance(record, KnowledgeRunBinding):
            if binding_owned(record):
                key = record.run_id
        elif isinstance(record, KnowledgeSnapshot):
            if record.requirement_id in identities:
                if (record.team_id, record.project_id) != (
                    checkpoint.team_id,
                    checkpoint.project_id,
                ) or (
                    not set(record.repository_ids) <= repositories
                    or repository_id not in record.repository_ids
                ):
                    raise ValueError("knowledge snapshot owner differs")
                key = record.snapshot_sha256
        elif isinstance(record, KnowledgeIntent):
            for run_id in bindings:
                if path.name == KnowledgeRecordStore._name(namespace, run_id):
                    key = run_id
        elif isinstance(record, KnowledgeGapRouting):
            if record.gap_id in gaps:
                key = record.gap_id
        elif isinstance(record, KnowledgeResolution):
            if record.resolution_id in resolutions:
                key = record.gap_id if namespace == "gap-resolutions" else record.resolution_id
        elif isinstance(record, KnowledgeHumanActionEvent):
            if record.requirement_id in identities:
                if (
                    record.project_id != checkpoint.project_id
                    or record.gap_id not in gaps
                    or (record.resolution.resolution_id not in resolutions)
                ):
                    raise ValueError("knowledge human action owner differs")
                key = record.event_sha256
        elif isinstance(record, JointCheckpoint):
            if record.delivery_id in identities:
                if (record.team_id, record.project_id) != (
                    checkpoint.team_id,
                    checkpoint.project_id,
                ):
                    raise ValueError("knowledge stage checkpoint owner differs")
                if namespace == "stage-checkpoints":
                    key = record.checkpoint_sha256
                else:
                    for item in bindings.values():
                        if path.name == KnowledgeRecordStore._name(
                            namespace, item.context_manifest_id
                        ):
                            key = item.context_manifest_id
        elif isinstance(record, (DeliveryWorkflowAdmission, DeliveryWorkflowProof)):
            if record.task_id in task_repositories:
                if task_repositories[record.task_id] != repository_id:
                    raise ValueError("knowledge delivery proof repository differs")
                key = (
                    record.task_id
                    if isinstance(record, DeliveryWorkflowAdmission)
                    else record.proof_sha256
                )
        elif isinstance(binding, KnowledgeRunBinding) and binding_owned(binding):
            if isinstance(record, (KnowledgeConsultation, KnowledgeConsultationInput)):
                key = binding.run_id
            elif isinstance(record, KnowledgeModelCall):
                key = record.call_id
            elif isinstance(record, KnowledgeEvidence):
                key = (
                    binding.run_id + ":" + record.operation_id
                    if namespace == "operations"
                    else record.evidence_id
                )
            elif isinstance(record, KnowledgeRunManifest):
                key = record.manifest_sha256
            elif isinstance(record, WorkflowSkillEvidence):
                key = record.evidence_sha256
            elif isinstance(record, KnowledgeGap):
                key = record.gap_id
            elif isinstance(record, StageWorkflowProof):
                key = record.proof_sha256
            elif not isinstance(record, KnowledgeInvocationIntent):
                raise ValueError("knowledge owned record has no identity contract")
        if key is not None:
            select(path, namespace, key)

    lanes = root / "invocations"
    _reject_symlinks(lanes)
    outcomes: dict[str, KnowledgeInvocationOutcome] = {}
    if lanes.exists():
        for lane in sorted(lanes.iterdir()):
            _reject_symlinks(lane)
            intents: dict[str, KnowledgeInvocationIntent] = {}
            lane_records: list[tuple[Path, str, DomainModel]] = []
            for path in sorted(lane.iterdir()):
                namespace = path.name.rsplit("-", 1)[0]
                models: Mapping[str, type[DomainModel]] = {
                    "knowledge-invocation-intents": KnowledgeInvocationIntent,
                    "knowledge-invocation-outcomes": KnowledgeInvocationOutcome,
                    "knowledge-execution-records": KnowledgeExecutionRecord,
                }
                model = models.get(namespace)
                if model is None:
                    raise ValueError("unknown knowledge invocation record")
                record = _decode(path, namespace, model)
                _integrity(record)
                lane_records.append((path, namespace, record))
                if isinstance(record, KnowledgeInvocationIntent):
                    if invocation_lane_sha256(record.binding) != lane.name:
                        raise ValueError("knowledge invocation lane differs")
                    intents[record.intent_sha256] = record
            lane_owned = [binding_owned(intent.binding) for intent in intents.values()]
            if not any(lane_owned):
                continue
            if not all(lane_owned):
                raise ValueError("knowledge invocation lane has foreign owner")
            for path, namespace, record in lane_records:
                if isinstance(record, KnowledgeInvocationIntent):
                    key = record.binding.run_id + ":" + record.phase
                elif isinstance(record, KnowledgeInvocationOutcome):
                    if intents.get(record.intent.intent_sha256) != record.intent:
                        raise ValueError("knowledge outcome input differs")
                    key = record.intent.binding.run_id + ":" + record.intent.phase
                    outcomes[record.outcome_sha256] = record
                elif isinstance(record, KnowledgeExecutionRecord):
                    if record.intent_sha256 not in intents:
                        raise ValueError("knowledge execution has another intent")
                    key = record.record_sha256
                else:
                    raise ValueError("unknown invocation contract")
                select(path, namespace, key)
            selected.add(lane)
    for path, namespace, record in records:
        if namespace == "knowledge-local-limit-intents" and isinstance(
            record, KnowledgeInvocationIntent
        ):
            for outcome_id, outcome in outcomes.items():
                if outcome.intent == record and path.name == KnowledgeRecordStore._name(
                    namespace, outcome_id
                ):
                    select(path, namespace, outcome_id)
    return tuple(sorted(selected))


def select_delivery_invocations(root: Path, task_ids: set[str]) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    selected: list[Path] = []
    starts: dict[str, DeliveryInvocationStart] = {}
    records: list[tuple[Path, str, DomainModel]] = []
    for path in sorted(root.glob("*.json")):
        namespace = path.name.rsplit("-", 1)[0]
        models: Mapping[str, type[DomainModel]] = {
            "invocation-starts": DeliveryInvocationStart,
            "invocation-outcomes": DeliveryInvocationOutcome,
        }
        model = models.get(namespace)
        if model is None:
            raise ValueError("unknown delivery invocation contract")
        record = _decode(path, namespace, model)
        _integrity(record)
        records.append((path, namespace, record))
        if isinstance(record, DeliveryInvocationStart):
            starts[record.work_item_id] = record
    for path, namespace, record in records:
        start = (
            record
            if isinstance(record, DeliveryInvocationStart)
            else record.start
            if isinstance(record, DeliveryInvocationOutcome)
            else None
        )
        if start is not None and start.request.task_id in task_ids:
            if (
                isinstance(record, DeliveryInvocationOutcome)
                and starts.get(start.work_item_id) != start
            ):
                raise ValueError("delivery invocation outcome has another start")
            if path.name != KnowledgeRecordStore._name(namespace, start.work_item_id):
                raise ValueError("delivery invocation record index differs")
            selected.append(path)
    return tuple(selected)
