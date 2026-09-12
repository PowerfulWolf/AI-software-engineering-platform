"""Designer rejection feedback survives restart without weakening acceptance guards."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import StructuredModelResult
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.multi_directory.models import (
    JointCheckpoint,
    JointStage,
    JointTechnicalDesign,
    digest,
)
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.manager.test_joint_contracts import checkpoint
from tests.manager.test_joint_planner_feedback import DeliveryReached, PlanningBackend


class DesigningBackend(PlanningBackend):
    def __init__(
        self, cp: JointCheckpoint, designs: list[JointTechnicalDesign | Exception]
    ) -> None:
        assert cp.plan is not None
        super().__init__(cp.plan)
        self.designs = designs
        self.design_inputs: list[Mapping[str, object]] = []

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
    ) -> StructuredModelResult:
        if output_schema.get("title") == "JointTechnicalDesign":
            self.design_inputs.append(input_payload)
            result = self.designs.pop(0)
            if isinstance(result, Exception):
                raise result
            return StructuredModelResult(payload=result.to_wire(), duration_ms=0)
        return super().complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
        )


def setup_design(
    tmp_path: Path,
) -> tuple[JointDeliveryService, DesigningBackend, JointCheckpoint, JointTechnicalDesign]:
    cp = checkpoint(tmp_path)
    assert cp.design is not None
    interface = cp.design.interfaces[0]
    invalid = cp.design.model_copy(
        update={
            "interfaces": (
                interface.model_copy(
                    update={
                        "id": "private-interface-text",
                        "consumers": interface.consumers * 2,
                    }
                ),
            )
        }
    )
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    backend = DesigningBackend(cp, [invalid, cp.design])
    service = JointDeliveryService(backend=backend, team=team, project=project)
    seed = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "stage": JointStage.DESIGNING,
            "design": None,
            "plan": None,
        }
    )
    service.journal.append(seed, expected=None)
    return service, backend, seed, invalid


def test_duplicate_consumers_are_corrected_before_planning(tmp_path: Path) -> None:
    service, backend, seed, invalid = setup_design(tmp_path)
    with pytest.raises(DeliveryReached):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert len(backend.design_inputs) == 2
    feedback = str(backend.design_inputs[1]["next_action"])
    assert "interface consumers must be unique" in feedback
    assert "interface index: 1" in feedback
    assert digest(invalid) in feedback
    assert "private-interface-text" not in feedback
    accepted = service.status(seed.delivery_id).checkpoint
    assert accepted.stage is JointStage.DELIVERING
    assert accepted.approval == seed.approval
    assert accepted.attempts == {"design": 2, "plan": 1}
    assert accepted.design != invalid
    assert not accepted.children


def test_designer_budget_is_durable_and_never_dispatches_invalid_output(tmp_path: Path) -> None:
    service, backend, seed, invalid = setup_design(tmp_path)
    backend.designs = [invalid] * 3
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    with pytest.raises(ValueError, match="design attempt budget exhausted"):
        service.resume(command)
    rejected = service.status(seed.delivery_id).checkpoint
    assert rejected.attempts == {"design": 3}
    assert rejected.design is None and rejected.plan is None and not rejected.children
    assert digest(invalid) in rejected.next_action
    reopened = JointDeliveryService(backend=backend, team=service.team, project=service.project)
    with pytest.raises(ValueError, match="design attempt budget exhausted"):
        reopened.resume(command)
    assert len(backend.design_inputs) == 3
    assert reopened.status(seed.delivery_id).checkpoint == rejected


def test_interruption_preserves_feedback_and_spent_attempts(tmp_path: Path) -> None:
    service, backend, seed, invalid = setup_design(tmp_path)
    valid = backend.designs[1]
    backend.designs = [invalid, RuntimeError("provider interrupted")]
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    with pytest.raises(RuntimeError, match="provider interrupted"):
        service.resume(command)
    paused = service.status(seed.delivery_id).checkpoint
    assert paused.attempts == {"design": 2}
    assert paused.design is None and digest(invalid) in paused.next_action
    backend.designs = [valid]
    reopened = JointDeliveryService(backend=backend, team=service.team, project=service.project)
    with pytest.raises(DeliveryReached):
        reopened.resume(command)
    assert backend.design_inputs[-1]["next_action"] == paused.next_action
    assert reopened.status(seed.delivery_id).checkpoint.attempts["design"] == 3


def test_unrelated_design_violation_does_not_auto_retry(tmp_path: Path) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    valid = backend.designs[1]
    assert isinstance(valid, JointTechnicalDesign)
    backend.designs = [valid.model_copy(update={"product_spec_sha256": "f" * 64})]
    with pytest.raises(ValueError, match="approved ProductSpec"):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    rejected = service.status(seed.delivery_id).checkpoint
    assert rejected.attempts == {"design": 1} and rejected.design is None
    assert len(backend.design_inputs) == 1


def test_valid_first_design_is_not_regenerated(tmp_path: Path) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    backend.designs = backend.designs[1:]
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    with pytest.raises(DeliveryReached):
        service.resume(command)
    reopened = JointDeliveryService(backend=backend, team=service.team, project=service.project)
    with pytest.raises(DeliveryReached):
        reopened.resume(command)
    assert len(backend.design_inputs) == 1
    assert len(backend.inputs) == 1


def test_foreign_duplicate_consumers_are_not_reclassified(tmp_path: Path) -> None:
    service, backend, seed, invalid = setup_design(tmp_path)
    interface = invalid.interfaces[0].model_copy(
        update={"consumers": ("unit_ffffffffffffffff",) * 2}
    )
    backend.designs = [invalid.model_copy(update={"interfaces": (interface,)})]
    with pytest.raises(ValueError, match="outside this request"):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert len(backend.design_inputs) == 1
    rejected = service.status(seed.delivery_id).checkpoint
    assert rejected.design is None and rejected.attempts == {"design": 1}


@pytest.mark.parametrize("path", ["./src/config.py", "src/", ".", "/private/secret", "../secret"])
@pytest.mark.parametrize("exhaust", [False, True])
def test_invalid_write_path_feedback_is_safe_and_bounded(
    tmp_path: Path, path: str, exhaust: bool
) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    valid = backend.designs[1]
    assert isinstance(valid, JointTechnicalDesign)
    unit = valid.units[0]
    component = unit.design.components[0].model_copy(update={"affected_paths": (path,)})
    invalid = valid.model_copy(
        update={
            "units": (
                unit.model_copy(
                    update={
                        "design": unit.design.model_copy(
                            update={
                                "components": (component, *unit.design.components[1:]),
                            }
                        )
                    }
                ),
                *valid.units[1:],
            )
        }
    )
    backend.designs = [invalid] * 3 if exhaust else [invalid, valid]
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    if exhaust:
        with pytest.raises(ValueError, match="design attempt budget exhausted"):
            service.resume(command)
        final = service.status(seed.delivery_id).checkpoint
        assert final.design is None and final.plan is None and not final.children
        reopened = JointDeliveryService(backend=backend, team=service.team, project=service.project)
        with pytest.raises(ValueError, match="design attempt budget exhausted"):
            reopened.resume(command)
        assert len(backend.design_inputs) == 3
    else:
        with pytest.raises(DeliveryReached):
            service.resume(command)
        final = service.status(seed.delivery_id).checkpoint
        assert final.design == valid and final.approval == seed.approval
    feedback = str(backend.design_inputs[1]["next_action"])
    assert "design write paths exceed the selected directories" in feedback
    assert "unit index: 1; component index: 1; path index: 1" in feedback
    assert digest(invalid) in feedback
    assert "secret" not in feedback
