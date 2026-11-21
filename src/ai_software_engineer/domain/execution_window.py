"""Frozen execution windows and an exact, single-invocation work slice.

These values are work instructions, not grants or role verdicts. Window values
come from trusted composition; a model cannot enlarge them.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique


class PlanExecutionWindow(DomainModel):
    kind: Literal["serial_coder_window_v1"] = "serial_coder_window_v1"
    hard_seconds: Annotated[StrictInt, Field(ge=2, le=3600)]
    finalization_reserve_seconds: Annotated[StrictInt, Field(ge=1, le=300)]
    reserve_rework_attempts: Annotated[StrictInt, Field(ge=0, le=1)] = 1
    # Optional work capacity. Both are absent in legacy windows, so their frozen
    # bytes and digests are unchanged. When present, one Coder invocation never
    # receives more than ``max_steps_per_run`` approved steps, and a plan whose
    # steps cannot fit the frozen work budget is rejected before any Coder runs.
    max_steps_per_run: Annotated[StrictInt, Field(ge=1, le=16)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    max_coder_runs: Annotated[StrictInt, Field(ge=1, le=20)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_reserve(self) -> Self:
        if self.finalization_reserve_seconds >= self.hard_seconds:
            raise ValueError("finalization reserve must be below the hard execution window")
        if (self.max_steps_per_run is None) != (self.max_coder_runs is None):
            raise ValueError("work capacity requires both max_steps_per_run and max_coder_runs")
        if self.max_coder_runs is not None and self.max_coder_runs <= self.reserve_rework_attempts:
            raise ValueError("work capacity must leave at least one Coder run after rework")
        return self

    @property
    def step_capacity(self) -> int | None:
        """Approved steps that fit the window, or ``None`` for legacy unbounded windows."""
        if self.max_steps_per_run is None or self.max_coder_runs is None:
            return None
        return self.max_steps_per_run * (self.max_coder_runs - self.reserve_rework_attempts)

    def validate_step_count(self, step_count: int) -> None:
        """Reject an oversized plan before work starts instead of timing out mid-run."""
        capacity = self.step_capacity
        if capacity is not None and step_count > capacity:
            raise PlanExceedsWorkCapacity(
                step_count=step_count,
                capacity=capacity,
                max_steps_per_run=self.max_steps_per_run or 0,
                coder_runs=(self.max_coder_runs or 0) - self.reserve_rework_attempts,
            )

    @classmethod
    def for_seconds(
        cls,
        seconds: int,
        *,
        max_steps_per_run: int | None = None,
        max_coder_runs: int | None = None,
    ) -> PlanExecutionWindow:
        return cls(
            hard_seconds=seconds,
            finalization_reserve_seconds=min(300, max(1, seconds // 5), seconds - 1),
            max_steps_per_run=max_steps_per_run,
            max_coder_runs=max_coder_runs,
        )


DEFAULT_CODER_STEPS_PER_RUN = 3
"""Approved design steps one Coder invocation may take on in a new production plan.

Calibrated against the serial Coder window: a run handed eight steps of a
53-path plan could not finish inside 1800 seconds and left an unreportable
draft. Smaller slices keep interruptions cheap and plans honest about size.
"""


def bounded_coder_window(seconds: int, *, max_work_attempts: int) -> PlanExecutionWindow:
    """Trusted composition of a capacity-bounded window for new production plans."""
    return PlanExecutionWindow.for_seconds(
        seconds,
        max_steps_per_run=DEFAULT_CODER_STEPS_PER_RUN,
        max_coder_runs=max(2, max_work_attempts),
    )


class PlanExceedsWorkCapacity(ValueError):
    """The approved design has more steps than its frozen Coder budget can complete."""

    def __init__(
        self, *, step_count: int, capacity: int, max_steps_per_run: int, coder_runs: int
    ) -> None:
        super().__init__(
            f"需求过大：技术方案有 {step_count} 个实现步骤，"  # noqa: RUF001
            f"超过单个需求的工作容量 {capacity}"
            f"（每次 Coder 最多 {max_steps_per_run} 步 × {coder_runs} 次）。"  # noqa: RUF001
            "请把需求拆分成更小的需求，或合并实现步骤后重新设计。"  # noqa: RUF001
        )
        self.step_count = step_count
        self.capacity = capacity


class CoderWorkSlice(DomainModel):
    kind: Literal["coder_work_slice_v1"] = "coder_work_slice_v1"
    task_id: NonEmptyStr
    attempt: Annotated[StrictInt, Field(ge=1)]
    source_revision: NonEmptyStr
    plan_artifact_id: NonEmptyStr
    plan_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    window: PlanExecutionWindow
    authorized_work_remaining: Annotated[StrictInt, Field(ge=1)]
    completed_step_ids: tuple[NonEmptyStr, ...]
    selected_step_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    later_step_ids: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        ensure_unique(
            (*self.completed_step_ids, *self.selected_step_ids, *self.later_step_ids),
            "work-slice step partition",
        )
        return self


class PlannedVerificationInspection(DomainModel):
    """An explicit approved inspection target, never a test or verdict."""

    kind: Literal["document", "source", "native_ui"]
    paths: tuple[NonEmptyStr, ...] = ()
    checklist: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    scenario_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        ensure_unique(self.paths, "inspection paths")
        ensure_unique(self.checklist, "inspection checklist")
        if self.kind == "native_ui":
            if self.scenario_sha256 is None:
                raise ValueError("native UI inspection requires an exact registered scenario")
        elif not self.paths or self.scenario_sha256 is not None:
            raise ValueError("source/document inspection requires files and no UI scenario")
        return self


def validate_inspection_levels(
    inspection: PlannedVerificationInspection, levels: tuple[str, ...]
) -> None:
    # Inspection cannot replace an independent unit/integration/e2e test. These
    # canonical levels are part of the structured contract, not prose guesses.
    allowed = {
        "document": {"documentation", "document"},
        "source": {"inspection", "source-inspection", "review"},
        "native_ui": {"ui", "native-ui", "ui-inspection"},
    }
    if not levels or any(level.casefold() not in allowed[inspection.kind] for level in levels):
        raise ValueError("inspection cannot weaken the approved verification levels")


class PlannedVerificationRequirement(DomainModel):
    id: NonEmptyStr
    role: Literal[AgentRole.QA, AgentRole.REVIEWER]
    criterion_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    inspection: PlannedVerificationInspection | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    verification_levels: tuple[NonEmptyStr, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    # A missing path can be planned for creation. This does not waive the later
    # candidate-file and independent-verdict gates.
    planned_new_files: tuple[NonEmptyStr, ...] = ()
    controlled_capability_kind: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_unique_refs(self) -> Self:
        ensure_unique(self.criterion_ids, "preflight criterion IDs")
        ensure_unique(self.planned_new_files, "preflight planned test files")
        if (self.argv is None) == (self.inspection is None):
            raise ValueError("verification requires exactly one command or inspection")
        if self.inspection is not None:
            validate_inspection_levels(self.inspection, self.verification_levels or ())
            if self.inspection.kind == "native_ui":
                if self.controlled_capability_kind != "macos_mock_ax_v1":
                    raise ValueError("native UI inspection requires its registered executor")
            elif self.controlled_capability_kind is not None:
                raise ValueError("source/document inspection cannot declare an executor")
        return self
