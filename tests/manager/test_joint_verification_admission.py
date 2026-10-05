"""Publication parity must not invalidate already sealed joint history."""

from pathlib import Path
from typing import Literal

import pytest

from ai_software_engineer.domain.execution_window import PlannedVerificationInspection
from ai_software_engineer.domain.project_delivery import AcceptanceDesignMapping
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.production_agents import (
    AcceptanceMappingDraft,
    AcceptanceVerificationRejected,
    native_acceptance_mapping,
)
from ai_software_engineer.multi_directory.admission import (
    JointDesignVerificationRejected,
    require_native_verification_contract,
)
from ai_software_engineer.multi_directory.models import (
    JointCheckpoint,
    JointStage,
    JointTechnicalDesign,
    digest,
)
from tests.manager.test_joint_contracts import checkpoint
from tests.manager.test_joint_designer_feedback import setup_design
from tests.manager.test_joint_planner_feedback import DeliveryReached


def inspected_design(
    original: JointTechnicalDesign, kind: Literal["source", "document"], levels: tuple[str, ...]
) -> JointTechnicalDesign:
    unit = original.units[0]
    mapping = unit.design.acceptance_mappings[0].model_copy(
        update={
            "test_levels": levels,
            "verification_argv": None,
            "verification_inspection": PlannedVerificationInspection(
                kind=kind, paths=("src/safe.py",), checklist=("Inspect approved behavior",)
            ),
        }
    )
    return original.model_copy(
        update={
            "units": (
                unit.model_copy(
                    update={
                        "design": unit.design.model_copy(update={"acceptance_mappings": (mapping,)})
                    }
                ),
                *original.units[1:],
            )
        }
    )


@pytest.mark.parametrize(
    ("kind", "levels", "allowed"),
    [
        ("source", ("source-inspection", "review"), True),
        ("document", ("documentation",), True),
        ("source", ("source-inspection", "integration"), False),
        ("document", ("documentation", "security"), False),
        ("source", ("unit",), False),
    ],
)
def test_publication_matches_native_inspection_contract(
    tmp_path: Path, kind: Literal["source", "document"], levels: tuple[str, ...], allowed: bool
) -> None:
    cp = checkpoint(tmp_path)
    assert cp.design and cp.product_spec
    design = inspected_design(cp.design, kind, levels)
    design.validate_for(cp.scope, cp.product_spec)
    mapping = design.units[0].design.acceptance_mappings[0]
    if allowed:
        AcceptanceDesignMapping.model_validate(mapping.to_wire())
        require_native_verification_contract(design)
    else:
        with pytest.raises(ValueError, match="inspection cannot weaken"):
            AcceptanceDesignMapping.model_validate(mapping.to_wire())
        with pytest.raises(JointDesignVerificationRejected, match=r"ac_001_001.*检查不能替代"):
            require_native_verification_contract(design)
        # Read-time validation and hashing retain historical accepted bytes.
        sealed = JointCheckpoint.seal({**cp.to_wire(), "design": design, "plan": None})
        sealed.validate_integrity()
        assert JointCheckpoint.model_validate(sealed.to_wire()) == sealed


