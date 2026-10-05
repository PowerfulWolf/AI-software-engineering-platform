"""Trusted reservation of an accepted QA result, separate from its verdict."""

from typing import Protocol

from ai_software_engineer.domain.artifact import QaReportArtifact, ReviewReportArtifact
from ai_software_engineer.domain.task import Task


class VerificationReservation(Protocol):
    def is_current(self, task: Task, report: QaReportArtifact | ReviewReportArtifact) -> bool: ...
