"""Read QA execution identity from accepted artifacts and immutable queue steps."""

from ai_software_engineer.domain.artifact import QaReportArtifact, ReviewReportArtifact
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.task import Task
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.ports import QueueCorruption


class QueuedVerificationReservation:
    def __init__(self, queue: MySqlRoleQueue) -> None:
        self.queue = queue

    def is_current(self, task: Task, report: QaReportArtifact | ReviewReportArtifact) -> bool:
        matches = tuple(
            record
            for record in self.queue.accepted(task.id)
            if record.receipt.artifact_id == report.artifact_id
        )
        if not matches:
            admission = self.queue.admission(task.id)
            if (
                admission is not None
                and task.engineering_policy is None
                and any(
                    legacy.artifact_id == report.artifact_id
                    and legacy.sha256 == report.integrity.sha256
                    for legacy in admission.legacy_artifacts
                )
            ):
                return True
            raise QueueCorruption("accepted QA result has no exact reservation receipt")
        if len(matches) != 1:
            raise QueueCorruption("accepted QA result has ambiguous reservations")
        record = matches[0]
        step = self.queue.original_step(record.work_item_id)
        if (
            record.receipt.sha256 != report.integrity.sha256
            or record.run_id != report.producer.run_id
            or record.context_manifest_id != report.context_manifest_id
            or record.source_revision != report.source_revision
            or step.boundary.role is not report.producer.role
            or step.boundary.role not in {AgentRole.QA, AgentRole.REVIEWER}
        ):
            raise QueueCorruption("accepted QA result changed its execution lineage")
        return step.boundary.attempt == max(task.attempts, 1)
