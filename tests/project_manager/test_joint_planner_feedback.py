"""A rejected plan must give the next bounded attempt actionable, durable coverage facts."""

from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn

import pytest

from ai_software_engineer.agents import StructuredModelClient, StructuredModelResult
from ai_software_engineer.company_workspace import CompanyWorkspace
from ai_software_engineer.multi_directory.models import (
    JointCheckpoint,
    JointExecutionPlan,
    JointStage,
    digest,
)
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.project_manager.delivery import ResumeProjectDelivery
from tests.project_manager.test_joint_contracts import checkpoint


class DeliveryReached(Exception):
    """Stop the fixture at the delivery boundary without producing any verdict."""


class PlanningBackend:
    def __init__(self, plan: JointExecutionPlan) -> None:
        self.plan = plan
        self.inputs: list[Mapping[str, object]] = []

    def client(self, scope: DirectoryScope) -> StructuredModelClient:
        return self

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
    ) -> StructuredModelResult:
        self.inputs.append(input_payload)
        return StructuredModelResult(payload=self.plan.to_wire(), duration_ms=0)

    def reconcile(self, checkpoint: JointCheckpoint) -> None:
        pass

    def validate_plan(self, checkpoint: JointCheckpoint, plan: JointExecutionPlan) -> None:
        pass

    def prepare(self, unit: DirectoryUnit) -> NoReturn:
        raise AssertionError("already prepared")

    def deliver(self, checkpoint: JointCheckpoint, unit_id: str) -> NoReturn:
        raise DeliveryReached

    def integrate(self, checkpoint: JointCheckpoint) -> NoReturn:
        raise AssertionError("no delivery verdict exists")


@pytest.mark.parametrize("missing", ["acceptance", "write_unit"])
@pytest.mark.parametrize("exhaust", [False, True])
def test_rejected_coverage_survives_restart_and_reaches_next_attempt(
    tmp_path: Path, missing: str, exhaust: bool
) -> None:
    cp = checkpoint(tmp_path)
    assert cp.product_spec and cp.design and cp.plan and cp.approval
    # Two acceptance criteria expose omission without an invalid empty list at the schema seam.
    requirement = cp.product_spec.product.requirements[0]
    product = cp.product_spec.model_copy(
        update={
            "product": cp.product_spec.product.model_copy(
                update={
                    "requirements": (
                        requirement.model_copy(
                            update={
                                "acceptance": (*requirement.acceptance, requirement.acceptance[0])
                            }
                        ),
                    )
                }
            )
        }
    )
    design = cp.design.model_copy(
        update={
            "product_spec_sha256": digest(product),
            "units": tuple(
                unit.model_copy(
                    update={
                        "design": unit.design.model_copy(
                            update={
                                "acceptance_mappings": (
                                    *unit.design.acceptance_mappings,
                                    unit.design.acceptance_mappings[0].model_copy(
                                        update={"acceptance_criterion_id": "ac_001_002"}
                                    ),
                                )
                            }
                        )
                    }
                )
                for unit in cp.design.units
            ),
        }
    )
    check = cp.plan.integration_checks[0].model_copy(
        update={"acceptance_ids": ("ac_001_001", "ac_001_002")}
    )
    valid = cp.plan.model_copy(
        update={"design_sha256": digest(design), "integration_checks": (check,)}
    )
    bad_check = check.model_copy(
        update=(
            {"acceptance_ids": ("ac_001_001",)}
            if missing == "acceptance"
            else {"consumes": (check.unit_id,)}
        )
    )
    invalid = valid.model_copy(update={"integration_checks": (bad_check,)})
    company = CompanyWorkspace.initialize(
        tmp_path / "platform", company_id="company_test", name="Test"
    )
    backend = PlanningBackend(invalid)
    service = JointDeliveryService(backend=backend, company=company)
    seed = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "company_manifest_sha256": company.manifest.manifest_sha256,
            "stage": JointStage.PLANNING,
            "product_spec": product,
            "design": design,
            "approval": cp.approval.model_copy(update={"product_spec_sha256": digest(product)}),
            "plan": None,
            "next_action": "Plan the approved design.",
        }
    )
    service.journal.append(seed, expected=None)
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    with pytest.raises(ValueError, match="integration checks must cover"):
        service.resume(command)
    rejected = service.status(seed.delivery_id).checkpoint
    expected_missing = "ac_001_002" if missing == "acceptance" else cp.scope.units[0].id
    assert expected_missing in rejected.next_action
    assert digest(invalid) in rejected.next_action
    assert rejected.stage is JointStage.PLANNING and rejected.plan is None
    assert rejected.attempts == {"plan": 1}
    assert rejected.approval == seed.approval
    assert backend.inputs[0]["required_coverage"] == {
        "acceptance_ids": ["ac_001_001", "ac_001_002"],
        "write_unit_ids": [u.unit_id for u in design.units],
        "interface_ids": [i.id for i in design.interfaces],
    }
    restarted = JointDeliveryService(backend=backend, company=company)
    if exhaust:
        for _ in range(2):
            with pytest.raises(ValueError, match="integration checks must cover"):
                restarted.resume(command)
        with pytest.raises(ValueError, match="plan attempt budget exhausted"):
            restarted.resume(command)
        assert len(backend.inputs) == 3
        final = restarted.status(seed.delivery_id).checkpoint
        assert final.attempts == {"plan": 3} and final.plan is None
        assert final.stage is JointStage.PLANNING and not final.children
        return
    backend.plan = valid
    with pytest.raises(DeliveryReached):
        restarted.resume(command)
    assert backend.inputs[1]["next_action"] == rejected.next_action
    accepted = restarted.status(seed.delivery_id).checkpoint
    assert accepted.stage is JointStage.DELIVERING and accepted.plan == valid
    assert accepted.attempts == {"plan": 2}
    assert not accepted.children and accepted.integration is None
