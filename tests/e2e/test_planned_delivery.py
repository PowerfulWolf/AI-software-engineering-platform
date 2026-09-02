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
from ai_software_engineer.orchestration.planned_delivery import (
    DispatchTaskConflict,
    DispatchTaskMaterializer,
    ExecutionPlanAgentAdapter,
)
from ai_software_engineer.project_manager.dispatch import DispatchCommitRecord
from ai_software_engineer.store import SqliteTaskRepository
from tests.project_manager.test_contracts import NOW, stage_chain


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
        repository=prepared.project_root,
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


def test_execution_plan_is_mechanically_materialized_as_task_plan(tmp_path: Path) -> None:
    task, spec, design, plan = _facts(tmp_path)
    adapter = ExecutionPlanAgentAdapter(
        task=task,
        product_spec=spec,
        technical_design=design,
        execution_plan=plan,
        agent_id="agent_project_manager_001",
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


def test_planning_adapter_rejects_a_non_planning_role(tmp_path: Path) -> None:
    task, spec, design, plan = _facts(tmp_path)
    adapter = ExecutionPlanAgentAdapter(
        task=task,
        product_spec=spec,
        technical_design=design,
        execution_plan=plan,
        agent_id="agent_project_manager_001",
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
        output_schema="schemas/implementation-report.schema.json",
        timeout_seconds=60,
    )

    with pytest.raises(RuntimeError, match="only accepts"):
        adapter.run(request)

    assert task.status is TaskStatus.NEW
