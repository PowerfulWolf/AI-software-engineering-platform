"""Frozen work budgets and exact serial progress partitions.

These are deterministic helper contracts. The production adapter/claim/candidate
checks must additionally be exercised through the public delivery factory.
"""

from __future__ import annotations

import pytest

from ai_software_engineer.artifacts import artifact_digest
from ai_software_engineer.domain import (
    AgentRole,
    CoderProgressArtifact,
    PlanAcceptanceMapping,
    PlanArtifact,
    PlanContent,
    PlanStep,
    Task,
    TaskStatus,
)
from ai_software_engineer.domain.coder_work import CoderSliceRejectionCode
from ai_software_engineer.domain.execution_window import PlanExecutionWindow
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure, DeliveryRetryPolicy
from ai_software_engineer.planning.execution_window import (
    CoderSliceRejected,
    select_coder_work_slice,
    validate_coder_slice_output,
)
from tests.domain.factories import (
    make_coder_progress_artifact,
    make_implementation_artifact,
    make_plan_artifact,
    make_task,
)


def _task(*, attempt: int = 1, transient_failures: int = 0) -> Task:
    base = make_task()
    assert base.constraints is not None
    policy = DeliveryRetryPolicy(max_work_attempts=3)
    return Task.model_validate(
        {
            **base.to_wire(),
            "status": TaskStatus.IMPLEMENTING.value,
            "attempts": attempt,
            "base_ref": "a" * 40,
            "retry_policy": policy.to_wire(),
            "max_attempts": policy.execution_limit,
            "constraints": {**base.constraints.to_wire(), "max_attempts": policy.execution_limit},
            "retry_failures": [
                DeliveryRetryFailure(
                    role=AgentRole.CODER,
                    attempt=index,
                    code="PROVIDER_UNAVAILABLE",
                ).to_wire()
                for index in range(1, transient_failures + 1)
            ],
        }
    )


def _plan(count: int = 16) -> PlanArtifact:
    base = make_plan_artifact()
    ids = tuple(f"step_{index:02d}" for index in range(1, count + 1))
    content = PlanContent(
        execution_window=PlanExecutionWindow.for_seconds(1800),
        goal=base.content.goal,
        assumptions=base.content.assumptions,
        steps=tuple(
            PlanStep(
                step_id=step_id,
                description="Implement one approved serial step",
                files=("src/example.py",),
                verification="Run the mapped focused test",
            )
            for step_id in ids
        ),
        acceptance_mapping=(
            PlanAcceptanceMapping(
                criterion_id="ac_models_01",
                step_ids=ids,
                test_strategy="Focused independent acceptance",
            ),
        ),
        risks=base.content.risks,
    )
    return base.model_copy(update={"content": content})


def _progress(completed: tuple[str, ...], remaining: tuple[str, ...]) -> CoderProgressArtifact:
    base = make_coder_progress_artifact()
    return CoderProgressArtifact.model_validate(
        {
            **base.to_wire(),
            "content": {
                **base.content.to_wire(),
                "completed_step_ids": list(completed),
                "remaining_step_ids": list(remaining),
            },
        }
    )


def test_sixteen_steps_are_aggregated_with_one_work_slot_reserved_for_rework() -> None:
    plan = _plan()
    first = select_coder_work_slice(
        _task(),
        plan,
        attempt=1,
        source_revision="a" * 40,
        progress=None,
    )
    assert first is not None
    assert first.authorized_work_remaining == 3
    assert len(first.selected_step_ids) == len(first.later_step_ids) == 8
    checkpoint = _progress(first.selected_step_ids, first.later_step_ids)
    validate_coder_slice_output(first, checkpoint)
    second = select_coder_work_slice(
        _task(attempt=2),
        plan,
        attempt=2,
        source_revision="a" * 40,
        progress=checkpoint,
    )
    assert second is not None
    assert second.selected_step_ids == first.later_step_ids
    assert second.completed_step_ids == first.selected_step_ids
    assert second.later_step_ids == ()
    assert second.authorized_work_remaining == 2
    validate_coder_slice_output(second, make_implementation_artifact())


def test_final_work_slot_aggregates_all_remaining_steps() -> None:
    plan = _plan()
    work = select_coder_work_slice(
        _task(attempt=3),
        plan,
        attempt=3,
        source_revision="a" * 40,
        progress=None,
    )
    assert work is not None
    assert work.authorized_work_remaining == 1
    assert len(work.selected_step_ids) == 16
    assert work.later_step_ids == ()