def test_designer_gets_exact_rejection_and_retries_before_planner(tmp_path: Path) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    valid = backend.designs[1]
    assert isinstance(valid, JointTechnicalDesign)
    invalid = inspected_design(valid, "source", ("source-inspection", "integration"))
    mapping = (
        invalid.units[0]
        .design.acceptance_mappings[0]
        .model_copy(
            update={
                "verification_inspection": None,
                "verification_argv": ("pytest", "tests/test_focused.py"),
            }
        )
    )
    valid = invalid.model_copy(
        update={
            "units": (
                invalid.units[0].model_copy(
                    update={
                        "design": invalid.units[0].design.model_copy(
                            update={"acceptance_mappings": (mapping,)}
                        )
                    }
                ),
                *invalid.units[1:],
            )
        }
    )
    backend.designs = [invalid, valid]
    first_plan = backend.plan.units[0]
    graph = first_plan.plan.work_graph
    assert graph is not None
    package = graph.packages[0]
    graph = graph.model_copy(
        update={
            "packages": (
                package.model_copy(
                    update={
                        "tests": (
                            package.tests[0].model_copy(
                                update={"id": "test_inspection", "level": "source-inspection"}
                            ),
                            package.tests[0].model_copy(
                                update={"id": "test_integration", "level": "integration"}
                            ),
                        )
                    }
                ),
            )
        }
    )
    backend.plan = backend.plan.model_copy(
        update={
            "design_sha256": digest(valid),
            "units": (
                first_plan.model_copy(
                    update={"plan": first_plan.plan.model_copy(update={"work_graph": graph})}
                ),
                *backend.plan.units[1:],
            ),
        }
    )
    with pytest.raises(DeliveryReached):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    feedback = backend.design_inputs[1]
    assert "ac_001_001" in str(feedback["next_action"])
    assert "检查不能替代" in str(feedback["next_action"])
    assert feedback["design_feedback"] == invalid.to_wire()
    current = service.journal.current(seed.delivery_id)
    assert current.design == valid and current.approval == seed.approval
    assert current.attempts == {"design": 2, "plan": 1}


