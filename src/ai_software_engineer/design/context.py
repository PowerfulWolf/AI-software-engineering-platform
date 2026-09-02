"""Task-free, digest-bound context routing for the Solution Designer."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from ai_software_engineer.domain import (
    ProductSpec,
    ProductSpecApproval,
    ProjectPreparation,
    ProjectRequest,
    ProjectRequestStatus,
    require_product_approval,
)
from ai_software_engineer.domain.identity import ContextId, ProjectId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.project_delivery import ProjectRequestId, StageSha256
from ai_software_engineer.project_manager.baseline import ProjectSpecBaseline
from ai_software_engineer.project_manager.stages import ProjectStage, StageAdvanceAuthorization
from ai_software_engineer.project_profile import ProjectProfile

type DesignLineage = tuple[
    ProjectPreparation,
    ProjectProfile,
    ProjectSpecBaseline,
    ProjectRequest,
    ProductSpec,
    ProductSpecApproval,
    StageAdvanceAuthorization,
]
type DesignSourceFacts = tuple[
    ProjectPreparation,
    ProjectProfile,
    ProjectSpecBaseline,
    ProjectRequest,
    ProductSpec,
    ProductSpecApproval,
    StageAdvanceAuthorization,
    DesignerAgentPermissions,
]


class DesignContextError(RuntimeError):
    """Base error for Designer context compilation."""


class DesignContextLineageError(DesignContextError):
    """Raised when project and product facts are not one exact chain."""


class DesignContextIntegrityError(DesignContextError):
    """Raised when a built context no longer matches its identity."""


class DesignerAgentPermissions(DomainModel):
    """Fail-closed Designer capabilities; prose cannot widen them."""

    read_project_facts: Literal[True] = True
    read_project_rules: Literal[True] = True
    read_project_request: Literal[True] = True
    read_product_spec: Literal[True] = True
    read_product_approval: Literal[True] = True
    output_technical_design: Literal[True] = True
    write_code: Literal[False] = False
    execute_shell: Literal[False] = False
    modify_product_spec: Literal[False] = False
    modify_product_approval: Literal[False] = False
    advance_project_stage: Literal[False] = False
    create_delivery_task: Literal[False] = False


DESIGNER_AGENT_PERMISSIONS = DesignerAgentPermissions()


class DesignContextSource(DomainModel):
    """One exact source routed into Designer context."""

    uri: NonEmptyStr
    sha256: StageSha256

    @model_validator(mode="after")
    def validate_uri(self) -> Self:
        if any(ord(character) < 32 for character in self.uri):
            raise ValueError("DesignContextSource uri cannot contain control characters")
        return self


class DesignContextManifest(DomainModel):
    """Complete Designer input independent of Delivery Task context."""

    kind: Literal["design_context_manifest"] = "design_context_manifest"
    schema_version: Literal["v0.1"] = "v0.1"
    context_id: ContextId
    project_id: ProjectId
    request_id: ProjectRequestId
    preparation: ProjectPreparation
    project_profile: ProjectProfile
    project_baseline: ProjectSpecBaseline
    project_request: ProjectRequest
    product_spec: ProductSpec
    product_approval: ProductSpecApproval
    solution_design_authorization: StageAdvanceAuthorization
    sources: Annotated[tuple[DesignContextSource, ...], Field(min_length=8, max_length=8)]
    permissions: DesignerAgentPermissions = DESIGNER_AGENT_PERMISSIONS
    built_at: AwareDatetime
    context_sha256: StageSha256

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        ensure_unique((source.uri for source in self.sources), "Designer context source URIs")
        _validate_lineage(*_lineage_from_manifest(self))
        expected_sources = _sources(*_source_facts(self))
        if self.sources != expected_sources:
            raise ValueError("Designer context sources do not match exact routed facts")
        expected = _manifest_digest(self)
        if self.context_sha256 != expected or self.context_id != f"ctx_{expected}":
            raise ValueError("Designer context identity does not match content")
        return self

    def validate_integrity(self) -> None:
        """Revalidate lineage, sources, and canonical identity after transport."""
        try:
            _validate_lineage(*_lineage_from_manifest(self))
            if self.sources != _sources(*_source_facts(self)):
                raise DesignContextIntegrityError(
                    "Designer context sources do not match exact routed facts"
                )
            expected = _manifest_digest(self)
        except (RuntimeError, ValueError) as error:
            if isinstance(error, DesignContextIntegrityError):
                raise
            raise DesignContextIntegrityError("Designer context lineage is invalid") from error
        if self.context_sha256 != expected or self.context_id != f"ctx_{expected}":
            raise DesignContextIntegrityError("Designer context identity does not match content")


class DesignContextBuilder:
    """Compile project knowledge and approved intent for Designer."""

    def build(
        self,
        preparation: ProjectPreparation,
        project_profile: ProjectProfile,
        project_baseline: ProjectSpecBaseline,
        project_request: ProjectRequest,
        product_spec: ProductSpec,
        product_approval: ProductSpecApproval,
        solution_design_authorization: StageAdvanceAuthorization,
        *,
        built_at: datetime,
    ) -> DesignContextManifest:
        if built_at.tzinfo is None or built_at.utcoffset() is None:
            raise DesignContextLineageError("built_at must be timezone-aware")
        lineage = (
            preparation,
            project_profile,
            project_baseline,
            project_request,
            product_spec,
            product_approval,
            solution_design_authorization,
        )
        try:
            _validate_lineage(*lineage)
        except (RuntimeError, ValueError) as error:
            raise DesignContextLineageError("Designer input lineage is invalid") from error
        permissions = DESIGNER_AGENT_PERMISSIONS
        sources = _sources(*lineage, permissions)
        identity = _identity(*lineage, sources, permissions)
        digest = _sha256(_canonical_json(identity))
        return DesignContextManifest(
            context_id=f"ctx_{digest}",
            project_id=preparation.project_id,
            request_id=project_request.id,
            preparation=preparation,
            project_profile=project_profile,
            project_baseline=project_baseline,
            project_request=project_request,
            product_spec=product_spec,
            product_approval=product_approval,
            solution_design_authorization=solution_design_authorization,
            sources=sources,
            permissions=permissions,
            built_at=built_at,
            context_sha256=digest,
        )


def _validate_lineage(
    preparation: ProjectPreparation,
    project_profile: ProjectProfile,
    project_baseline: ProjectSpecBaseline,
    project_request: ProjectRequest,
    product_spec: ProductSpec,
    product_approval: ProductSpecApproval,
    authorization: StageAdvanceAuthorization,
) -> None:
    preparation.validate_integrity()
    project_profile.validate_integrity()
    project_baseline.validate_integrity()
    project_request.validate_integrity()
    require_product_approval(product_spec, product_approval)
    authorization.validate_integrity()
    if (
        project_profile.project_id != preparation.project_id
        or project_profile.profile_sha256 != preparation.project_profile_sha256
        or project_baseline.project_id != preparation.project_id
        or project_baseline.project_profile_sha256 != project_profile.profile_sha256
        or project_baseline.baseline_sha256 != preparation.baseline_spec_sha256
        or project_request.project_id != preparation.project_id
        or project_request.preparation_sha256 != preparation.preparation_sha256
        or project_request.status is not ProjectRequestStatus.DESIGNING
        or product_spec.request_id != project_request.id
        or product_spec.project_id != project_request.project_id
    ):
        raise ValueError("Designer project/request/product lineage does not match")
    expected_inputs = (
        preparation.preparation_sha256,
        project_request.request_sha256,
        product_spec.product_spec_sha256,
        product_approval.approval_sha256,
    )
    if (
        authorization.target is not ProjectStage.SOLUTION_DESIGN
        or authorization.project_id != preparation.project_id
        or authorization.input_sha256s != expected_inputs
    ):
        raise ValueError("Designer launch authorization does not bind exact stage input")


def _sources(
    preparation: ProjectPreparation,
    project_profile: ProjectProfile,
    project_baseline: ProjectSpecBaseline,
    project_request: ProjectRequest,
    product_spec: ProductSpec,
    product_approval: ProductSpecApproval,
    authorization: StageAdvanceAuthorization,
    permissions: DesignerAgentPermissions,
) -> tuple[DesignContextSource, ...]:
    return (
        DesignContextSource(
            uri="policy://designer-agent/v0.1",
            sha256=_sha256(_canonical_json(permissions.to_wire())),
        ),
        DesignContextSource(
            uri=f"preparation://{preparation.project_id}",
            sha256=preparation.preparation_sha256,
        ),
        DesignContextSource(
            uri=f"project-profile://{preparation.project_id}",
            sha256=project_profile.profile_sha256,
        ),
        DesignContextSource(
            uri=f"baseline://{preparation.project_id}",
            sha256=project_baseline.baseline_sha256,
        ),
        DesignContextSource(
            uri=f"request://{project_request.id}", sha256=project_request.request_sha256
        ),
        DesignContextSource(
            uri=f"product-spec://{product_spec.id}", sha256=product_spec.product_spec_sha256
        ),
        DesignContextSource(
            uri=f"product-approval://{product_approval.id}",
            sha256=product_approval.approval_sha256,
        ),
        DesignContextSource(
            uri=f"stage-authorization://{authorization.target.value.lower()}",
            sha256=authorization.authorization_sha256,
        ),
    )


def _lineage_from_manifest(manifest: DesignContextManifest) -> DesignLineage:
    return (
        manifest.preparation,
        manifest.project_profile,
        manifest.project_baseline,
        manifest.project_request,
        manifest.product_spec,
        manifest.product_approval,
        manifest.solution_design_authorization,
    )


def _source_facts(manifest: DesignContextManifest) -> DesignSourceFacts:
    return (*_lineage_from_manifest(manifest), manifest.permissions)


def _identity(
    preparation: ProjectPreparation,
    project_profile: ProjectProfile,
    project_baseline: ProjectSpecBaseline,
    project_request: ProjectRequest,
    product_spec: ProductSpec,
    product_approval: ProductSpecApproval,
    authorization: StageAdvanceAuthorization,
    sources: tuple[DesignContextSource, ...],
    permissions: DesignerAgentPermissions,
) -> dict[str, object]:
    return {
        "kind": "design_context_manifest",
        "schema_version": "v0.1",
        "project_id": preparation.project_id,
        "request_id": project_request.id,
        "preparation": preparation.to_wire(),
        "project_profile": project_profile.to_wire(),
        "project_baseline": project_baseline.to_wire(),
        "project_request": project_request.to_wire(),
        "product_spec": product_spec.to_wire(),
        "product_approval": product_approval.to_wire(),
        "solution_design_authorization": authorization.to_wire(),
        "sources": [source.to_wire() for source in sources],
        "permissions": permissions.to_wire(),
    }


def _manifest_digest(manifest: DesignContextManifest) -> str:
    return _sha256(
        _canonical_json(
            _identity(
                manifest.preparation,
                manifest.project_profile,
                manifest.project_baseline,
                manifest.project_request,
                manifest.product_spec,
                manifest.product_approval,
                manifest.solution_design_authorization,
                manifest.sources,
                manifest.permissions,
            )
        )
    )


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


__all__ = [
    "DESIGNER_AGENT_PERMISSIONS",
    "DesignContextBuilder",
    "DesignContextError",
    "DesignContextIntegrityError",
    "DesignContextLineageError",
    "DesignContextManifest",
    "DesignContextSource",
    "DesignerAgentPermissions",
]
