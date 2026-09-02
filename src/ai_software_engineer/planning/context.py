"""Task-free context and fail-closed permissions for the Planner Agent."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, model_validator

from ai_software_engineer.design.models import DesignCommitCheckpoint
from ai_software_engineer.domain.enums import ProjectRequestStatus
from ai_software_engineer.domain.identity import ContextId, ProjectId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import (
    ProductSpec,
    ProductSpecApproval,
    ProjectRequest,
    ProjectRequestId,
    StageIntegrityError,
    StageSha256,
    TechnicalDesign,
    require_product_approval,
    validate_technical_design,
)
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.project_manager.stages import ProjectStage, StageAdvanceAuthorization


class PlannerContextError(RuntimeError):
    """Base error for Planner context construction and integrity checks."""


class PlannerContextLineageError(PlannerContextError):
    """Raised when Planner inputs are not one exact approved design chain."""


class PlannerContextIntegrityError(PlannerContextError):
    """Raised when an immutable Planner manifest was changed after creation."""


class PlannerAgentPermissions(DomainModel):
    """Machine-readable least authority granted to Planner model execution."""

    read_stage_artifacts: Literal[True] = True
    produce_execution_plan: Literal[True] = True
    preview_scheduler: Literal[True] = True
    preview_model_router: Literal[True] = True
    write_project_files: Literal[False] = False
    run_commands: Literal[False] = False
    modify_product_or_design: Literal[False] = False
    persist_assignments_or_leases: Literal[False] = False
    persist_model_selection: Literal[False] = False
    advance_project_stage: Literal[False] = False


PLANNER_AGENT_PERMISSIONS = PlannerAgentPermissions()


class PlannerContextManifest(DomainModel):
    """Exact approved design chain sent to one isolated Planner run."""

    kind: Literal["planner_context_manifest"] = "planner_context_manifest"
    schema_version: Literal["v0.1"] = "v0.1"
    context_id: ContextId
    project_id: ProjectId
    request_id: ProjectRequestId
    project_request_revision: ProjectRequestRevision
    product_spec: ProductSpec
    product_approval: ProductSpecApproval
    technical_design: TechnicalDesign
    design_checkpoint: DesignCommitCheckpoint
    planning_authorization: StageAdvanceAuthorization
    expected_execution_plan_version: int
    permissions: PlannerAgentPermissions = PLANNER_AGENT_PERMISSIONS
    built_at: AwareDatetime
    context_sha256: StageSha256

    @model_validator(mode="after")
    def validate_manifest_shape(self) -> Self:
        if self.expected_execution_plan_version < 1:
            raise ValueError("expected_execution_plan_version must be at least one")
        return self

    def validate_integrity(self) -> None:
        try:
            _validate_lineage(
                self.project_request_revision,
                self.product_spec,
                self.product_approval,
                self.technical_design,
                self.design_checkpoint,
                self.planning_authorization,
            )
        except (ValueError, StageIntegrityError) as error:
            raise PlannerContextLineageError(str(error)) from error
        expected = _manifest_digest(self)
        if self.context_sha256 != expected or self.context_id != f"ctx_{expected}":
            raise PlannerContextIntegrityError(
                "PlannerContextManifest identity does not match content"
            )

    @property
    def project_request(self) -> ProjectRequest:
        """Return the request snapshot carried by the exact immutable revision."""
        return self.project_request_revision.request


class PlannerContextBuilder:
    """Build deterministic Planner context without Delivery Task or ambient state."""

    def build(
        self,
        *,
        project_request_revision: ProjectRequestRevision,
        product_spec: ProductSpec,
        product_approval: ProductSpecApproval,
        technical_design: TechnicalDesign,
        design_checkpoint: DesignCommitCheckpoint,
        planning_authorization: StageAdvanceAuthorization,
        expected_execution_plan_version: int,
        built_at: datetime,
    ) -> PlannerContextManifest:
        if built_at.tzinfo is None or built_at.utcoffset() is None:
            raise PlannerContextError("Planner context built_at must be timezone-aware")
        try:
            _validate_lineage(
                project_request_revision,
                product_spec,
                product_approval,
                technical_design,
                design_checkpoint,
                planning_authorization,
            )
        except (ValueError, StageIntegrityError) as error:
            raise PlannerContextLineageError(str(error)) from error
        project_request = project_request_revision.request
        provisional = PlannerContextManifest(
            context_id=f"ctx_{'0' * 64}",
            project_id=project_request.project_id,
            request_id=project_request.id,
            project_request_revision=project_request_revision,
            product_spec=product_spec,
            product_approval=product_approval,
            technical_design=technical_design,
            design_checkpoint=design_checkpoint,
            planning_authorization=planning_authorization,
            expected_execution_plan_version=expected_execution_plan_version,
            permissions=PLANNER_AGENT_PERMISSIONS,
            built_at=built_at,
            context_sha256="0" * 64,
        )
        digest = _manifest_digest(provisional)
        return provisional.model_copy(
            update={"context_id": f"ctx_{digest}", "context_sha256": digest}
        )


def _validate_lineage(
    request_revision: ProjectRequestRevision,
    product_spec: ProductSpec,
    approval: ProductSpecApproval,
    design: TechnicalDesign,
    checkpoint: DesignCommitCheckpoint,
    authorization: StageAdvanceAuthorization,
) -> None:
    request_revision.validate_integrity()
    request = request_revision.request
    request.validate_integrity()
    require_product_approval(product_spec, approval)
    validate_technical_design(product_spec, approval, design)
    if request.status is not ProjectRequestStatus.PLANNING:
        raise PlannerContextLineageError("Planner requires a ProjectRequest in PLANNING")
    if (
        request.id != product_spec.request_id
        or request.project_id != product_spec.project_id
        or request.project_id != design.project_id
    ):
        raise PlannerContextLineageError("Planner stage inputs do not match request/project")
    checkpoint.validate_integrity()
    authorization.validate_integrity()
    if (
        checkpoint.project_id != request.project_id
        or checkpoint.request_id != request.id
        or checkpoint.technical_design_id != design.id
        or checkpoint.technical_design_sha256 != design.technical_design_sha256
        or checkpoint.input_request_revision_sha256 != request_revision.supersedes_sha256
        or checkpoint.request_revision != request_revision.revision
        or checkpoint.request_revision_sha256 != request_revision.request_revision_sha256
        or checkpoint.planning_authorization_sha256 != authorization.authorization_sha256
        or authorization.target is not ProjectStage.PLANNING
        or authorization.project_id != request.project_id
        or authorization.input_sha256s[1:]
        != (
            request.request_sha256,
            product_spec.product_spec_sha256,
            approval.approval_sha256,
            design.technical_design_sha256,
        )
    ):
        raise PlannerContextLineageError(
            "Planner requires an exact committed Designer handoff and PLANNING authorization"
        )


def _manifest_digest(manifest: PlannerContextManifest) -> StageSha256:
    payload = manifest.model_dump(
        mode="json",
        exclude={"context_id", "context_sha256", "built_at"},
        exclude_none=True,
    )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "PLANNER_AGENT_PERMISSIONS",
    "PlannerAgentPermissions",
    "PlannerContextBuilder",
    "PlannerContextError",
    "PlannerContextIntegrityError",
    "PlannerContextLineageError",
    "PlannerContextManifest",
]