def test_correction_cannot_delete_rejected_verification_levels(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.design is not None
    invalid = inspected_design(cp.design, "source", ("source-inspection", "integration"))
    weakened = inspected_design(cp.design, "source", ("source-inspection",))
    with pytest.raises(JointDesignVerificationRejected, match="不得删除原设计"):
        require_native_verification_contract(weakened, invalid)


@pytest.mark.parametrize(
    ("kind", "original_levels", "weak_levels"),
    [
        ("source", ("source_inspection", "integration"), ("source-inspection",)),
        ("document", ("document_inspection", "security"), ("documentation",)),
    ],
)
def test_three_round_correction_cannot_erase_required_levels(
    tmp_path: Path,
    kind: Literal["source", "document"],
    original_levels: tuple[str, ...],
    weak_levels: tuple[str, ...],
) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    valid = backend.designs[1]
    assert isinstance(valid, JointTechnicalDesign)
    invalid = inspected_design(valid, kind, original_levels)
    weakened = inspected_design(valid, kind, weak_levels)
    backend.designs = [invalid, weakened, weakened]
    with pytest.raises(ValueError, match="design attempt budget exhausted"):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    current = service.journal.current(seed.delivery_id)
    assert current is not None and current.design is None and current.plan is None
    assert current.attempts == {"design": 3} and not current.children
    assert "不得删除原设计" in str(backend.design_inputs[-1]["next_action"])
    corrections = backend.design_inputs[-1]["required_verification_corrections"]
    assert corrections[0]["required_test_levels"] == sorted(original_levels)


def test_correction_cannot_erase_rejected_unit_with_reference_only(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.design is not None and cp.product_spec is not None
    original = inspected_design(cp.design, "source", ("source_inspection", "integration"))
    moved = original.model_copy(
        update={
            "units": (original.units[1],),
            "reference_only": (original.units[0].unit_id,),
        }
    )
    moved.validate_for(cp.scope, cp.product_spec)
    with pytest.raises(JointDesignVerificationRejected, match="不得删除原仓库"):
        require_native_verification_contract(moved, original)


def test_knowledge_wait_does_not_erase_original_verification_requirements(tmp_path: Path) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    valid = backend.designs[1]
    assert isinstance(valid, JointTechnicalDesign)
    original = inspected_design(valid, "source", ("source_inspection", "integration"))
    weaker = inspected_design(valid, "source", ("source-inspection",))
    rejected = service._save(seed, design_feedback=original)
    waiting = service._save(rejected, stage=JointStage.WAITING_HUMAN)
    resumed = service._save(waiting, stage=JointStage.DESIGNING, design_feedback=weaker)
    with pytest.raises(JointDesignVerificationRejected, match="不得删除原设计"):
        require_native_verification_contract(
            weaker, resumed.design_feedback, service._design_feedback_history(resumed)
        )


def test_public_knowledge_investigation_cannot_erase_verification_requirements(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.domain.enums import TeamRole
    from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised
    from ai_software_engineer.knowledge.runtime import joint_knowledge_client
    from ai_software_engineer.multi_directory.service import RecheckDesign
    from tests.knowledge.test_consultation import Model

    service, backend, seed, _ = setup_design(tmp_path)
    valid = backend.designs[1]
    assert isinstance(valid, JointTechnicalDesign)
    original = inspected_design(valid, "source", ("source_inspection", "integration"))
    weaker = inspected_design(valid, "source", ("source-inspection",))
    rejected = service._save(seed, design_feedback=original, attempts={"design": 1})
    rejected = service._save(rejected, design_feedback=weaker)
    root = service.journal.directory(seed.delivery_id) / "knowledge"
    client = joint_knowledge_client(Model(), rejected, TeamRole.DESIGNER, root)
    with pytest.raises(KnowledgeGapRaised) as error:
        client.complete(
            instructions="Design",
            input_payload=rejected.to_wire(),
            output_schema={"title": "Output"},
            timeout_seconds=10,
        )
    waiting = service._save(
        rejected,
        stage=JointStage.WAITING_HUMAN,
        knowledge_wait_stage=JointStage.DESIGNING,
        knowledge_gap_id=error.value.gap.gap_id,
    )
    rechecked = service.recheck_design(
        RecheckDesign(
            delivery_id=waiting.delivery_id,
            expected_checkpoint_sha256=waiting.checkpoint_sha256,
            operator_id="test-engineer",
            request_reference="inspect-existing-facts",
        )
    ).checkpoint
    assert rechecked.design_feedback is None and rechecked.knowledge_rechecks
    backend.designs = [weaker, weaker]
    with pytest.raises(ValueError, match="design attempt budget exhausted"):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert "不得删除原设计" in str(backend.design_inputs[-1]["next_action"])


def test_recovery_classification_ignores_untrusted_error_like_text() -> None:
    draft = AcceptanceMappingDraft(
        acceptance_criterion_id="ac_001_001",
        verification_strategy=(
            "inspection cannot weaken the approved verification levels secret=do-not-leak"
        ),
        test_levels=("unit", "unit"),
    )
    with pytest.raises(AcceptanceVerificationRejected) as caught:
        native_acceptance_mapping(draft)
    assert caught.value.code == "INVALID_MAPPING"
    assert "do-not-leak" not in str(caught.value)


@pytest.mark.parametrize(
    ("criterion_id", "visible"),
    [
        ("ac_registered_behavior", "ac_registered_behavior"),
        ("not-an-id password=do-not-leak", "未知验收项"),
    ],
)
def test_exact_non_numeric_acceptance_ids_are_safe_in_feedback(
    criterion_id: str, visible: str
) -> None:
    draft = AcceptanceMappingDraft(
        acceptance_criterion_id=criterion_id,
        verification_strategy="Focused verification",
        test_levels=("unit", "unit"),
    )
    with pytest.raises(AcceptanceVerificationRejected) as caught:
        native_acceptance_mapping(draft)
    assert visible in str(caught.value)
    assert "do-not-leak" not in str(caught.value)


def test_corrected_inspection_alias_preserves_executable_levels(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.design is not None
    original = inspected_design(cp.design, "source", ("source_inspection", "integration"))
    corrected = inspected_design(cp.design, "source", ("source-inspection", "integration"))
    unit = corrected.units[0]
    mapping = unit.design.acceptance_mappings[0].model_copy(
        update={
            "verification_inspection": None,
            "verification_argv": ("pytest", "tests/test_focused.py"),
        }
    )
    corrected = corrected.model_copy(
        update={
            "units": (
                unit.model_copy(
                    update={
                        "design": unit.design.model_copy(update={"acceptance_mappings": (mapping,)})
                    }
                ),
                *corrected.units[1:],
            )
        }
    )
    require_native_verification_contract(corrected, original)
    assert original.units[0].design.acceptance_mappings[0].test_levels[0] == "source_inspection"
