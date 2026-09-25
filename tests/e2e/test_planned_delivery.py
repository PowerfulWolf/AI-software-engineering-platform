"""Recovery contracts at the DispatchCommit-to-Task delivery seam."""

from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    NetworkAccess,
    PlanArtifact,
    TaskStatus,
    derive_delivery_task,
)
from ai_software_engineer.domain.project_delivery import (
    ExecutionPlan,
    PlanTestItem,
    PlanWorkGraph,
    PlanWorkPackage,
)
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure, DeliveryRetryPolicy
from ai_software_engineer.manager.dispatch import DispatchCommitRecord
from ai_software_engineer.orchestration.planned_delivery import (
    DispatchTaskConflict,
    DispatchTaskMaterializer,
    ExecutionPlanAgentAdapter,
)
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import make_state_event
from tests.manager.test_contracts import NOW, stage_chain


class _Dispatch:
    def __init__(self, task: object) -> None:
        self.task = task

    def validate_integrity(self) -> None:
        return None


def _facts(tmp_path: Path):  # type: ignore[no-untyped-def]
    prepared, request, spec, approved, design, plan = stage_chain(tmp_path)
    task = derive_delivery_task(
        prepared,
        request,
        spec,
        approved,
        design,
        plan,
        task_id="task_planned_delivery_001",
        repository=prepared.repository_root,
        base_ref="a" * 40,
        max_attempts=3,
        created_at=NOW + timedelta(minutes=5),
    )
    return task, spec, design, plan


def test_dispatch_task_is_exact_create_or_compare_across_restart(tmp_path: Path) -> None:
    task, *_ = _facts(tmp_path)
    dispatch = cast(DispatchCommitRecord, _Dispatch(task))
    database = tmp_path / "state.sqlite3"

    with SqliteTaskRepository(database) as repository:
        materializer = DispatchTaskMaterializer(repository)
        assert materializer.materialize(dispatch) == task
        assert materializer.materialize(dispatch) == task

        changed = task.model_copy(update={"description": "different dispatch intent"})
        with pytest.raises(DispatchTaskConflict, match="different dispatch content"):
            materializer.materialize(cast(DispatchCommitRecord, _Dispatch(changed)))


def test_dispatch_replay_after_persisted_transient_failure_retains_runtime(tmp_path: Path) -> None:
    task, *_ = _facts(tmp_path)
    policy = DeliveryRetryPolicy()
    task = task.model_copy(update={"retry_policy": policy, "max_attempts": policy.execution_limit})
    dispatch = cast(DispatchCommitRecord, _Dispatch(task))
    database = tmp_path / "retry.sqlite3"
    with SqliteTaskRepository(database) as repository:
        DispatchTaskMaterializer(repository).materialize(dispatch)
        for index, (before, after) in enumerate(
            (
                (TaskStatus.NEW, TaskStatus.PLANNING),
                (TaskStatus.PLANNING, TaskStatus.IMPLEMENTING),
            )
        ):
            repository.append_event(
                make_state_event(
                    event_id=f"evt_replay_{index}",
                    task_id=task.id,
                    from_status=before,
                    to_status=after,
                ).model_copy(update={"occurred_at": task.updated_at})
            )
        repository.record_attempt(task.id, 1)
        repository.record_retry_failure(
            task.id,
            DeliveryRetryFailure(
                role=AgentRole.CODER,
                attempt=1,
                code="TIMEOUT",
                run_id="run_replay_timeout",
            ),
        )
        current, events = repository.get(task.id), repository.list_events(task.id)
        assert current.attempts == 2

    with SqliteTaskRepository(database) as reopened:
        assert DispatchTaskMaterializer(reopened).materialize(dispatch) == current
        assert reopened.list_events(task.id) == events
        assert current.retry_failures is not None and len(current.retry_failures) == 1


