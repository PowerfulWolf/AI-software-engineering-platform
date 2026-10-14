"""Planner rejects verification entries the controlled delivery host cannot run."""

from pathlib import Path

import pytest

from ai_software_engineer.domain.project_delivery import PlanTestItem
from ai_software_engineer.multi_directory.models import JointExecutionPlan
from ai_software_engineer.multi_directory.planning import (
    PlanVerificationFeasibilityError,
    validate_plan_verification_entries,
)
from tests.manager.test_joint_contracts import checkpoint


def _plan(
    tmp_path: Path,
    count: int,
    *,
    argv_prefix: tuple[str, ...] = ("python", "-m", "pytest"),
) -> JointExecutionPlan:
    seed = checkpoint(tmp_path)
    assert seed.plan is not None
    unit = seed.plan.units[0]
    graph = unit.plan.work_graph
    assert graph is not None
    package = graph.packages[0]
    tests = tuple(
        PlanTestItem(
            id=f"test_focused_{index}",
            acceptance_criterion_ids=package.acceptance_criterion_ids,
            level="unit",
            verification="Run the exact focused test node.",
            verification_argv=(
                *argv_prefix,
                "-q",
                f"tests/test_focused_{index}.py::test_focused",
            ),
            controlled_capability_kind="codex_sandbox_pytest_mysql_v1",
        )
        for index in range(count)
    )
    updated_graph = graph.model_copy(
        update={"packages": (package.model_copy(update={"tests": tests}), *graph.packages[1:])}
    )
    return seed.plan.model_copy(
        update={
            "units": (
                unit.model_copy(
                    update={"plan": unit.plan.model_copy(update={"work_graph": updated_graph})}
                ),
                *seed.plan.units[1:],
            )
        }
    )


@pytest.mark.parametrize("count", [33, 64])
def test_registered_python_selection_limit_accepts_k1_matrix(tmp_path: Path, count: int) -> None:
    validate_plan_verification_entries(_plan(tmp_path, count))


def test_registered_python_selection_limit_rejects_the_65th_node(tmp_path: Path) -> None:
    with pytest.raises(PlanVerificationFeasibilityError, match="PYTEST_SELECTION_LIMIT_EXCEEDED"):
        validate_plan_verification_entries(_plan(tmp_path, 65))


def test_new_plan_rejects_node_test_without_a_registered_capability(tmp_path: Path) -> None:
    with pytest.raises(PlanVerificationFeasibilityError, match="UNSUPPORTED_TEST_COMMAND"):
        validate_plan_verification_entries(
            _plan(tmp_path, 1, argv_prefix=("node", "--test")),
        )


def test_new_plan_requires_registered_capability_for_python_pytest(tmp_path: Path) -> None:
    plan = _plan(tmp_path, 1)
    unit = plan.units[0]
    graph = unit.plan.work_graph
    assert graph is not None
    package = graph.packages[0]
    test = package.tests[0].model_copy(update={"controlled_capability_kind": None})
    graph = graph.model_copy(update={"packages": (package.model_copy(update={"tests": (test,)}),)})
    plan = plan.model_copy(
        update={
            "units": (
                unit.model_copy(
                    update={"plan": unit.plan.model_copy(update={"work_graph": graph})}
                ),
            )
        }
    )
    with pytest.raises(PlanVerificationFeasibilityError, match="CONTROLLED_CAPABILITY_REQUIRED"):
        validate_plan_verification_entries(plan)


@pytest.mark.parametrize(
    "node", ["tests/../secrets.py::test_x", "tests/file.py", "tests/file.py::x;evil"]
)
def test_planner_uses_the_real_exact_node_contract(tmp_path: Path, node: str) -> None:
    plan = _plan(tmp_path, 1)
    unit = plan.units[0]
    graph = unit.plan.work_graph
    assert graph is not None
    package = graph.packages[0]
    test = package.tests[0].model_copy(
        update={
            "id": "secret_untrusted_marker",
            "verification_argv": ("pytest", node),
        }
    )
    graph = graph.model_copy(update={"packages": (package.model_copy(update={"tests": (test,)}),)})
    plan = plan.model_copy(
        update={
            "units": (
                unit.model_copy(
                    update={
                        "plan": unit.plan.model_copy(update={"work_graph": graph}),
                    }
                ),
            )
        }
    )
    with pytest.raises(PlanVerificationFeasibilityError, match="PYTEST_SELECTOR_REQUIRED") as error:
        validate_plan_verification_entries(plan)
    assert "secret_untrusted_marker" not in str(error.value)


def test_python_selection_bound_is_per_repository_task(tmp_path: Path) -> None:
    plan = _plan(tmp_path, 64)
    unit = plan.units[0]
    other = unit.model_copy(update={"unit_id": "unit_second_repository"})
    validate_plan_verification_entries(plan.model_copy(update={"units": (unit, other)}))
