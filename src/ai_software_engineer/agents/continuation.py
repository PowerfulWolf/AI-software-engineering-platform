"""Trusted Coder continuation ports; unavailable as model tools."""

from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ai_software_engineer.agents.execution import ExecutionStop
from ai_software_engineer.agents.models import AgentErrorCode, AgentRequest, AgentResult
from ai_software_engineer.domain.continuation import ContinuationCause
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.mutation import WorkspaceMutationInventory
from ai_software_engineer.store import TaskRepository


class InterruptionObservation(StrEnum):
    UNCHANGED = "unchanged"
    CAPTURED = "captured"
    PRESERVED = "preserved"


class InterruptionAdmissionRejected(RuntimeError):
    """A typed continuation admission was refused before a provider call."""


class ContinuationExecutionUncertain(InterruptionAdmissionRejected):
    """Invocation or stop cannot be proven; preserve checkpoint and wait for engineering."""


class InterruptionBudgetExhausted(InterruptionAdmissionRejected):
    """The recorded interruption cannot reserve another authorized invocation."""


class CoderInterruptionControl(Protocol):
    def prepare(self, request: AgentRequest, root: Path) -> str | None: ...

    def started(self, request: AgentRequest, root: Path) -> WorkspaceMutationInventory | None: ...

    def finished(
        self, request: AgentRequest, root: Path, *, before: WorkspaceMutationInventory
    ) -> None: ...

    def interrupted(
        self,
        request: AgentRequest,
        root: Path,
        *,
        before: WorkspaceMutationInventory,
        cause: ContinuationCause,
        original_error_code: AgentErrorCode,
        process_stop: ExecutionStop | None,
        output_present: bool,
    ) -> InterruptionObservation: ...


class InterruptionRetryControl(Protocol):
    def resume(self, task: Task, repository: TaskRepository) -> int | None: ...

    def next_attempt(
        self, task: Task, result: AgentResult, repository: TaskRepository
    ) -> int | None: ...


def same_continuation_inputs(
    new: AgentRequest, old: AgentRequest, *, cause: ContinuationCause
) -> bool:
    """Compare frozen inputs and the exact deterministic successor work slice.

    Never discard the slice: its plan, source, window, completed steps, full
    pending sequence and remaining allowance are authority-bearing facts.
    Only new Run identity/context and the monotonically advanced attempt vary.
    """
    if new.attempt != old.attempt + 1:
        return False
    expected = old
    if old.work_slice is not None:
        from ai_software_engineer.domain.coder_work import (
            CoderSliceRejected,
            successor_coder_work_slice,
        )

        try:
            work = successor_coder_work_slice(
                old.work_slice, consume_work=cause == "local_execution_limit"
            )
        except CoderSliceRejected:
            return False
        expected = old.model_copy(update={"work_slice": work})
    return new.model_dump(
        mode="json", exclude_none=True, exclude={"run_id", "attempt", "context_manifest_id"}
    ) == expected.model_dump(
        mode="json", exclude_none=True, exclude={"run_id", "attempt", "context_manifest_id"}
    )