@pytest.mark.parametrize("with_graph", (False, True))
def test_execution_plan_is_mechanically_materialized_as_task_plan(
    tmp_path: Path, with_graph: bool
) -> None:
    task, spec, design, plan = _facts(tmp_path)
    if with_graph:
        plan = ExecutionPlan.create(
            spec,
            design,
            plan_id=plan.id,
            version=1,
            phases=plan.phases,
            created_at=plan.created_at,
            work_graph=PlanWorkGraph(
                packages=(
                    PlanWorkPackage(
                        id="package_delivery",
                        component_ids=tuple(item.id for item in design.components),
                        step_ids=tuple(step.id for step in design.implementation_steps),
                        acceptance_criterion_ids=tuple(
                            item.id for item in spec.acceptance_criteria
                        ),
                        risk=plan.phases[0].risk,
                        checkpoints=("Exact independent acceptance",),
                        tests=tuple(
                            PlanTestItem(
                                id="matrix_" + item.acceptance_criterion_id + "_" + level,
                                acceptance_criterion_ids=(item.acceptance_criterion_id,),
                                level=level,
                                verification="Run the Planner-selected integration matrix",
                            )
                            for item in design.acceptance_mappings
                            for level in (*item.test_levels, "integration")
                        ),
                    ),
                )
            ),
        )
        task = task.model_copy(
            update={
                "metadata": {
                    **task.metadata,
                    "execution_plan_sha256": plan.execution_plan_sha256,
                }
            }
        )
    adapter = ExecutionPlanAgentAdapter(
        task=task,
        product_spec=spec,
        technical_design=design,
        execution_plan=plan,
        agent_id="agent_manager_001",
        agent_version="v0.1",
        created_at=NOW + timedelta(minutes=6),
    )
    request = AgentRequest(
        run_id="run_planned_delivery_001",
        task_id=task.id,
        role=AgentRole.ORCHESTRATOR,
        attempt=1,
        source_revision=task.base_ref,
        context_manifest_id="ctx_" + "c" * 64,
        input_artifact_ids=(),
        permissions=AgentPermissions(
            read_paths=("**",),
            write_paths=(),
            commands=("git status",),
            network=NetworkAccess.NONE,
            can_change_state=True,
        ),
        output_schema="schemas/plan.schema.json",
        timeout_seconds=60,
    )

    result = adapter.run(request)

    assert isinstance(result.artifact, PlanArtifact)
    assert result.artifact.producer.role is AgentRole.ORCHESTRATOR
    assert result.artifact.source_revision == task.base_ref
    assert {mapping.criterion_id for mapping in result.artifact.content.acceptance_mapping} == {
        criterion.id for criterion in task.acceptance_criteria
    }
    assert result.artifact.integrity.validated is False
    if with_graph:
        assert all(
            "Planner-selected integration matrix" in mapping.test_strategy
            for mapping in result.artifact.content.acceptance_mapping
        )


def test_planning_adapter_rejects_a_non_planning_role(tmp_path: Path) -> None:
    task, spec, design, plan = _facts(tmp_path)
    adapter = ExecutionPlanAgentAdapter(
        task=task,
        product_spec=spec,
        technical_design=design,
        execution_plan=plan,
        agent_id="agent_manager_001",
        agent_version="v0.1",
        created_at=NOW,
    )
    request = AgentRequest(
        run_id="run_wrong_role_001",
        task_id=task.id,
        role=AgentRole.CODER,
        attempt=1,
        source_revision=task.base_ref,
        context_manifest_id="ctx_" + "d" * 64,
        input_artifact_ids=(),
        permissions=AgentPermissions(
            read_paths=("**",),
            write_paths=("src/**",),
            commands=("git status",),
            network=NetworkAccess.NONE,
        ),
        output_schema="schemas/coder-output.schema.json",
        timeout_seconds=60,
    )

    with pytest.raises(RuntimeError, match="only accepts"):
        adapter.run(request)

    assert task.status is TaskStatus.NEW
