"""The actual joint entry uses Manager routing and keeps planning history durable."""

from pathlib import Path

import pytest

from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage, digest
from ai_software_engineer.multi_directory.planning import (
    compile_joint_plan,
    joint_planning_decision,
)
from ai_software_engineer.multi_directory.production import DerivedStageInputs
from ai_software_engineer.multi_directory.service import JointDeliveryService, UpgradeJointPlanning
from ai_software_engineer.planning.gate import PlanningMode
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.manager.test_joint_contracts import checkpoint
from tests.manager.test_joint_planner_feedback import DeliveryReached, PlanningBackend
from tests.manager.test_single_repository_acceptance import _single_checkpoint


def _seed(tmp_path: Path) -> tuple[JointDeliveryService, PlanningBackend, JointCheckpoint]:
    base = _single_checkpoint(tmp_path)
    assert base.plan is not None
    backend = PlanningBackend(base.plan)
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Project")
    service = JointDeliveryService(backend=backend, team=team, project=project)
    seed = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "stage": JointStage.PLANNING,
            "plan": None,
            "children": (),
            "integration": None,
            "attempts": {},
        }
    )
    service.journal.append(seed, expected=None)
    return service, backend, seed


def test_joint_simple_path_has_zero_planner_calls_and_persists_gate(tmp_path: Path) -> None:
    service, backend, seed = _seed(tmp_path)
    with pytest.raises(DeliveryReached):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    result = service.status(seed.delivery_id).checkpoint
    assert not backend.inputs
    assert result.planning_decision is not None
    assert result.planning_decision.mode is PlanningMode.SIMPLE
    assert result.plan is not None and result.plan.units[0].plan.work_graph is not None
    assert result.attempts.get("plan", 0) == 0
    assert result.approval == seed.approval
    result.validate_integrity()


def test_human_upgrade_is_audited_and_cannot_be_removed(tmp_path: Path) -> None:
    service, backend, seed = _seed(tmp_path)
    result = service.upgrade_planning(
        UpgradeJointPlanning(
            delivery_id=seed.delivery_id,
            expected_checkpoint_sha256=seed.checkpoint_sha256,
            operator_id="human_owner",
            rationale="Request explicit task planning",
        )
    ).checkpoint
    assert result.planning_decision is not None
    assert result.planning_decision.mode is PlanningMode.COMPLEX
    assert result.planning_upgrade is not None
    assert service.journal.history(seed.delivery_id)[0] == seed
    with pytest.raises(ValueError, match="immutable"):
        service._save(result, planning_upgrade=None, planning_decision=None)
    with pytest.raises(DeliveryReached):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert len(backend.inputs) == 1
    persisted = service.status(seed.delivery_id).checkpoint
    assert persisted.planning_upgrade == result.planning_upgrade


def test_bounded_parallel_proposal_obeys_dependencies_and_serial_role_contract(
    tmp_path: Path,
) -> None:
    base = checkpoint(tmp_path)
    assert base.plan is not None and base.design is not None and base.product_spec is not None
    independent = base.plan.model_copy(
        update={
            "max_parallelism": 2,
            "units": tuple(unit.model_copy(update={"depends_on": ()}) for unit in base.plan.units),
        }
    )
    plan = compile_joint_plan(base, independent)
    plan.validate_for(base.scope, base.product_spec, base.design)
    assert len(plan.ready_units(frozenset())) == 2
    assert all(
        tuple(phase.role for phase in unit.plan.phases) == ("coder", "qa", "reviewer")
        for unit in plan.units
    )
    assert len(base.plan.ready_units(frozenset())) == 1
    assert joint_planning_decision(base).reason_codes[:2] == (
        "MULTIPLE_REPOSITORIES",
        "MULTIPLE_MODULES",
    )
    with pytest.raises(ValueError, match="dependency"):
        plan.model_copy(
            update={
                "units": (
                    plan.units[0].model_copy(update={"depends_on": (plan.units[1].unit_id,)}),
                    plan.units[1],
                )
            }
        ).validate_for(base.scope, base.product_spec, base.design)
    assert digest(base.plan) != digest(plan)


