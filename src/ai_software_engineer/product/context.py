"""Product-discovery context that is independent of Delivery ``Task`` context.

The Product Agent receives a complete, immutable view of the prepared project,
the current request, and the durable dialogue chain.  It never receives a fake
Delivery Task or a mutable model-session transcript.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain import ProductSpec, ProjectPreparation, ProjectRequest
from ai_software_engineer.domain.identity import ContextId, ProjectId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.project_delivery import (
    ProductSpecId,
    ProjectRequestId,
    StageSha256,
)
from ai_software_engineer.product.models import ProductDialogueActor
from ai_software_engineer.project_manager.baseline import ProjectSpecBaseline
from ai_software_engineer.project_profile import ProjectProfile

ProductDialogueSha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class ProductContextError(RuntimeError):
    """Base error for Product Agent context compilation."""


class ProductContextLineageError(ProductContextError):
    """Raised when prepared project, request, dialogue, and spec do not form one chain."""


class ProductContextIntegrityError(ProductContextError):
    """Raised when an already-built Product context no longer matches its digest."""


class ProductAgentPermissions(DomainModel):
    """Fail-closed permissions delivered to every Product Agent invocation."""

    read_project_facts: Literal[True] = True
    read_project_rules: Literal[True] = True
    read_project_request: Literal[True] = True
    read_product_dialogue: Literal[True] = True
    output_clarification: Literal[True] = True
    output_product_spec: Literal[True] = True
    write_code: Literal[False] = False
    execute_shell: Literal[False] = False
    change_project_state: Literal[False] = False
    approve_product_spec: Literal[False] = False


PRODUCT_AGENT_PERMISSIONS = ProductAgentPermissions()


class ProductDialogueContextItem(DomainModel):
    """Minimal, digest-bound view of one immutable dialogue record."""

    sequence: Annotated[StrictInt, Field(ge=1)]
    actor: ProductDialogueActor
    summary: NonEmptyStr
    previous_sha256: ProductDialogueSha256 | None = None
    dialogue_sha256: ProductDialogueSha256


class ProductContextSource(DomainModel):
    """URI and digest of one durable fact routed into Product context."""

    uri: NonEmptyStr
    sha256: StageSha256

    @model_validator(mode="after")
    def validate_uri(self) -> Self:
        if any(ord(character) < 32 for character in self.uri):
            raise ValueError("ProductContextSource uri cannot contain control characters")
        return self


class ProductContextManifest(DomainModel):
    """Exact, replayable Product Agent input manifest."""

    kind: Literal["product_context_manifest"] = "product_context_manifest"
    schema_version: Literal["v0.1"] = "v0.1"
    context_id: ContextId
    project_id: ProjectId
    request_id: ProjectRequestId
    preparation: ProjectPreparation
    project_profile: ProjectProfile
    project_baseline: ProjectSpecBaseline
    project_request: ProjectRequest
    dialogue: tuple[ProductDialogueContextItem, ...] = ()
    current_product_spec: ProductSpec | None = None
    expected_product_spec_version: Annotated[StrictInt, Field(ge=1)]
    expected_supersedes: ProductSpecId | None = None
    sources: Annotated[tuple[ProductContextSource, ...], Field(min_length=5)]
    permissions: ProductAgentPermissions = PRODUCT_AGENT_PERMISSIONS
    built_at: AwareDatetime
    context_sha256: StageSha256

    @model_validator(mode="after")
    def validate_manifest_shape(self) -> Self:
        ensure_unique((source.uri for source in self.sources), "Product context source URIs")
        self._validate_lineage()
        expected_sources = _context_sources(
            self.preparation,
            self.project_profile,
            self.project_baseline,
            self.project_request,
            self.dialogue,
            self.current_product_spec,
            self.permissions,
        )
        if self.sources != expected_sources:
            raise ValueError("Product context sources do not match the exact routed facts")
        expected_digest = _manifest_digest(self)
        if self.context_sha256 != expected_digest:
            raise ValueError("Product context digest does not match content")
        if self.context_id != f"ctx_{expected_digest}":
            raise ValueError("Product context ID does not match content")
        return self

    def _validate_lineage(self) -> None:
        try:
            self.preparation.validate_integrity()
            self.project_profile.validate_integrity()
            self.project_baseline.validate_integrity()
            self.project_request.validate_integrity()
            if self.current_product_spec is not None:
                self.current_product_spec.validate_integrity()
        except RuntimeError as error:
            raise ValueError("Product context contains an invalid stage document") from error
        if (
            self.project_id != self.preparation.project_id
            or self.project_profile.project_id != self.project_id
            or self.project_baseline.project_id != self.project_id
            or self.project_profile.profile_sha256 != self.preparation.project_profile_sha256
            or self.project_baseline.project_profile_sha256 != self.project_profile.profile_sha256
            or self.project_baseline.baseline_sha256 != self.preparation.baseline_spec_sha256
            or self.request_id != self.project_request.id
            or self.project_request.project_id != self.project_id
            or self.project_request.preparation_sha256 != self.preparation.preparation_sha256
        ):
            raise ValueError("Product context preparation/request lineage does not match")
        _validate_dialogue_chain(self.dialogue)
        current = self.current_product_spec
        expected_version = 1 if current is None else current.version + 1
        expected_supersedes = None if current is None else current.id
        if current is not None and (
            current.project_id != self.project_id or current.request_id != self.request_id
        ):
            raise ValueError("current ProductSpec belongs to another request")
        if (
            self.expected_product_spec_version != expected_version
            or self.expected_supersedes != expected_supersedes
        ):
            raise ValueError("next ProductSpec version/supersedes do not match current spec")

    def validate_integrity(self) -> None:
        """Recheck the canonical identity after persistence or transport."""
        try:
            self._validate_lineage()
            if self.sources != _context_sources(
                self.preparation,
                self.project_profile,
                self.project_baseline,
                self.project_request,
                self.dialogue,
                self.current_product_spec,
                self.permissions,
            ):
                raise ProductContextIntegrityError(
                    "Product context sources do not match routed facts"
                )
            expected = _manifest_digest(self)
        except (RuntimeError, ValueError) as error:
            if isinstance(error, ProductContextIntegrityError):
                raise
            raise ProductContextIntegrityError("Product context lineage is invalid") from error
        if self.context_sha256 != expected or self.context_id != f"ctx_{expected}":
            raise ProductContextIntegrityError("Product context identity does not match content")


class ProductContextBuilder:
    """Compile exact Product discovery facts without touching Delivery Task context."""

    def build(
        self,
        preparation: ProjectPreparation,
        project_profile: ProjectProfile,
        project_baseline: ProjectSpecBaseline,
        project_request: ProjectRequest,
        *,
        dialogue: tuple[ProductDialogueContextItem, ...] = (),
        current_product_spec: ProductSpec | None = None,
        built_at: datetime,
    ) -> ProductContextManifest:
        """Return a deterministic manifest; ``built_at`` is not part of its identity."""
        if built_at.tzinfo is None or built_at.utcoffset() is None:
            raise ProductContextLineageError("built_at must be timezone-aware")
        try:
            preparation.validate_integrity()
            project_profile.validate_integrity()
            project_baseline.validate_integrity()
            project_request.validate_integrity()
            if current_product_spec is not None:
                current_product_spec.validate_integrity()
        except RuntimeError as error:
            raise ProductContextLineageError("Product context stage integrity failed") from error
        if (
            project_request.project_id != preparation.project_id
            or project_profile.project_id != preparation.project_id
            or project_baseline.project_id != preparation.project_id
            or project_profile.profile_sha256 != preparation.project_profile_sha256
            or project_baseline.project_profile_sha256 != project_profile.profile_sha256
            or project_baseline.baseline_sha256 != preparation.baseline_spec_sha256
            or project_request.preparation_sha256 != preparation.preparation_sha256
        ):
            raise ProductContextLineageError(
                "ProjectRequest does not belong to the exact ProjectPreparation"
            )
        try:
            _validate_dialogue_chain(dialogue)
        except ValueError as error:
            raise ProductContextLineageError(str(error)) from error
        if current_product_spec is not None and (
            current_product_spec.project_id != project_request.project_id
            or current_product_spec.request_id != project_request.id
        ):
            raise ProductContextLineageError("current ProductSpec belongs to another request")

        permissions = PRODUCT_AGENT_PERMISSIONS
        sources = _context_sources(
            preparation,
            project_profile,
            project_baseline,
            project_request,
            dialogue,
            current_product_spec,
            permissions,
        )
        expected_version = 1 if current_product_spec is None else current_product_spec.version + 1
        expected_supersedes = None if current_product_spec is None else current_product_spec.id
        identity = _manifest_identity(
            project_id=preparation.project_id,
            request_id=project_request.id,
            preparation=preparation,
            project_profile=project_profile,
            project_baseline=project_baseline,
            project_request=project_request,
            dialogue=dialogue,
            current_product_spec=current_product_spec,
            expected_product_spec_version=expected_version,
            expected_supersedes=expected_supersedes,
            sources=sources,
            permissions=permissions,
        )
        digest = _sha256(_canonical_json(identity))
        return ProductContextManifest(
            context_id=f"ctx_{digest}",
            project_id=preparation.project_id,
            request_id=project_request.id,
            preparation=preparation,
            project_profile=project_profile,
            project_baseline=project_baseline,
            project_request=project_request,
            dialogue=dialogue,
            current_product_spec=current_product_spec,
            expected_product_spec_version=expected_version,
            expected_supersedes=expected_supersedes,
            sources=sources,
            permissions=permissions,
            built_at=built_at,
            context_sha256=digest,
        )


def _validate_dialogue_chain(dialogue: tuple[ProductDialogueContextItem, ...]) -> None:
    for index, item in enumerate(dialogue, start=1):
        expected_previous = None if index == 1 else dialogue[index - 2].dialogue_sha256
        if item.sequence != index:
            raise ValueError("Product dialogue sequence must be contiguous from one")
        if item.previous_sha256 != expected_previous:
            raise ValueError("Product dialogue previous digest does not match chain head")


def _context_sources(
    preparation: ProjectPreparation,
    project_profile: ProjectProfile,
    project_baseline: ProjectSpecBaseline,
    project_request: ProjectRequest,
    dialogue: tuple[ProductDialogueContextItem, ...],
    current_product_spec: ProductSpec | None,
    permissions: ProductAgentPermissions,
) -> tuple[ProductContextSource, ...]:
    sources = [
        ProductContextSource(
            uri="policy://product-agent/v0.1",
            sha256=_sha256(_canonical_json(permissions.to_wire())),
        ),
        ProductContextSource(
            uri=f"preparation://{preparation.project_id}",
            sha256=preparation.preparation_sha256,
        ),
        ProductContextSource(
            uri=f"project-profile://{preparation.project_id}",
            sha256=project_profile.profile_sha256,
        ),
        ProductContextSource(
            uri=f"baseline://{preparation.project_id}",
            sha256=project_baseline.baseline_sha256,
        ),
        ProductContextSource(
            uri=f"request://{project_request.id}",
            sha256=project_request.request_sha256,
        ),
    ]
    # ProjectPreparation carries individual source URIs but not their document
    # digests. Advertising the aggregate baseline digest for each URI would be a
    # false provenance claim, so Product context routes only the verified aggregate.
    sources.extend(
        ProductContextSource(
            uri=f"dialogue://{project_request.id}/{item.sequence}",
            sha256=item.dialogue_sha256,
        )
        for item in dialogue
    )
    if current_product_spec is not None:
        sources.append(
            ProductContextSource(
                uri=f"product-spec://{current_product_spec.id}",
                sha256=current_product_spec.product_spec_sha256,
            )
        )
    result = tuple(sources)
    ensure_unique((source.uri for source in result), "Product context source URIs")
    return result


def _manifest_identity(
    *,
    project_id: str,
    request_id: str,
    preparation: ProjectPreparation,
    project_profile: ProjectProfile,
    project_baseline: ProjectSpecBaseline,
    project_request: ProjectRequest,
    dialogue: tuple[ProductDialogueContextItem, ...],
    current_product_spec: ProductSpec | None,
    expected_product_spec_version: int,
    expected_supersedes: str | None,
    sources: tuple[ProductContextSource, ...],
    permissions: ProductAgentPermissions,
) -> dict[str, object]:
    return {
        "kind": "product_context_manifest",
        "schema_version": "v0.1",
        "project_id": project_id,
        "request_id": request_id,
        "preparation": preparation.to_wire(),
        "project_profile": project_profile.to_wire(),
        "project_baseline": project_baseline.to_wire(),
        "project_request": project_request.to_wire(),
        "dialogue": [item.to_wire() for item in dialogue],
        "current_product_spec": (
            None if current_product_spec is None else current_product_spec.to_wire()
        ),
        "expected_product_spec_version": expected_product_spec_version,
        "expected_supersedes": expected_supersedes,
        "sources": [source.to_wire() for source in sources],
        "permissions": permissions.to_wire(),
    }


def _manifest_digest(manifest: ProductContextManifest) -> str:
    identity = _manifest_identity(
        project_id=manifest.project_id,
        request_id=manifest.request_id,
        preparation=manifest.preparation,
        project_profile=manifest.project_profile,
        project_baseline=manifest.project_baseline,
        project_request=manifest.project_request,
        dialogue=manifest.dialogue,
        current_product_spec=manifest.current_product_spec,
        expected_product_spec_version=manifest.expected_product_spec_version,
        expected_supersedes=manifest.expected_supersedes,
        sources=manifest.sources,
        permissions=manifest.permissions,
    )
    return _sha256(_canonical_json(identity))


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
    "PRODUCT_AGENT_PERMISSIONS",
    "ProductAgentPermissions",
    "ProductContextBuilder",
    "ProductContextError",
    "ProductContextIntegrityError",
    "ProductContextLineageError",
    "ProductContextManifest",
    "ProductContextSource",
    "ProductDialogueActor",
    "ProductDialogueContextItem",
]
