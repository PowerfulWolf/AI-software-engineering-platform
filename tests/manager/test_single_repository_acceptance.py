"""A one-repository Requirement reuses native QA/Review instead of joint integration."""

from pathlib import Path

import pytest

from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.execution import CommandResult
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.multi_directory.models import (
    Candidate,
    IntegrationEvidence,
    JointCheckpoint,
    JointStage,
    SingleRepositoryAcceptance,
    digest,
)
from ai_software_engineer.multi_directory.scope import DirectoryScope
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.manager.test_joint_contracts import checkpoint
from tests.manager.test_joint_planner_feedback import _done_child


def _single_checkpoint(tmp_path: Path) -> JointCheckpoint:
    base = checkpoint(tmp_path)
    assert base.product_spec and base.design and base.plan and base.approval
    scope = DirectoryScope(units=base.scope.units[:1])
    product = base.product_spec.model_copy(update={"scope_sha256": digest(scope)})
    design = base.design.model_copy(
        update={
            "product_spec_sha256": digest(product),
            "units": base.design.units[:1],
            "reference_only": (),
            "interfaces": (),
        }
    )
    plan = base.plan.model_copy(
        update={
            "design_sha256": digest(design),
            "units": base.plan.units[:1],
            "integration_checks": (),
        }
    )
    plan.validate_for(scope, product, design)
    child = _done_child(base, 0)
    return JointCheckpoint.seal(
        {
            **base.to_wire(),
            "scope": scope,
            "preparations": base.preparations[:1],
            "product_spec": product,
            "approval": base.approval.model_copy(update={"product_spec_sha256": digest(product)}),
            "design": design,
            "plan": plan,
            "children": (child,),
            "stage": JointStage.BLOCKED,
            "attempts": {"integration": 3},
            "integration": IntegrationEvidence(
                plan_sha256=digest(plan),
                candidates=(
                    Candidate(
                        unit_id=child.unit_id,
                        revision=child.checkpoint.candidate_revision or "",
                    ),
                ),
                checks=(
                    CommandResult(
                        argv=("pytest", "missing.py"),
                        cwd=scope.units[0].root,
                        returncode=1,
                        stdout="",
                        stderr="historical redundant integration failure",
                        duration_ms=1,
                    ),
                ),
            ),
            "next_action": "Historical integration recovery.",
        }
    )


class AcceptanceBackend:
    def __init__(self) -> None:
        self.accept_calls = 0

    def reconcile(self, checkpoint: JointCheckpoint) -> None:
        del checkpoint

    def accept_single_repository(self, checkpoint: JointCheckpoint) -> SingleRepositoryAcceptance:
        self.accept_calls += 1
        assert checkpoint.product_spec is not None
        child = checkpoint.children[0]
        assert child.checkpoint.candidate_revision is not None
        return SingleRepositoryAcceptance(
            unit_id=child.unit_id,
            child_checkpoint_sha256=child.checkpoint.checkpoint_sha256,
            candidate_revision=child.checkpoint.candidate_revision,
            product_spec_sha256=digest(checkpoint.product_spec),
            acceptance_ids=checkpoint.product_spec.acceptance_ids(),
            native_evidence_references=("qa-artifact", "review-artifact"),
        )

    def client(self, checkpoint: JointCheckpoint, role: TeamRole) -> None:
        raise AssertionError((checkpoint, role))

    def prepare(self, unit: object) -> None:
        raise AssertionError(unit)

    def deliver(self, checkpoint: JointCheckpoint, unit_id: str) -> None:
        raise AssertionError((checkpoint, unit_id))

    def integrate(self, checkpoint: JointCheckpoint) -> None:
        raise AssertionError(checkpoint)

    def validate_plan(self, checkpoint: JointCheckpoint, plan: object) -> None:
        raise AssertionError((checkpoint, plan))


def test_single_repository_legacy_recovery_finishes_without_agents(tmp_path: Path) -> None:
    seed = _single_checkpoint(tmp_path)
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    backend = AcceptanceBackend()
    service = JointDeliveryService(backend=backend, team=team, project=project)  # type: ignore[arg-type]
    seed = JointCheckpoint.seal(
        {
            **seed.to_wire(),
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_manifest_sha256": project.manifest.manifest_sha256,
        }
    )
    service.journal.append(seed, expected=None)
    recovering = JointCheckpoint.seal(
        {
            **seed.to_wire(),
            "sequence": 2,
            "previous_checkpoint_sha256": seed.checkpoint_sha256,
            "stage": JointStage.PLANNING,
            "plan": None,
            "next_action": "Recover integration planning.",
        }
    )
    service.journal.append(recovering, expected=seed.checkpoint_sha256)

    result = service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))

    assert result.checkpoint.stage is JointStage.DONE
    assert result.checkpoint.single_repository_acceptance is not None
    assert result.checkpoint.children == seed.children
    assert result.checkpoint.attempts == {"integration": 3}
    assert backend.accept_calls == 1
    assert service.status(seed.delivery_id).checkpoint == result.checkpoint


def test_multi_repository_still_requires_joint_checks(tmp_path: Path) -> None:
    base = checkpoint(tmp_path)
    assert base.plan and base.product_spec and base.design
    with pytest.raises(ValueError, match="multi-repository plan requires"):
        base.plan.model_copy(update={"integration_checks": ()}).validate_for(
            base.scope, base.product_spec, base.design
        )


def test_single_acceptance_rejects_candidate_drift(tmp_path: Path) -> None:
    seed = _single_checkpoint(tmp_path)
    assert seed.product_spec
    child = seed.children[0]
    with pytest.raises(ValueError, match="proof drifted"):
        JointCheckpoint.seal(
            {
                **seed.to_wire(),
                "stage": JointStage.DONE,
                "single_repository_acceptance": SingleRepositoryAcceptance(
                    unit_id=child.unit_id,
                    child_checkpoint_sha256=child.checkpoint.checkpoint_sha256,
                    candidate_revision="f" * 40,
                    product_spec_sha256=digest(seed.product_spec),
                    acceptance_ids=seed.product_spec.acceptance_ids(),
                    native_evidence_references=("qa", "review"),
                ),
            }
        )
