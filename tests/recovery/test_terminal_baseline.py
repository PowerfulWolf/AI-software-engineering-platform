"""Terminal source epochs require exact verified engineering binding history."""

from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.task import Task
from ai_software_engineer.recovery.baseline_source import (
    RecoveryBaselineEpoch,
    read_recovery_baseline_epochs,
    validate_pre_candidate_sources,
)
from tests.domain.factories import NOW, make_state_event
from tests.manager.test_terminal_candidate_reconstruction import _binding, _repository


def test_source_epoch_store_requires_exact_project_scope(tmp_path: Path) -> None:
    from ai_software_engineer.knowledge.models import digest
    from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
    from ai_software_engineer.recovery.models import RecoveryScope
    from tests.manager.test_execution_baseline import authorize, setup

    f = setup(tmp_path)
    facts = f.collector.facts.model_copy(
        update={
            "scope": f.collector.facts.scope.model_copy(
                update={"repository_id": "repository_baseline"}
            )
        }
    )
    f.collector.facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    sidecar = tmp_path / "sidecar"
    f.service.store = FileExecutionBaselineStore(
        sidecar / "state/execution-baselines" / facts.task.id
    )
    plan = f.service.propose(f.target)
    binding = f.service.execute(plan.plan_sha256, authority=authorize(plan))
    scope = RecoveryScope(
        team_id=binding.scope.team_id,
        repository_id=binding.scope.repository_id,
        repository_root=binding.scope.repository_root,
        delivery_id="delivery_baseline",
    )
    files = {p: p.read_bytes() for p in f.service.store.root.rglob("*.json")}
    observed = read_recovery_baseline_epochs(
        sidecar, facts.task, scope, project_id=binding.scope.project_id
    )
    assert observed[0].binding == binding
    with pytest.raises(ValueError, match="scope"):
        read_recovery_baseline_epochs(sidecar, facts.task, scope, project_id="project_other")
    assert files == {p: p.read_bytes() for p in f.service.store.root.rglob("*.json")}


def _task() -> Task:
    return _repository().task


def _event(
    revision: int,
    source: str,
    *,
    attempt: int = 2,
    seconds: int = 1,
) -> StateEvent:
    return make_state_event(event_id=f"evt_epoch_{revision}").model_copy(
        update={
            "source_revision": source,
            "attempt": attempt,
            "occurred_at": NOW + timedelta(seconds=seconds),
        }
    )


def _epoch(task: Task) -> RecoveryBaselineEpoch:
    return RecoveryBaselineEpoch(binding=_binding(task), minimum_attempt=2)


def _events() -> tuple[StateEvent, ...]:
    return (
        _event(1, "a" * 40, attempt=1, seconds=-1),
        _event(2, "d" * 40),
    )


def test_original_epoch_and_exact_new_terminal_epoch_are_accepted() -> None:
    task = _task()
    validate_pre_candidate_sources(task, _events(), (_epoch(task),))


def test_unbound_original_source_keeps_existing_behavior() -> None:
    task = _task()
    validate_pre_candidate_sources(task, (_event(1, task.base_ref),), ())
    with pytest.raises(ValueError, match="source"):
        validate_pre_candidate_sources(task, _events(), ())


@pytest.mark.parametrize("source", ["a" * 40, "b" * 40, "f" * 40])
def test_later_event_cannot_select_unknown_or_stale_source(source: str) -> None:
    task = _task()
    with pytest.raises(ValueError, match="source"):
        validate_pre_candidate_sources(task, (_events()[0], _event(2, source)), (_epoch(task),))


@pytest.mark.parametrize("change", ["time", "attempt", "revision"])
def test_new_source_cannot_precede_its_exact_binding_boundary(change: str) -> None:
    task, epoch = _task(), _epoch(_task())
    events = _events()
    if change == "time":
        events = (events[0], _event(2, "d" * 40, seconds=-1))
    elif change == "attempt":
        events = (events[0], _event(2, "d" * 40, attempt=1))
    else:
        events = (_event(1, "d" * 40), events[1])
    with pytest.raises(ValueError, match=r"source|epoch|attempt"):
        validate_pre_candidate_sources(task, events, (epoch,))


def test_each_historical_event_uses_its_own_epoch() -> None:
    task = _task().model_copy(update={"attempts": 3})
    wire = _binding(task).to_wire()
    wire.pop("binding_sha256")
    first = ExecutionBaselineBinding.create(
        **{
            **wire,
            "prior_source_revision": "a" * 40,
            "execution_base_ref": "b" * 40,
            "execution_source_revision": "b" * 40,
        }
    )
    second = ExecutionBaselineBinding.create(
        **{
            **wire,
            "sequence": 2,
            "previous_binding_sha256": first.binding_sha256,
            "prior_execution_base_ref": "b" * 40,
            "prior_source_revision": "b" * 40,
            "prior_task_revision": 2,
            "completed_at": NOW + timedelta(seconds=2),
        }
    )
    epochs = (
        RecoveryBaselineEpoch(binding=first, minimum_attempt=2),
        RecoveryBaselineEpoch(binding=second, minimum_attempt=3),
    )
    events = (
        _event(1, "a" * 40, attempt=1, seconds=-1),
        _event(2, "b" * 40),
        _event(3, "d" * 40, attempt=3, seconds=3),
    )
    validate_pre_candidate_sources(task, events, epochs)
    # The latest source is known, but cannot authorize an earlier historical event.
    with pytest.raises(ValueError, match="source"):
        validate_pre_candidate_sources(task, (events[0], _event(2, "d" * 40), events[2]), epochs)
    with pytest.raises(ValueError, match="source"):
        validate_pre_candidate_sources(
            task, (*events[:2], _event(3, "b" * 40, attempt=3, seconds=3)), epochs
        )


@pytest.mark.parametrize("change", ["task", "sequence", "revision", "attempt"])
def test_binding_chain_cannot_be_reinterpreted(change: str) -> None:
    task = _task()
    wire = _binding(task).to_wire()
    wire.pop("binding_sha256")
    minimum_attempt = 2
    if change == "task":
        wire["task_id"] = "task_other"
    elif change == "sequence":
        wire["sequence"] = 2
        wire["previous_binding_sha256"] = "c" * 64
    elif change == "revision":
        wire["prior_task_revision"] = 5
    else:
        minimum_attempt = 3
    binding = ExecutionBaselineBinding.create(**wire)
    with pytest.raises(ValueError):
        validate_pre_candidate_sources(
            task,
            _events(),
            (RecoveryBaselineEpoch(binding=binding, minimum_attempt=minimum_attempt),),
        )
