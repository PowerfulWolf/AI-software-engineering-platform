"""Exact design test levels and bounded, durable Planner correction."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    StructuredModelError,
    StructuredModelResult,
)
from ai_software_engineer.domain.project_delivery import PlanTestMatrixError
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.multi_directory.models import (
    JointCheckpoint,
    JointExecutionPlan,
    JointPlanFeedback,
    JointStage,
    digest,
)
from ai_software_engineer.multi_directory.planning import design_work_graph
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.manager.test_joint_contracts import checkpoint
from tests.manager.test_joint_planner_feedback import DeliveryReached, PlanningBackend
from tests.manager.test_single_repository_acceptance import _single_checkpoint


class SequencePlanner(PlanningBackend):
    def __init__(self, responses: tuple[JointExecutionPlan | Exception, ...]) -> None:
        self.responses = responses
        first = responses[0]
        assert isinstance(first, JointExecutionPlan)
        super().__init__(first)
        self.schemas: list[Mapping[str, object]] = []
        self.prompts: list[str] = []

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        response = self.responses[len(self.inputs)]
        self.inputs.append(input_payload)
        self.schemas.append(output_schema)
        self.prompts.append(instructions)
        if isinstance(response, Exception):
            raise response
        return StructuredModelResult(payload=response.to_wire(), duration_ms=0)


def setup_matrix(
    tmp_path: Path, *, limit: int = 3, simple: bool = False
) -> tuple[JointDeliveryService, SequencePlanner, JointCheckpoint, JointExecutionPlan]:
    cp = _single_checkpoint(tmp_path) if simple else checkpoint(tmp_path)
    assert cp.design and cp.plan
    design = cp.design.model_copy(
        update={
            "units": tuple(
                unit.model_copy(
                    update={
                        "design": unit.design.model_copy(
                            update={
                                "acceptance_mappings": tuple(
                                    mapping.model_copy(
                                        update={
                                            "test_levels": ("manual_ui", "accessibility"),
                                        }
                                    )
                                    for mapping in unit.design.acceptance_mappings
                                ),
                            }
                        ),
                    }
                )
                for unit in cp.design.units
            ),
        }
    )
    valid = cp.plan.model_copy(
        update={
            "design_sha256": digest(design),
            "units": tuple(
                unit.model_copy(
                    update={
                        "plan": unit.plan.model_copy(
                            update={
                                "work_graph": design_work_graph(
                                    next(
                                        item.design
                                        for item in design.units
                                        if item.unit_id == unit.unit_id
                                    ),
                                    package_id=unit.unit_id,
                                ),
                            }
                        ),
                    }
                )
                for unit in cp.plan.units
            ),
        }
    )
    unit = valid.units[0]
    graph = unit.plan.work_graph
    assert graph
    package = graph.packages[0]
    invalid = valid.model_copy(
        update={
            "units": (
                unit.model_copy(
                    update={
                        "plan": unit.plan.model_copy(
                            update={
                                "work_graph": graph.model_copy(
                                    update={
                                        "packages": (
                                            package.model_copy(
                                                update={
                                                    "tests": (
                                                        package.tests[0].model_copy(
                                                            update={
                                                                "level": "manual_ui_accessibility"
                                                            }
                                                        ),
                                                    )
                                                }
                                            ),
                                        )
                                    }
                                ),
                            }
                        )
                    }
                ),
                *valid.units[1:],
            )
        }
    )
    backend = SequencePlanner((invalid, valid))
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    service = JointDeliveryService(
        backend=backend,
        team=team,
        project=project,
        execution_retry_policy=ExecutionRetryPolicy(planner=StageRetryPolicy(max_attempts=limit)),
    )
    seed = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "stage": JointStage.PLANNING,
            "children": (),
            "integration": None,
            "attempts": {},
            "plan": None,
            "design": design,
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_manifest_sha256": project.manifest.manifest_sha256,
        }
    )
    service.journal.append(seed, expected=None)
    return service, backend, seed, valid


def test_combined_level_is_corrected_in_one_resume_with_exact_requirements(tmp_path: Path) -> None:
    service, backend, seed, _ = setup_matrix(tmp_path)
    with pytest.raises(DeliveryReached):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    final = service.status(seed.delivery_id).checkpoint
    assert final.stage is JointStage.DELIVERING and final.plan
    assert final.attempts == {"plan": 2} and final.approval == seed.approval
    assert final.design == seed.design and not final.children
    feedback = final.planning_feedback
    assert feedback and feedback.test_matrix_issues
    issue = feedback.test_matrix_issues[0]
    assert issue.unit_id == seed.scope.units[0].id
    assert issue.acceptance_criterion_id == "ac_001_001"
    assert set(issue.missing_levels) == {"manual_ui", "accessibility"}
    assert issue.observed_levels == ("manual_ui_accessibility",)
    assert feedback.reason_codes == ("PLAN_TEST_MATRIX_MISSING_LEVELS",)
    assert final.plan.previous_plan_sha256 == digest(feedback.previous_plan)
    assert final.plan.feedback_sha256 == digest(feedback)
    assert backend.inputs[1]["planning_feedback"] == feedback.to_wire()
    matrix = backend.inputs[0]["required_test_matrix"]
    assert matrix == [
        {
            "unit_id": unit.id,
            "acceptance_criterion_id": "ac_001_001",
            "test_levels": ["manual_ui", "accessibility"],
        }
        for unit in seed.scope.units
    ]
    defs = backend.schemas[0]["$defs"]
    assert isinstance(defs, dict)
    assert defs["PlanTestItem"]["properties"]["level"]["enum"] == ["accessibility", "manual_ui"]
    assert "separate" in backend.prompts[0] and "required_test_matrix" in backend.prompts[0]
    # The live schema restriction must not mutate the persisted contract or legacy reads.
    assert (
        "enum"
        not in JointExecutionPlan.model_json_schema()["$defs"]["PlanTestItem"]["properties"][
            "level"
        ]
    )


def test_repeated_matrix_failure_stops_at_budget_then_resumes_after_increase(
    tmp_path: Path,
) -> None:
    service, backend, seed, valid = setup_matrix(tmp_path, limit=2)
    backend.responses = (backend.plan, backend.plan, valid)
    command = ResumeProjectDelivery(delivery_id=seed.delivery_id)
    with pytest.raises(PlanTestMatrixError, match="missing test levels"):
        service.resume(command)
    rejected = service.status(seed.delivery_id).checkpoint
    assert rejected.stage is JointStage.PLANNING and rejected.plan is None
    assert rejected.attempts == {"plan": 2} and len(backend.inputs) == 2
    before = service.journal.history(seed.delivery_id)
    restarted = JointDeliveryService(
        backend=backend,
        team=service.team,
        project=service.project,
        execution_retry_policy=service.execution_retry_policy,
    )
    with pytest.raises(ValueError, match="plan attempt budget exhausted"):
        restarted.resume(command)
    assert restarted.journal.history(seed.delivery_id) == before
    assert len(backend.inputs) == 2
    increased = JointDeliveryService(backend=backend, team=service.team, project=service.project)
    with pytest.raises(DeliveryReached):
        increased.resume(command)
    assert increased.status(seed.delivery_id).checkpoint.attempts == {"plan": 3}
    assert increased.journal.history(seed.delivery_id)[: len(before)] == before


@pytest.mark.parametrize("transient", [True, False])
def test_provider_failure_after_rejection_only_refunds_current_reservation(
    tmp_path: Path, transient: bool
) -> None:
    service, backend, seed, _ = setup_matrix(tmp_path)
    backend.responses = (
        backend.plan,
        StructuredModelError(
            AgentErrorCode.PROVIDER_UNAVAILABLE,
            "fixture outage",
            transient=transient,
        ),
    )
    with pytest.raises(StructuredModelError):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    failed = service.status(seed.delivery_id).checkpoint
    assert failed.attempts == ({"plan": 1, "plan_transient": 1} if transient else {"plan": 2})
    assert failed.planning_feedback and failed.plan is None and not failed.children
    assert failed.approval == seed.approval


def test_unknown_failure_is_not_automatically_retried(tmp_path: Path) -> None:
    service, backend, seed, _ = setup_matrix(tmp_path)
    backend.responses = (backend.plan, RuntimeError("fixture interruption"))
    with pytest.raises(RuntimeError, match="fixture interruption"):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert service.status(seed.delivery_id).checkpoint.attempts == {"plan": 2}
    assert len(backend.inputs) == 2


def test_legacy_feedback_roundtrip_omits_extension(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.plan
    legacy = {
        "previous_plan": cp.plan.to_wire(),
        "reason_codes": ["ValueError"],
        "required_changes": ["Correct the previous rejection"],
    }
    assert JointPlanFeedback.model_validate(legacy).to_wire() == legacy


@pytest.mark.parametrize("wait_at", ["break-loop", "next_gate", "producer"])
def test_knowledge_wait_only_refunds_an_unfinished_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wait_at: str
) -> None:
    from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised

    service, backend, seed, _ = setup_matrix(tmp_path)

    class Gap:
        gap_id = "a" * 64

    gap = KnowledgeGapRaised(Gap())  # type: ignore[arg-type]
    if wait_at == "producer":
        backend.responses = (backend.plan, gap)
    else:
        calls = []

        class Gate:
            def require(self, name: str, *_args: object, **_kwargs: object) -> None:
                calls.append(name)
                if (wait_at == "break-loop" and name == "break-loop") or (
                    wait_at == "next_gate" and calls.count("planning-gate") == 2
                ):
                    raise gap

        monkeypatch.setattr(service, "_stage_workflow", lambda _: Gate())
    final = service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id)).checkpoint
    assert final.stage is JointStage.WAITING_HUMAN
    assert final.knowledge_wait_stage is JointStage.PLANNING
    assert final.attempts == {"plan": 1}, "the rejected output consumed real work"
    assert final.planning_feedback and final.plan is None and final.approval == seed.approval


def test_simple_generation_error_never_loops_without_spending_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.multi_directory import service as service_module

    service, backend, seed, _ = setup_matrix(tmp_path, simple=True)
    calls = []

    def invalid_fast_plan(checkpoint: JointCheckpoint) -> JointExecutionPlan:
        calls.append(checkpoint)
        return backend.plan

    monkeypatch.setattr(service_module, "fast_joint_plan", invalid_fast_plan)
    with pytest.raises(PlanTestMatrixError):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert len(calls) == 1 and not backend.inputs
    final = service.status(seed.delivery_id).checkpoint
    assert not final.attempts and final.plan is None


def test_schema_invalid_output_does_not_enter_matrix_correction_loop(
    tmp_path: Path,
) -> None:
    service, backend, seed, _ = setup_matrix(tmp_path)
    # model_copy deliberately bypasses validation to simulate a malformed provider reply.
    backend.responses = (backend.plan.model_copy(update={"units": ()}),)
    with pytest.raises(StructuredModelError) as raised:
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert raised.value.code is AgentErrorCode.INVALID_OUTPUT
    final = service.status(seed.delivery_id).checkpoint
    assert final.attempts == {"plan": 1} and final.planning_feedback is None
    assert len(backend.inputs) == 1