def test_transient_execution_id_does_not_spend_coder_work_slots() -> None:
    work = select_coder_work_slice(
        _task(attempt=3, transient_failures=2),
        _plan(),
        attempt=3,
        source_revision="a" * 40,
        progress=None,
    )
    assert work is not None
    assert work.authorized_work_remaining == 3
    assert len(work.selected_step_ids) == 8


def test_progress_can_finish_only_part_of_the_selected_slice_and_keeps_all_later_steps() -> None:
    plan = _plan(4)
    work = select_coder_work_slice(
        _task(),
        plan,
        attempt=1,
        source_revision="a" * 40,
        progress=None,
    )
    assert work is not None
    progress = _progress(("step_01",), ("step_02", "step_03", "step_04"))
    validate_coder_slice_output(work, progress)


@pytest.mark.parametrize(
    ("completed", "remaining"),
    [
        (("step_01",), ("step_02", "step_03")),
        (("step_01", "step_03"), ("step_02", "step_04")),
        (("step_01",), ("step_02", "step_03", "step_04", "step_foreign")),
    ],
)
def test_progress_cannot_drop_deferred_steps_complete_unselected_work_or_add_foreign_steps(
    completed: tuple[str, ...],
    remaining: tuple[str, ...],
) -> None:
    work = select_coder_work_slice(
        _task(),
        _plan(4),
        attempt=1,
        source_revision="a" * 40,
        progress=None,
    )
    assert work is not None
    with pytest.raises(CoderSliceRejected):
        validate_coder_slice_output(work, _progress(completed, remaining))


def test_progress_cannot_revoke_a_previous_completed_step() -> None:
    plan = _plan(4)
    prior = _progress(("step_01",), ("step_02", "step_03", "step_04"))
    work = select_coder_work_slice(
        _task(attempt=2),
        plan,
        attempt=2,
        source_revision="a" * 40,
        progress=prior,
    )
    assert work is not None
    with pytest.raises(CoderSliceRejected, match="erase"):
        validate_coder_slice_output(
            work, _progress(("step_02",), ("step_01", "step_03", "step_04"))
        )


def test_partial_slice_cannot_publish_a_complete_implementation_report() -> None:
    work = select_coder_work_slice(
        _task(),
        _plan(4),
        attempt=1,
        source_revision="a" * 40,
        progress=None,
    )
    assert work is not None and work.later_step_ids
    with pytest.raises(CoderSliceRejected, match="complete candidate") as rejected:
        validate_coder_slice_output(work, make_implementation_artifact())
    assert rejected.value.code is CoderSliceRejectionCode.PARTIAL_CANDIDATE


def test_current_reservation_and_progress_partition_must_be_exact() -> None:
    plan = _plan(4)
    with pytest.raises(CoderSliceRejected, match="reservation"):
        select_coder_work_slice(_task(), plan, attempt=2, source_revision="a" * 40, progress=None)
    prior = _progress(("step_01",), ("step_02", "step_03"))
    with pytest.raises(CoderSliceRejected, match="exact complete"):
        select_coder_work_slice(_task(), plan, attempt=1, source_revision="a" * 40, progress=prior)
    wrong = prior.model_copy(update={"source_revision": "f" * 40})
    with pytest.raises(CoderSliceRejected, match="another Task or revision"):
        select_coder_work_slice(_task(), plan, attempt=1, source_revision="a" * 40, progress=wrong)


def test_legacy_plan_keeps_exact_wire_digest_and_receives_no_new_execution_policy() -> None:
    legacy = make_plan_artifact()
    assert "execution_window" not in legacy.content.to_wire()
    assert "verification_requirements" not in legacy.content.to_wire()
    assert (
        artifact_digest(legacy)
        == "5b7a1848b49b629f403b3970e0a3a5580cb5b7255985b8f4ce64c33dd06d866b"
    )
    assert (
        select_coder_work_slice(
            _task(),
            legacy,
            attempt=1,
            source_revision="a" * 40,
            progress=None,
        )
        is None
    )
    reloaded = PlanArtifact.model_validate_json(legacy.model_dump_json())
    assert reloaded.to_wire() == legacy.to_wire()
    assert artifact_digest(reloaded) == artifact_digest(legacy)


