"""Owner-fenced delivery waiting, separate from role output and Task termination."""

from typing import Protocol

from ai_software_engineer.domain.task import Task


class DeliveryFailureControl(Protocol):
    def wait(
        self,
        task: Task,
        *,
        classification: str,
        reason: str,
        source_revision: str,
        artifact_ids: tuple[str, ...],
    ) -> None:
        """Persist recoverable waiting and stop the pass with a typed pending result."""
        ...
