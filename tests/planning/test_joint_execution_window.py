"""Joint-to-native execution windows stay trusted, frozen, and serial."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_software_engineer.domain.execution_window import PlanExecutionWindow
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.production_agents import ExecutionPlanDraft, _execution_plan
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage, digest
from ai_software_engineer.multi_directory.planning import compile_joint_plan
from ai_software_engineer.multi_directory.production import DerivedStageInputs
from ai_software_engineer.multi_directory.service import (
    CreateRequirement,
    JointDeliveryService,
    UpgradeJointPlanning,
)
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.planning import PlannerAgentRequest, PlannerContextBuilder
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.manager.test_joint_contracts import checkpoint
from tests.manager.test_joint_planner_feedback import DeliveryReached, PlanningBackend
from tests.manager.test_production_backend import _git
from tests.manager.test_single_repository_acceptance import _single_checkpoint
from tests.planning.conftest import execution_plan
from tests.planning.test_agent_contract import _context

WINDOW = PlanExecutionWindow.for_seconds(900)


def _planning_seed(tmp_path: Path) -> tuple[JointDeliveryService, PlanningBackend, JointCheckpoint]:
    base = _single_checkpoint(tmp_path)
    assert base.plan is not None
    backend = PlanningBackend(base.plan)
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Project")
    service = JointDeliveryService(
        backend=backend, team=team, project=project, execution_window=WINDOW
    )
    seed = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "execution_window": WINDOW,
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


def test_new_intake_freezes_window_and_service_restart_does_not_update_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    base = checkpoint(tmp_path)
    assert base.plan is not None
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Project")
    service = JointDeliveryService(
        backend=PlanningBackend(base.plan), team=team, project=project, execution_window=WINDOW
    )
    monkeypatch.setattr(service, "_advance", lambda current: current)
    command = CreateRequirement(
        name="Freeze current bounded window", repository_roots=(str(repository),)
    )
    first = service.create(command).checkpoint
    assert first.execution_window == WINDOW
    restarted = JointDeliveryService(
        backend=PlanningBackend(base.plan),
        team=team,
        project=project,
        execution_window=PlanExecutionWindow.for_seconds(1800),
    )
    monkeypatch.setattr(restarted, "_advance", lambda current: current)
    assert restarted.create(command).checkpoint == first
    assert restarted.journal.history(first.delivery_id) == (first,)


def test_simple_joint_plan_projects_the_exact_window_into_each_native_child(tmp_path: Path) -> None:
    service, backend, seed = _planning_seed(tmp_path)
    with pytest.raises(DeliveryReached):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    accepted = service.status(seed.delivery_id).checkpoint
    assert not backend.inputs and accepted.plan is not None
    assert accepted.plan.units[0].plan.execution_window == WINDOW
    projected = DerivedStageInputs(accepted, accepted.scope.units[0].id)
    assert projected.plan.execution_window == WINDOW
    assert accepted.approval == seed.approval
    assert service.journal.history(seed.delivery_id)[0] == seed


def test_complex_joint_planner_sees_frozen_window_and_omission_is_mechanically_filled(
    tmp_path: Path,
) -> None:
    service, backend, seed = _planning_seed(tmp_path)
    service.upgrade_planning(
        UpgradeJointPlanning(
            delivery_id=seed.delivery_id,
            expected_checkpoint_sha256=seed.checkpoint_sha256,
            operator_id="human_owner",
            rationale="Require explicit bounded work packages",
        )
    )
    with pytest.raises(DeliveryReached):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert len(backend.inputs) == 1
    assert backend.inputs[0]["execution_window"] == WINDOW.to_wire()
    accepted = service.status(seed.delivery_id).checkpoint
    assert accepted.plan is not None
    assert accepted.plan.units[0].plan.execution_window == WINDOW
    assert tuple(phase.role for phase in accepted.plan.units[0].plan.phases) == (
        "coder",
        "qa",
        "reviewer",
    )
    accepted.validate_integrity()


def test_joint_planner_cannot_enlarge_window_or_invent_it_for_a_legacy_requirement(
    tmp_path: Path,
) -> None:
    service, backend, seed = _planning_seed(tmp_path)
    assert seed.plan is None
    assert seed.design is not None
    changed = backend.plan.model_copy(
        update={
            "units": tuple(
                unit.model_copy(
                    update={
                        "plan": unit.plan.model_copy(
                            update={
                                "execution_window": PlanExecutionWindow.for_seconds(1800),
                            }
                        )
                    }
                )
                for unit in backend.plan.units
            )
        }
    )
    with pytest.raises(ValueError, match="trusted frozen"):
        compile_joint_plan(seed, changed)
    legacy = JointCheckpoint.seal({**seed.to_wire(), "execution_window": None})
    with pytest.raises(ValueError, match="trusted frozen"):
        compile_joint_plan(legacy, changed)
    assert seed == service.journal.current(seed.delivery_id)


def test_frozen_requirement_window_is_immutable_and_legacy_wire_omits_it(tmp_path: Path) -> None:
    service, _, seed = _planning_seed(tmp_path)
    with pytest.raises(ValueError, match="immutable"):
        service._save(seed, execution_window=PlanExecutionWindow.for_seconds(1800))
    assert service.journal.current(seed.delivery_id) == seed
    legacy = checkpoint(tmp_path / "legacy")
    assert legacy.execution_window is None and legacy.plan is not None
    assert "execution_window" not in legacy.to_wire()
    assert all("execution_window" not in unit.plan.to_wire() for unit in legacy.plan.units)
    original_hash = digest(legacy.plan)
    journal = JointJournal(tmp_path / "legacy-journal")
    journal.append(legacy, expected=None)
    reopened = JointJournal(tmp_path / "legacy-journal", read_only=True).current(legacy.delivery_id)
    assert reopened == legacy and reopened.plan is not None
    assert digest(reopened.plan) == original_hash


def test_native_planner_rejects_model_window_drift(tmp_path: Path) -> None:
    old = _context(tmp_path)
    context = PlannerContextBuilder().build(
        project_request_revision=old.project_request_revision,
        product_spec=old.product_spec,
        product_approval=old.product_approval,
        technical_design=old.technical_design,
        design_checkpoint=old.design_checkpoint,
        planning_authorization=old.planning_authorization,
        expected_execution_plan_version=old.expected_execution_plan_version,
        built_at=old.built_at,
        execution_window=WINDOW,
    )
    request = PlannerAgentRequest(
        run_id="run_frozen_window",
        repository_id=context.repository_id,
        request_id=context.request_id,
        context=context,
    )
    base = execution_plan(context.product_spec, context.technical_design)
    draft = ExecutionPlanDraft.model_validate(
        {
            "phases": [
                {
                    key: value
                    for key, value in phase.to_wire().items()
                    if key not in {"id", "critical_path"}
                }
                for phase in base.phases
            ],
            "execution_window": WINDOW.to_wire(),
        }
    )
    assert _execution_plan(request, draft).execution_window == WINDOW
    altered = draft.model_copy(update={"execution_window": PlanExecutionWindow.for_seconds(1800)})
    with pytest.raises(ValueError, match="trusted frozen"):
        _execution_plan(request, altered)
