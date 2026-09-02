"""Read-only stage advancement guards for the Project Manager Agent.

The Project Manager may authorize the next role only after validating the exact immutable
lineage accumulated so far. Authorization never edits a stage document, an Artifact, or a
verdict; it produces a digest-bound receipt that downstream composition can verify.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from ai_software_engineer.domain import (
    ExecutionPlan,
    ProductSpec,
    ProductSpecApproval,
    ProjectPreparation,
    ProjectRequest,
    TechnicalDesign,
    require_product_approval,
    validate_stage_chain,
    validate_technical_design,
)
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import DomainModel, ensure_unique

StageSha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class ProjectStage(StrEnum):
    """Role boundary that the Project Manager can authorize."""

    PRODUCT_DISCOVERY = "PRODUCT_DISCOVERY"
    SOLUTION_DESIGN = "SOLUTION_DESIGN"
    PLANNING = "PLANNING"
    DELIVERY_DISPATCH = "DELIVERY_DISPATCH"


class ProjectStageError(RuntimeError):
    """Base error for Project Manager stage authorization."""


class ProjectStageNotReady(ProjectStageError):
    """Raised when the exact prerequisite chain is absent or incoherent."""


class StageAdvanceRequest(DomainModel):
    """Typed stage chain supplied to the read-only advancement guard."""

    kind: Literal["stage_advance_request"] = "stage_advance_request"
    target: ProjectStage
    preparation: ProjectPreparation | None = None
    project_request: ProjectRequest | None = None
    product_spec: ProductSpec | None = None
    product_approval: ProductSpecApproval | None = None
    technical_design: TechnicalDesign | None = None
    execution_plan: ExecutionPlan | None = None

    @model_validator(mode="after")
    def validate_exact_shape(self) -> Self:
        fields = (
            self.preparation,
            self.project_request,
            self.product_spec,
            self.product_approval,
            self.technical_design,
            self.execution_plan,
        )
        required_count = {
            ProjectStage.PRODUCT_DISCOVERY: 1,
            ProjectStage.SOLUTION_DESIGN: 4,
            ProjectStage.PLANNING: 5,
            ProjectStage.DELIVERY_DISPATCH: 6,
        }[self.target]
        if any(value is None for value in fields[:required_count]) or any(
            value is not None for value in fields[required_count:]
        ):
            raise ValueError("stage advance request must contain the exact prerequisite prefix")
        return self


class StageAdvanceAuthorization(DomainModel):
    """Verifiable permission to start exactly one downstream stage."""

    kind: Literal["stage_advance_authorization"] = "stage_advance_authorization"
    schema_version: Literal["v0.1"] = "v0.1"
    target: ProjectStage
    project_id: ProjectId
    input_sha256s: Annotated[tuple[StageSha256, ...], Field(min_length=1)]
    authorized_at: AwareDatetime
    authorization_sha256: StageSha256

    @model_validator(mode="after")
    def validate_inputs(self) -> Self:
        ensure_unique(self.input_sha256s, "StageAdvanceAuthorization input digests")
        expected_count = {
            ProjectStage.PRODUCT_DISCOVERY: 1,
            ProjectStage.SOLUTION_DESIGN: 4,
            ProjectStage.PLANNING: 5,
            ProjectStage.DELIVERY_DISPATCH: 6,
        }[self.target]
        if len(self.input_sha256s) != expected_count:
            raise ValueError("stage authorization digest count does not match target")
        return self

    def validate_integrity(self) -> None:
        """Reject a changed authorization receipt."""
        if self.authorization_sha256 != _authorization_digest(self):
            raise ProjectStageError("stage authorization digest does not match content")


class ProjectStageAdvancer:
    """Validate an immutable prefix and authorize its next role without mutation."""

    def advance_stage(
        self,
        request: StageAdvanceRequest,
        *,
        authorized_at: datetime,
    ) -> StageAdvanceAuthorization:
        """Return a digest-bound authorization for the requested stage."""
        if authorized_at.tzinfo is None or authorized_at.utcoffset() is None:
            raise ValueError("authorized_at must be timezone-aware")
        preparation = _required(request.preparation, "ProjectPreparation")
        preparation.validate_integrity()
        digests: list[str] = [preparation.preparation_sha256]

        if request.target is not ProjectStage.PRODUCT_DISCOVERY:
            project_request = _required(request.project_request, "ProjectRequest")
            product_spec = _required(request.product_spec, "ProductSpec")
            _validate_request_prefix(preparation, project_request, product_spec)
            approval = _required(request.product_approval, "ProductSpecApproval")
            require_product_approval(product_spec, approval)
            digests.extend(
                (
                    project_request.request_sha256,
                    product_spec.product_spec_sha256,
                    approval.approval_sha256,
                )
            )

            if request.target in {
                ProjectStage.PLANNING,
                ProjectStage.DELIVERY_DISPATCH,
            }:
                design = _required(request.technical_design, "TechnicalDesign")
                validate_technical_design(product_spec, approval, design)
                digests.append(design.technical_design_sha256)

                if request.target is ProjectStage.DELIVERY_DISPATCH:
                    plan = _required(request.execution_plan, "ExecutionPlan")
                    validate_stage_chain(
                        preparation,
                        project_request,
                        product_spec,
                        approval,
                        design,
                        plan,
                    )
                    digests.append(plan.execution_plan_sha256)

        provisional = StageAdvanceAuthorization(
            target=request.target,
            project_id=preparation.project_id,
            input_sha256s=tuple(digests),
            authorized_at=authorized_at,
            authorization_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={"authorization_sha256": _authorization_digest(provisional)}
        )


def _validate_request_prefix(
    preparation: ProjectPreparation,
    project_request: ProjectRequest,
    product_spec: ProductSpec,
) -> None:
    project_request.validate_integrity()
    product_spec.validate_integrity()
    if (
        project_request.project_id != preparation.project_id
        or project_request.preparation_sha256 != preparation.preparation_sha256
        or product_spec.project_id != project_request.project_id
        or product_spec.request_id != project_request.id
    ):
        raise ProjectStageNotReady(
            "ProjectPreparation, ProjectRequest, and ProductSpec lineage does not match"
        )


def _required[ModelT](value: ModelT | None, label: str) -> ModelT:
    if value is None:
        raise ProjectStageNotReady(f"{label} is required for stage advancement")
    return value


def _authorization_digest(receipt: StageAdvanceAuthorization) -> str:
    payload = receipt.model_dump(
        mode="json",
        exclude={"authorized_at", "authorization_sha256"},
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ProjectStage",
    "ProjectStageAdvancer",
    "ProjectStageError",
    "ProjectStageNotReady",
    "StageAdvanceAuthorization",
    "StageAdvanceRequest",
]
