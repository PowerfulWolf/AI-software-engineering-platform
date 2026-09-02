"""Read-only Project Manager stage advancement tests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain import (
    ProductApprovalDecision,
    ProductApprovalRequired,
    ProductSpecApproval,
    StageIntegrityError,
)
from ai_software_engineer.project_manager.stages import (
    ProjectStage,
    ProjectStageAdvancer,
    ProjectStageNotReady,
    StageAdvanceAuthorization,
    StageAdvanceRequest,
)
from tests.project_manager.test_contracts import NOW, stage_chain


def test_product_context_requires_exact_preparation(tmp_path: Path) -> None:
    preparation, *_ = stage_chain(tmp_path)
    authorization = ProjectStageAdvancer().advance_stage(
        StageAdvanceRequest(
            target=ProjectStage.PRODUCT_DISCOVERY,
            preparation=preparation,
        ),
        authorized_at=NOW,
    )

    authorization.validate_integrity()
    assert authorization.project_id == preparation.project_id
    assert authorization.input_sha256s == (preparation.preparation_sha256,)

    with pytest.raises(ValidationError, match="exact prerequisite prefix"):
        StageAdvanceRequest(target=ProjectStage.PRODUCT_DISCOVERY)


def test_design_and_planning_require_validated_prefix(tmp_path: Path) -> None:
    preparation, request, spec, approval, design, _ = stage_chain(tmp_path)
    advancer = ProjectStageAdvancer()

    design_authorization = advancer.advance_stage(
        StageAdvanceRequest(
            target=ProjectStage.SOLUTION_DESIGN,
            preparation=preparation,
            project_request=request,
            product_spec=spec,
            product_approval=approval,
        ),
        authorized_at=NOW,
    )
    planning_authorization = advancer.advance_stage(
        StageAdvanceRequest(
            target=ProjectStage.PLANNING,
            preparation=preparation,
            project_request=request,
            product_spec=spec,
            product_approval=approval,
            technical_design=design,
        ),
        authorized_at=NOW,
    )

    assert len(design_authorization.input_sha256s) == 4
    assert len(planning_authorization.input_sha256s) == 5


def test_stage_advancer_rejects_changed_lineage(tmp_path: Path) -> None:
    preparation, request, spec, approval, *_ = stage_chain(tmp_path)
    changed_request = request.model_copy(update={"preparation_sha256": "f" * 64})

    with pytest.raises(StageIntegrityError):
        ProjectStageAdvancer().advance_stage(
            StageAdvanceRequest(
                target=ProjectStage.SOLUTION_DESIGN,
                preparation=preparation,
                project_request=changed_request,
                product_spec=spec,
                product_approval=approval,
            ),
            authorized_at=NOW,
        )


def test_stage_advancer_cannot_treat_request_changes_as_approval(tmp_path: Path) -> None:
    preparation, request, spec, _, *_ = stage_chain(tmp_path)
    rejected = ProductSpecApproval.create(
        spec,
        decision=ProductApprovalDecision.REQUEST_CHANGES,
        operator_id="user_owner_001",
        rationale="Clarify one acceptance criterion.",
        decided_at=NOW,
    )

    with pytest.raises(ProductApprovalRequired, match="requested changes"):
        ProjectStageAdvancer().advance_stage(
            StageAdvanceRequest(
                target=ProjectStage.SOLUTION_DESIGN,
                preparation=preparation,
                project_request=request,
                product_spec=spec,
                product_approval=rejected,
            ),
            authorized_at=NOW,
        )


def test_dispatch_requires_ready_request_and_complete_exact_chain(tmp_path: Path) -> None:
    preparation, request, spec, approval, design, plan = stage_chain(tmp_path)
    authorization = ProjectStageAdvancer().advance_stage(
        StageAdvanceRequest(
            target=ProjectStage.DELIVERY_DISPATCH,
            preparation=preparation,
            project_request=request,
            product_spec=spec,
            product_approval=approval,
            technical_design=design,
            execution_plan=plan,
        ),
        authorized_at=datetime(2026, 9, 2, 9, 30, tzinfo=UTC),
    )

    assert len(authorization.input_sha256s) == 6
    authorization.validate_integrity()


def test_stage_request_rejects_extra_future_artifacts(tmp_path: Path) -> None:
    preparation, request, spec, approval, *_ = stage_chain(tmp_path)

    with pytest.raises(ValidationError, match="exact prerequisite prefix"):
        StageAdvanceRequest(
            target=ProjectStage.PRODUCT_DISCOVERY,
            preparation=preparation,
            project_request=request,
            product_spec=spec,
            product_approval=approval,
        )


def test_stage_advancer_requires_aware_clock(tmp_path: Path) -> None:
    preparation, *_ = stage_chain(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        ProjectStageAdvancer().advance_stage(
            StageAdvanceRequest(
                target=ProjectStage.PRODUCT_DISCOVERY,
                preparation=preparation,
            ),
            authorized_at=datetime(2026, 9, 2, 9, 0),
        )


def test_stage_authorization_rejects_digest_count_for_another_target() -> None:
    with pytest.raises(ValidationError, match="digest count"):
        StageAdvanceAuthorization(
            target=ProjectStage.PRODUCT_DISCOVERY,
            project_id="project_delivery_001",
            input_sha256s=("a" * 64, "b" * 64),
            authorized_at=NOW,
            authorization_sha256="c" * 64,
        )


def test_stage_advancer_uses_typed_lineage_error_after_valid_integrity(tmp_path: Path) -> None:
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    first = stage_chain(tmp_path / "first")
    second = stage_chain(tmp_path / "second")

    with pytest.raises(ProjectStageNotReady, match="lineage"):
        ProjectStageAdvancer().advance_stage(
            StageAdvanceRequest(
                target=ProjectStage.SOLUTION_DESIGN,
                preparation=first[0],
                project_request=second[1],
                product_spec=second[2],
                product_approval=second[3],
            ),
            authorized_at=NOW,
        )
