"""Bridge exact approved knowledge resolutions into ordinary ADR evaluation facts."""

from datetime import UTC, datetime

from ai_software_engineer.domain import Task
from ai_software_engineer.evaluation import (
    EvaluationCaseId,
    EvaluationEventStore,
    HumanAction,
    HumanActionEvent,
)
from ai_software_engineer.knowledge.gaps import KnowledgeGap, KnowledgeResolution
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore


class KnowledgeHumanActionRecorder:
    def __init__(
        self, stores: tuple[KnowledgeRecordStore, ...], *, requirement_id: str | None = None
    ) -> None:
        self.stores, self.requirement_id = stores, requirement_id

    def record(self, task: Task, case_id: EvaluationCaseId, events: EvaluationEventStore) -> None:
        for records in self.stores:
            for resolution in records.list("gap-resolutions", KnowledgeResolution):
                resolution.validate_integrity()
                gap = records.get("gaps", resolution.gap_id, KnowledgeGap)
                gap.validate_integrity()
                if gap.binding.task_id != task.id and not (
                    gap.binding.task_id is None
                    and self.requirement_id is not None
                    and gap.binding.requirement_id == self.requirement_id
                ):
                    continue
                if resolution.previous_run_id != gap.binding.run_id:
                    raise KnowledgeError("RESOLUTION_LINEAGE")
                identity = digest((case_id, task.id, resolution.resolution_id))
                event_id = "evalevt_knowledge_" + identity[:32]
                evidence_uri = "knowledge-resolution://" + resolution.resolution_id
                prior = events.find(event_id)
                if prior is not None:
                    if (
                        not isinstance(prior, HumanActionEvent)
                        or prior.case_id != case_id
                        or prior.task_id != task.id
                        or prior.action is not HumanAction.CLARIFY_REQUIREMENTS
                        or prior.evidence_uri != evidence_uri
                    ):
                        raise KnowledgeError("RESOLUTION_EVALUATION_CONFLICT")
                    continue
                events.append(
                    HumanActionEvent(
                        event_id=event_id,
                        case_id=case_id,
                        task_id=task.id,
                        occurred_at=datetime.now(UTC),
                        action=HumanAction.CLARIFY_REQUIREMENTS,
                        evidence_uri=evidence_uri,
                        note="Exact knowledge resolution approved through the human boundary.",
                    )
                )
