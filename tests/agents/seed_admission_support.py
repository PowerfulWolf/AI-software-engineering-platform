"""A trusted fixture admission delegates scope to real immutable main records."""

from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.agents.continuation import ContinuationExecutionUncertain
from ai_software_engineer.agents.workspace_admission import InitialWorkspaceAdmission
from ai_software_engineer.domain.artifact import CoderProgressArtifact, ImplementationReportArtifact
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)


class RecordedSeedAdmission:
    """Adapter fixture only; production additionally verifies queue and accepted publication."""

    def __init__(self, root: Path) -> None:
        self.records = KnowledgeRecordStore(root)
        self.attempts: list[int] = []

    @property
    def calls(self) -> int:
        return len(self.attempts)

    def for_request(self, request: AgentRequest) -> InitialWorkspaceAdmission | None:
        outcome = self.records.find("invocation-outcomes", "initial", DeliveryInvocationOutcome)
        if outcome is None:
            return self
        outcome.validate_integrity()
        artifact = outcome.result.artifact
        if request.task_id != outcome.start.request.task_id:
            raise ValueError("fixture admission is Task scoped")
        if isinstance(artifact, CoderProgressArtifact):
            if request.continuation_checkpoint_id != artifact.artifact_id:
                raise ContinuationExecutionUncertain("fixture has no matching accepted progress")
        elif not isinstance(artifact, ImplementationReportArtifact):
            raise ContinuationExecutionUncertain("fixture has no main output")
        if artifact.source_revision != request.source_revision:
            raise ValueError("fixture main input changed")
        return None

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None:
        assert workspace_root.is_dir()
        if self.records.find("invocation-starts", "initial", DeliveryInvocationStart) is not None:
            raise ContinuationExecutionUncertain("fixture seed is already admitted")
        start = DeliveryInvocationStart(
            work_item_id="work_fixture_initial",
            checkpoint_sequence=2,
            request=request,
            lease_id="lease_fixture_initial",
            started_at=datetime.now(UTC),
            start_sha256="0" * 64,
        )
        start = start.model_copy(
            update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
        )
        self.records.put("invocation-starts", "initial", start)
        self.attempts.append(request.attempt)

    def completed(self, result: AgentResult) -> None:
        start = self.records.get("invocation-starts", "initial", DeliveryInvocationStart)
        outcome = DeliveryInvocationOutcome(start=start, result=result, outcome_sha256="0" * 64)
        outcome = outcome.model_copy(
            update={
                "outcome_sha256": digest(
                    outcome.model_dump(mode="json", exclude={"outcome_sha256"})
                )
            }
        )
        self.records.put("invocation-outcomes", "initial", outcome)
