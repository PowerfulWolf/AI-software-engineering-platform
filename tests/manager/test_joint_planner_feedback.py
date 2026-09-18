"""A rejected plan must give the next bounded attempt actionable, durable coverage facts."""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import pytest

from ai_software_engineer.agents import StructuredModelClient, StructuredModelResult
from ai_software_engineer.domain import TeamRole
from ai_software_engineer.domain.enums import TaskStatus
from ai_software_engineer.execution import CommandResult
from ai_software_engineer.manager.delivery import DeliveryCheckpointStale, ResumeProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.multi_directory.models import (
    Candidate,
    ChildDelivery,
    IntegrationCommandError,
    IntegrationEvidence,
    JointCheckpoint,
    JointExecutionPlan,
    JointStage,
    digest,
)
from ai_software_engineer.multi_directory.production import ProductionJointBackend
from ai_software_engineer.multi_directory.scope import DirectoryUnit
from ai_software_engineer.multi_directory.service import CloseRequirement, JointDeliveryService
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.manager.test_joint_contracts import checkpoint


class DeliveryReached(Exception):
    """Stop the fixture at the delivery boundary without producing any verdict."""


class PlanningBackend:
    def __init__(self, plan: JointExecutionPlan) -> None:
        self.plan = plan
        self.inputs: list[Mapping[str, object]] = []
        self.command_error = False

    def client(self, checkpoint: JointCheckpoint, role: TeamRole) -> StructuredModelClient:
        del checkpoint, role
        return self

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        del instructions, timeout_seconds, input_images
        self.inputs.append(input_payload)
        return StructuredModelResult(payload=self.plan.to_wire(), duration_ms=0)

    def reconcile(self, checkpoint: JointCheckpoint) -> None:
        pass

    def validate_plan(self, checkpoint: JointCheckpoint, plan: JointExecutionPlan) -> None:
        if self.command_error:
            raise IntegrationCommandError(check_index=1, argv=("ruff", "private-value"))

    def prepare(self, unit: DirectoryUnit) -> NoReturn:
        raise AssertionError("already prepared")

    def deliver(self, checkpoint: JointCheckpoint, unit_id: str) -> NoReturn:
        raise DeliveryReached

    def integrate(self, checkpoint: JointCheckpoint) -> IntegrationEvidence:
        raise AssertionError("no delivery verdict exists")


def _done_child(checkpoint: JointCheckpoint, index: int) -> ChildDelivery:
    unit = checkpoint.scope.units[index]
    prepared = next(item for item in checkpoint.preparations if item.unit_id == unit.id).result
    assert prepared.preparation is not None
    native = ProjectDeliveryCheckpoint.create(
        delivery_id=f"delivery_child_{index}",
        sequence=1,
        repository_id=prepared.repository_id,
        repository_root=unit.root,
        preparation_sha256=prepared.preparation.preparation_sha256,
        request_id=f"request_child_{index}",
        request_revision=1,
        product_checkpoint_sha256="1" * 64,
        product_spec_id=f"product_spec_child_{index}",
        product_spec_sha256="2" * 64,
        approval_id="product_approval_" + "3" * 64,
        approval_sha256="4" * 64,
        technical_design_id=f"technical_design_child_{index}",
        technical_design_sha256="5" * 64,
        execution_plan_id=f"execution_plan_child_{index}",
        execution_plan_sha256="6" * 64,
        planning_preview_id=f"planning_preview_child_{index}",
        planning_preview_sha256="7" * 64,
        dispatch_commit_id=f"dispatch_commit_child_{index}",
        dispatch_commit_sha256="8" * 64,
        task_id=f"task_child_{index}",
        task_revision=1,
        task_status=TaskStatus.DONE,
        candidate_revision=chr(ord("a") + index) * 40,
        stage=DeliveryStage.DONE,
        stage_attempts=DeliveryStageAttempts(),
        next_action=DeliveryNextAction.NONE,
        checkpointed_at=datetime.now(UTC),
    )
    return ChildDelivery(unit_id=unit.id, checkpoint=native)


