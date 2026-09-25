"""Recovery must not inherit the projection's legacy policy exception."""

from ai_software_engineer.domain.retry_policy import DeliveryRetryPolicy
from ai_software_engineer.domain.task import task_matches_dispatch
from tests.domain.factories import make_task


def test_policy_compatibility_is_explicit_and_read_only() -> None:
    legacy = make_task()
    current = legacy.model_copy(update={"retry_policy": DeliveryRetryPolicy()})
    assert not task_matches_dispatch(current, legacy)
    assert task_matches_dispatch(current, legacy, allow_legacy_retry_policy=True)
    assert not task_matches_dispatch(legacy, current, allow_legacy_retry_policy=True)


def test_runtime_comparison_retains_all_immutable_intent() -> None:
    task = make_task()
    for field, value in (
        ("repository", "/workspace/foreign"),
        ("base_ref", "foreign"),
        ("metadata", {"milestone": "foreign"}),
        ("acceptance_criteria", ()),
        ("max_attempts", 10),
        ("owner", "foreign"),
    ):
        assert not task_matches_dispatch(task.model_copy(update={field: value}), task), field