def _bounded_plan(count: int, *, steps_per_run: int = 3, coder_runs: int = 3) -> PlanArtifact:
    plan = _plan(count)
    window = PlanExecutionWindow.for_seconds(
        1800, max_steps_per_run=steps_per_run, max_coder_runs=coder_runs
    )
    return plan.model_copy(
        update={"content": plan.content.model_copy(update={"execution_window": window})}
    )


def test_legacy_window_wire_omits_capacity_and_keeps_old_semantics() -> None:
    window = PlanExecutionWindow.for_seconds(1800)
    assert window.to_wire() == {
        "kind": "serial_coder_window_v1",
        "hard_seconds": 1800,
        "finalization_reserve_seconds": 300,
        "reserve_rework_attempts": 1,
    }
    assert window.step_capacity is None
    window.validate_step_count(100)


def test_bounded_window_caps_each_coder_run_at_its_step_limit() -> None:
    plan = _bounded_plan(6)
    first = select_coder_work_slice(
        _task(), plan, attempt=1, source_revision="a" * 40, progress=None
    )
    assert first is not None
    assert len(first.selected_step_ids) == 3
    assert len(first.later_step_ids) == 3
    checkpoint = _progress(first.selected_step_ids, first.later_step_ids)
    validate_coder_slice_output(first, checkpoint)
    second = select_coder_work_slice(
        _task(attempt=2), plan, attempt=2, source_revision="a" * 40, progress=checkpoint
    )
    assert second is not None
    assert second.selected_step_ids == first.later_step_ids
    assert second.later_step_ids == ()


def test_bounded_window_keeps_all_rework_reachable_on_the_last_slot() -> None:
    # Rework after QA FAIL re-enters with no progress; one slot must still be
    # able to publish a complete candidate instead of a stranded partial slice.
    work = select_coder_work_slice(
        _task(attempt=3), _bounded_plan(6), attempt=3, source_revision="a" * 40, progress=None
    )
    assert work is not None
    assert len(work.selected_step_ids) == 6
    assert work.later_step_ids == ()
    validate_coder_slice_output(work, make_implementation_artifact())


def test_bounded_window_finishes_a_small_plan_in_one_run() -> None:
    work = select_coder_work_slice(
        _task(), _bounded_plan(2), attempt=1, source_revision="a" * 40, progress=None
    )
    assert work is not None
    assert len(work.selected_step_ids) == 2
    assert work.later_step_ids == ()


def test_bounded_window_fills_runs_up_to_the_cap() -> None:
    work = select_coder_work_slice(
        _task(), _bounded_plan(4), attempt=1, source_revision="a" * 40, progress=None
    )
    assert work is not None
    assert len(work.selected_step_ids) == 3
    assert len(work.later_step_ids) == 1


def test_oversized_plan_is_rejected_before_any_coder_run() -> None:
    from ai_software_engineer.domain.execution_window import PlanExceedsWorkCapacity

    window = PlanExecutionWindow.for_seconds(1800, max_steps_per_run=3, max_coder_runs=3)
    assert window.step_capacity == 6
    window.validate_step_count(6)
    with pytest.raises(PlanExceedsWorkCapacity, match="需求过大") as raised:
        window.validate_step_count(16)
    assert raised.value.step_count == 16
    assert raised.value.capacity == 6


def test_bounded_window_requires_complete_and_usable_capacity() -> None:
    with pytest.raises(ValueError, match="both max_steps_per_run and max_coder_runs"):
        PlanExecutionWindow.for_seconds(1800, max_steps_per_run=3)
    with pytest.raises(ValueError, match="at least one Coder run"):
        PlanExecutionWindow.for_seconds(1800, max_steps_per_run=3, max_coder_runs=1)


def test_bounded_window_round_trips_its_capacity() -> None:
    window = PlanExecutionWindow.for_seconds(1800, max_steps_per_run=2, max_coder_runs=4)
    assert window.to_wire()["max_steps_per_run"] == 2
    assert PlanExecutionWindow.model_validate(window.to_wire()) == window


def test_production_composition_uses_the_bounded_default() -> None:
    from ai_software_engineer.domain.execution_window import (
        DEFAULT_CODER_STEPS_PER_RUN,
        bounded_coder_window,
    )

    window = bounded_coder_window(1800, max_work_attempts=3)
    assert window.max_steps_per_run == DEFAULT_CODER_STEPS_PER_RUN
    assert window.step_capacity == DEFAULT_CODER_STEPS_PER_RUN * 2
    assert bounded_coder_window(1800, max_work_attempts=1).step_capacity == (
        DEFAULT_CODER_STEPS_PER_RUN
    )
