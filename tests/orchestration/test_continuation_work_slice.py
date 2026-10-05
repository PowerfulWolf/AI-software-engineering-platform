"""A continuation keeps frozen work authority and exactly charges local windows."""

import pytest

from ai_software_engineer.agents.continuation import same_continuation_inputs
from ai_software_engineer.domain.coder_work import successor_coder_work_slice
from ai_software_engineer.domain.continuation import ContinuationCause
from ai_software_engineer.domain.execution_window import CoderWorkSlice, PlanExecutionWindow
from tests.orchestration.test_native_continuation_v2 import (
    V2Fixture,
)
from tests.orchestration.test_native_continuation_v2 import (
    denied_paths as denied_paths,
)
from tests.orchestration.test_native_continuation_v2 import (
    transient_limit as transient_limit,
)
from tests.orchestration.test_native_continuation_v2 import (
    v2_fixture as v2_fixture,
)
from tests.orchestration.test_native_continuation_v2 import (
    work_limit as work_limit,
)


def _work(f: V2Fixture) -> CoderWorkSlice:
    return CoderWorkSlice(
        task_id=f.task.id,
        attempt=1,
        source_revision=f.task.base_ref,
        plan_artifact_id="art_plan_001",
        plan_sha256="a" * 64,
        window=PlanExecutionWindow.for_seconds(1800),
        authorized_work_remaining=5,
        completed_step_ids=(),
        selected_step_ids=("step_1", "step_2"),
        later_step_ids=("step_3", "step_4", "step_5", "step_6"),
    )


@pytest.mark.parametrize("provider", [False, True])
def test_successor_request_exactly_preserves_frozen_slice_and_recomputes_budget(
    v2_fixture: V2Fixture,
    provider: bool,
) -> None:
    f = v2_fixture
    old = f.request.model_copy(update={"work_slice": _work(f)})
    assert old.work_slice is not None
    work = successor_coder_work_slice(old.work_slice, consume_work=not provider)
    new = old.model_copy(
        update={
            "run_id": "run_slice_next",
            "context_manifest_id": "ctx_" + "b" * 64,
            "attempt": 2,
            "work_slice": work,
        }
    )
    cause: ContinuationCause = "provider_transient" if provider else "local_execution_limit"
    assert same_continuation_inputs(new, old, cause=cause)
    assert work.authorized_work_remaining == (5 if provider else 4)
    assert (*work.selected_step_ids, *work.later_step_ids) == (
        *old.work_slice.selected_step_ids,
        *old.work_slice.later_step_ids,
    )
    wrong = new.model_copy(
        update={"work_slice": work.model_copy(update={"authorized_work_remaining": 6})}
    )
    assert not same_continuation_inputs(wrong, old, cause=cause)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_revision", "b" * 40),
        ("plan_sha256", "b" * 64),
        ("completed_step_ids", ("step_3",)),
        ("later_step_ids", ("step_5", "step_6")),
        ("window", PlanExecutionWindow.for_seconds(3600)),
    ],
)
def test_slice_cannot_expand_or_erase_authority_on_replacement(
    v2_fixture: V2Fixture,
    field: str,
    value: object,
) -> None:
    old = v2_fixture.request.model_copy(update={"work_slice": _work(v2_fixture)})
    assert old.work_slice is not None
    work = successor_coder_work_slice(old.work_slice, consume_work=True)
    new = old.model_copy(
        update={
            "run_id": "run_slice_next",
            "context_manifest_id": "ctx_" + "b" * 64,
            "attempt": 2,
            "work_slice": work.model_copy(update={field: value}),
        }
    )
    assert not same_continuation_inputs(new, old, cause="local_execution_limit")