def test_complex_missing_graph_is_rejected_then_revised_with_feedback(tmp_path: Path) -> None:
    service, backend, seed = _seed(tmp_path)
    upgraded = service.upgrade_planning(
        UpgradeJointPlanning(
            delivery_id=seed.delivery_id,
            expected_checkpoint_sha256=seed.checkpoint_sha256,
            operator_id="human_owner",
            rationale="Require explicit work packages",
        )
    ).checkpoint
    valid = backend.plan
    backend.plan = valid.model_copy(
        update={
            "units": tuple(
                unit.model_copy(update={"plan": unit.plan.model_copy(update={"work_graph": None})})
                for unit in valid.units
            )
        }
    )
    with pytest.raises(ValueError, match="COMPLEX planning requires"):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    rejected = service.status(seed.delivery_id).checkpoint
    assert rejected.plan is None and not rejected.children
    assert rejected.planning_feedback is not None
    assert rejected.planning_feedback.previous_plan == backend.plan
    assert rejected.planning_decision == upgraded.planning_decision
    backend.plan = valid
    with pytest.raises(DeliveryReached):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    accepted = service.status(seed.delivery_id).checkpoint
    assert accepted.plan is not None
    assert accepted.plan.previous_plan_sha256 == digest(rejected.planning_feedback.previous_plan)
    assert accepted.plan.feedback_sha256 == digest(rejected.planning_feedback)
    assert len(backend.inputs) == 2


def test_historical_approved_plan_projects_without_rewriting_its_hash(tmp_path: Path) -> None:
    original = checkpoint(tmp_path)
    assert original.plan is not None
    old_plan = original.plan.model_copy(
        update={
            "units": tuple(
                unit.model_copy(update={"plan": unit.plan.model_copy(update={"work_graph": None})})
                for unit in original.plan.units
            )
        }
    )
    historical = JointCheckpoint.seal({**original.to_wire(), "plan": old_plan})
    previous_sha = historical.checkpoint_sha256
    projection = DerivedStageInputs(historical, historical.scope.units[1].id)
    assert projection.plan.work_graph is not None
    assert projection.design.complexity_facts is not None
    assert projection.design.complexity_facts.work_package_dependencies
    assert historical.checkpoint_sha256 == previous_sha
    assert historical.plan == old_plan
    historical.validate_integrity()


@pytest.mark.parametrize("invalid", ("components", "steps", "test_levels", "dependency"))
def test_joint_semantic_rejection_is_durable_and_reaches_revised_attempt(
    tmp_path: Path, invalid: str
) -> None:
    service, backend, seed = _seed(tmp_path)
    service.upgrade_planning(
        UpgradeJointPlanning(
            delivery_id=seed.delivery_id,
            expected_checkpoint_sha256=seed.checkpoint_sha256,
            operator_id="human_owner",
            rationale="Require explicit work packages",
        )
    )
    valid = backend.plan
    unit = valid.units[0]
    graph = unit.plan.work_graph
    assert graph is not None
    package = graph.packages[0]
    if invalid == "dependency":
        changed = unit.model_copy(update={"depends_on": (unit.unit_id,)})
    else:
        if invalid == "components":
            package = package.model_copy(update={"component_ids": ("component_unknown",)})
        elif invalid == "steps":
            package = package.model_copy(update={"step_ids": ("design_step_unknown",)})
        else:
            package = package.model_copy(
                update={
                    "tests": tuple(
                        test.model_copy(update={"level": "smoke"}) for test in package.tests
                    ),
                }
            )
        changed = unit.model_copy(
            update={
                "plan": unit.plan.model_copy(
                    update={
                        "work_graph": graph.model_copy(update={"packages": (package,)}),
                    }
                )
            }
        )
    backend.plan = valid.model_copy(update={"units": (changed,)})
    with pytest.raises(ValueError):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    rejected = service.status(seed.delivery_id).checkpoint
    assert rejected.stage is JointStage.PLANNING and rejected.plan is None
    assert rejected.planning_feedback is not None
    assert rejected.planning_feedback.previous_plan == backend.plan
    assert not rejected.children
    expected_attempts = 3 if invalid == "test_levels" else 1
    assert rejected.attempts["plan"] == expected_attempts
    assert len(backend.inputs) == expected_attempts
    backend.plan = valid
    restarted = JointDeliveryService(
        backend=backend,
        team=service.team,
        project=service.project,
        execution_retry_policy=ExecutionRetryPolicy(planner=StageRetryPolicy(max_attempts=4)),
    )
    with pytest.raises(DeliveryReached):
        restarted.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    accepted = restarted.status(seed.delivery_id).checkpoint
    assert accepted.plan is not None and accepted.plan.version == 2
    assert accepted.attempts["plan"] == expected_attempts + 1
    assert accepted.plan.previous_plan_sha256 == digest(rejected.planning_feedback.previous_plan)
    assert backend.inputs[-1]["planning_feedback"] == rejected.planning_feedback.to_wire()
