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
    with pytest.raises(CoderSliceRejected, match="complete candidate"):
        validate_coder_slice_output(work, make_implementation_artifact())


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