class IntegrationRecoveryBackend(PlanningBackend):
    def __init__(self, plan: JointExecutionPlan, candidates: tuple[Candidate, ...]) -> None:
        super().__init__(plan)
        self.candidates = candidates
        self.deliver_calls: list[str] = []
        self.integrate_calls = 0

    def deliver(self, checkpoint: JointCheckpoint, unit_id: str) -> NoReturn:
        del checkpoint
        self.deliver_calls.append(unit_id)
        raise AssertionError("a completed child must not be delivered again")

    def integrate(self, checkpoint: JointCheckpoint) -> IntegrationEvidence:
        assert checkpoint.plan is not None
        self.integrate_calls += 1
        return IntegrationEvidence(
            plan_sha256=digest(checkpoint.plan),
            candidates=self.candidates,
            checks=tuple(
                CommandResult(
                    argv=check.argv,
                    cwd=check.unit_id,
                    returncode=0,
                    stdout="Ran 1 test in 0.001s\nOK",
                    stderr="",
                    duration_ms=1,
                )
                for check in checkpoint.plan.integration_checks
            ),
        )


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
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    backend = PlanningBackend(invalid)
    service = JointDeliveryService(backend=backend, team=team, project=project)
    seed = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_manifest_sha256": project.manifest.manifest_sha256,
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
    policy = backend.inputs[0]["integration_command_policy"]
    assert isinstance(policy, dict)
    assert ["uv", "run", "pytest"] in policy["test_prefixes"]
    assert ["ruff"] not in policy["test_prefixes"]
    assert "--collect-only" in policy["forbidden_options"]
    restarted = JointDeliveryService(backend=backend, team=team, project=project)
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


def test_command_rejection_is_safe_and_durable(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.plan is not None
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    backend = PlanningBackend(cp.plan)
    backend.command_error = True
    service = JointDeliveryService(backend=backend, team=team, project=project)
    seed = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "stage": JointStage.PLANNING,
            "plan": None,
        }
    )
    service.journal.append(seed, expected=None)
    with pytest.raises(IntegrationCommandError, match="supported test command"):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    rejected = service.status(seed.delivery_id).checkpoint
    assert "private-value" not in rejected.next_action
    assert "check index: 1" in rejected.next_action
    assert "argv sha256:" in rejected.next_action
    assert digest(cp.plan) in rejected.next_action
    assert rejected.plan is None and rejected.attempts == {"plan": 1}
    backend.command_error = False
    reopened = JointDeliveryService(backend=backend, team=team, project=project)
    with pytest.raises(DeliveryReached):
        reopened.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert backend.inputs[-1]["next_action"] == rejected.next_action


