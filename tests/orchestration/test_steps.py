"""A queue permit bounds execution without replacing the existing verdict gates."""

from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.orchestration import RetryDeliveryResult
from ai_software_engineer.orchestration.steps import BoundedRunControl, RoleRunPending
from tests.orchestration.test_retry import ScriptedAdapter, _runner


def test_probe_and_each_permit_execute_only_one_delivery_role(tmp_path: Path) -> None:
    adapter = ScriptedAdapter()
    task, repository, runner = _runner(tmp_path, adapter)
    runner.execution_control = BoundedRunControl(repository)
    with pytest.raises(RoleRunPending) as pending:
        runner.run_task(task.id)
    assert pending.value.boundary.role is AgentRole.CODER
    assert [r.role for r in adapter.requests] == [AgentRole.ORCHESTRATOR]
    assert repository.get(task.id).status is TaskStatus.IMPLEMENTING
    for role, next_role in ((AgentRole.CODER, AgentRole.QA), (AgentRole.QA, AgentRole.REVIEWER)):
        permit = pending.value.boundary
        assert permit.role is role
        runner.execution_control = BoundedRunControl(repository, permit=permit)
        with pytest.raises(RoleRunPending) as pending:
            runner.run_task(task.id)
        assert pending.value.boundary.role is next_role
        assert adapter.requests[-1].role is role
    runner.execution_control = BoundedRunControl(repository, permit=pending.value.boundary)
    result = runner.run_task(task.id)
    assert isinstance(result, RetryDeliveryResult)
    assert result.task.status is TaskStatus.DONE
    assert [r.role for r in adapter.requests] == list(AgentRole)


def test_transient_retry_yields_before_a_second_coder_invocation(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(coder_timeouts=(1,))
    task, repository, runner = _runner(tmp_path, adapter)
    runner.execution_control = BoundedRunControl(repository)
    with pytest.raises(RoleRunPending) as first:
        runner.run_task(task.id)
    runner.execution_control = BoundedRunControl(repository, permit=first.value.boundary)
    with pytest.raises(RoleRunPending) as second:
        runner.run_task(task.id)
    assert second.value.boundary.role is AgentRole.CODER
    assert second.value.boundary.attempt == 2
    assert len([r for r in adapter.requests if r.role is AgentRole.CODER]) == 1


def test_lost_owner_cannot_seal_artifact_or_advance_task(tmp_path: Path) -> None:
    lost = False

    def guard() -> None:
        if lost:
            raise RuntimeError("lost lease")

    class LosingAdapter(ScriptedAdapter):
        def run(self, request):  # type: ignore[no-untyped-def]
            nonlocal lost
            result = super().run(request)
            if request.role is AgentRole.CODER:
                lost = True
            return result

    adapter = LosingAdapter()
    task, repository, runner = _runner(tmp_path, adapter)
    runner.execution_control = BoundedRunControl(repository)
    with pytest.raises(RoleRunPending) as pending:
        runner.run_task(task.id)
    runner.execution_control = BoundedRunControl(
        repository, permit=pending.value.boundary, guard=guard
    )
    with pytest.raises(RuntimeError, match="lost lease"):
        runner.run_task(task.id)
    assert repository.get(task.id).status is TaskStatus.IMPLEMENTING
    assert len(runner._artifact_store.list_for_task(task.id)) == 1