@pytest.mark.parametrize("exhausted", [False, True])
@pytest.mark.parametrize("replanning", [False, True])
@pytest.mark.parametrize("retry_fails", [False, True])
def test_failed_integration_replans_without_redelivering_done_children(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exhausted: bool,
    replanning: bool,
    retry_fails: bool,
) -> None:
    cp = checkpoint(tmp_path)
    assert cp.plan is not None
    children = tuple(_done_child(cp, index) for index in range(len(cp.scope.units)))
    candidates = tuple(
        Candidate(unit_id=child.unit_id, revision=child.checkpoint.candidate_revision or "missing")
        for child in children
    )
    failed = IntegrationEvidence(
        plan_sha256=digest(cp.plan),
        candidates=candidates,
        checks=(
            CommandResult(
                argv=cp.plan.integration_checks[0].argv,
                cwd=str(tmp_path),
                returncode=127,
                stdout="",
                stderr="command could not start",
                duration_ms=0,
            ),
        ),
    )
    fresh_plan = cp.plan.model_copy(
        update={
            "integration_checks": (
                cp.plan.integration_checks[0].model_copy(update={"id": "fresh_check"}),
            )
        }
    )
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    backend = IntegrationRecoveryBackend(fresh_plan, candidates)
    service = JointDeliveryService(backend=backend, team=team, project=project)
    seed = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "stage": JointStage.PLANNING if replanning else JointStage.BLOCKED,
            "plan": None if replanning else cp.plan,
            "children": children,
            "integration": failed,
            "attempts": {"plan": 1, "integration": 3 if exhausted else 1},
            "next_action": "Joint integration failed; inspect evidence.",
        }
    )
    service.journal.append(seed, expected=None)

    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    if exhausted:
        proposal_result = service.resume(command)
        proposal = proposal_result.integration_retry_proposal
        assert proposal is not None
        assert proposal_result.checkpoint == seed
        assert service.journal.current(seed.delivery_id) == seed
        assert not backend.inputs and backend.integrate_calls == 0
        assert service.resume(command).integration_retry_proposal == proposal
        with pytest.raises(DeliveryCheckpointStale, match="integration retry approval changed"):
            service.resume(
                command.model_copy(
                    update={"approved_plan_sha256": "f" * 64, "approval_reference": "stale"}
                )
            )
        command = command.model_copy(
            update={
                "approved_plan_sha256": digest(proposal),
                "approval_reference": "human-approved-one-integration-retry",
            }
        )
    if retry_fails:

        def integrate(checkpoint: JointCheckpoint) -> IntegrationEvidence:
            backend.integrate_calls += 1
            assert checkpoint.plan is not None
            return failed.model_copy(update={"plan_sha256": digest(checkpoint.plan)})

        monkeypatch.setattr(backend, "integrate", integrate)
    result = service.resume(command).checkpoint

    assert result.stage is (JointStage.BLOCKED if retry_fails else JointStage.DONE)
    assert result.plan == fresh_plan
    assert result.children == children
    assert result.integration is not None and result.integration.plan_sha256 == digest(fresh_plan)
    assert backend.inputs and len(backend.inputs) == 1
    assert backend.deliver_calls == []
    assert backend.integrate_calls == 1
    assert result.attempts["integration"] == (4 if exhausted else 2)
    if exhausted:
        assert result.integration_retry_approval is not None
        assert result.integration_retry_approval.proposal == proposal
        assert result.integration_retry_approval.reference == command.approval_reference
        repeated = service.resume(command)
        assert repeated.integration_retry_proposal is None
        assert backend.integrate_calls == 1
        assert len(backend.inputs) == 1
        if retry_fails:
            assert "已用完" in repeated.checkpoint.next_action
            current = repeated.checkpoint
            for changes in (
                {"integration_retry_approval": None},
                {"attempts": {**current.attempts, "integration": 3}},
            ):
                illegal = JointCheckpoint.seal(
                    {
                        **current.to_wire(),
                        "sequence": current.sequence + 1,
                        "previous_checkpoint_sha256": current.checkpoint_sha256,
                        **changes,
                    }
                )
                with pytest.raises(ValueError, match=r"approval|cannot be reset"):
                    service.journal.append(illegal, expected=current.checkpoint_sha256)
            closed = service.close_requirement(
                CloseRequirement(
                    delivery_id=current.delivery_id,
                    expected_checkpoint_sha256=current.checkpoint_sha256,
                )
            ).checkpoint
            assert service.resume(command).checkpoint == closed
            assert backend.integrate_calls == 1
    history = [
        JointCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(service.journal.directory(seed.delivery_id).glob("*.json"))
    ]
    planning = next(item for item in history if item.stage is JointStage.PLANNING)
    assert planning.plan is None
    assert planning.integration == failed


def test_production_reconcile_accepts_replan_checkpoint_with_retained_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cp = checkpoint(tmp_path)
    child = _done_child(cp, 0)
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    store = FileProjectDeliveryCheckpointStore(
        project.root / "repositories" / child.checkpoint.repository_id / "state/project-deliveries"
    )
    store.put(child.checkpoint)
    replanning = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "stage": JointStage.PLANNING,
            "plan": None,
            "children": (child,),
            "next_action": "Produce a fresh complete integration plan.",
        }
    )

    class Native:
        def prepared_context(self, result: object) -> tuple[object, ...]:
            del result
            return ()

    class Team:
        def validate_code_root(self, root: str) -> None:
            del root

    backend = object.__new__(ProductionJointBackend)
    monkeypatch.setattr(backend, "native", Native(), raising=False)
    monkeypatch.setattr(backend, "team", Team(), raising=False)
    backend.project = project
    monkeypatch.setattr(backend, "_baseline_paths", lambda checkpoint: ())

    ProductionJointBackend.reconcile(backend, replanning)
