"""Strict wire contracts for scoped, frozen knowledge retrieval."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.identity import ContextId, ProjectId, RepositoryId, RunId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId

Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
KnowledgeId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-zA-Z0-9_.:-]{0,159}$")]
KnowledgeScope = Literal["team", "project", "repository", "spec"]
BoundedText = Annotated[str, StringConstraints(min_length=1, max_length=4096)]


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class KnowledgeError(RuntimeError):
    """Stable fail-closed knowledge error without provider or document payloads."""


class KnowledgeDocument(DomainModel):
    document_id: KnowledgeId
    scope: KnowledgeScope
    team_id: TeamId
    project_id: ProjectId | None = None
    repository_ids: tuple[RepositoryId, ...] = ()
    roles: tuple[TeamRole, ...] = ()
    title: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    source_uri: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    document_sha256: Digest
    content_sha256: Digest | None = None
    content: Annotated[str, StringConstraints(max_length=1_000_000)]

    @model_validator(mode="after")
    def validate_document(self) -> Self:
        if self.scope in {"project", "repository"} and self.project_id is None:
            raise ValueError("Project knowledge requires owner")
        if self.scope == "team" and self.project_id is not None:
            raise ValueError("Team knowledge cannot have a Project owner")
        if self.scope == "repository" and not self.repository_ids:
            raise ValueError("native rules require Repository scope")
        if any(ord(c) < 32 for c in self.source_uri):
            raise ValueError("invalid source URI")
        ensure_unique(self.repository_ids, "knowledge repositories")
        ensure_unique(self.roles, "knowledge roles")
        if text_digest(self.content) != (self.content_sha256 or self.document_sha256):
            raise ValueError("knowledge document digest mismatch")
        return self


class KnowledgeSnapshot(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    team_id: TeamId
    project_id: ProjectId
    requirement_id: KnowledgeId
    repository_ids: Annotated[tuple[RepositoryId, ...], Field(min_length=1, max_length=64)]
    documents: Annotated[tuple[KnowledgeDocument, ...], Field(max_length=256)] = ()
    snapshot_sha256: Digest

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        ensure_unique(self.repository_ids, "snapshot repositories")
        ensure_unique(((d.scope, d.document_id) for d in self.documents), "snapshot documents")
        for document in self.documents:
            KnowledgeDocument.model_validate(document.to_wire())
            if document.team_id != self.team_id or document.project_id not in {
                None,
                self.project_id,
            }:
                raise ValueError("cross-owner knowledge snapshot")
            if document.repository_ids and not set(document.repository_ids) <= set(
                self.repository_ids
            ):
                raise ValueError("cross-repository knowledge snapshot")
        return self

    @classmethod
    def create(
        cls,
        *,
        team_id: str,
        project_id: str,
        requirement_id: str,
        repository_ids: tuple[str, ...],
        documents: tuple[KnowledgeDocument, ...] = (),
    ) -> Self:
        provisional = cls(
            team_id=team_id,
            project_id=project_id,
            requirement_id=requirement_id,
            repository_ids=tuple(sorted(repository_ids)),
            documents=tuple(sorted(documents, key=lambda d: (d.scope, d.document_id))),
            snapshot_sha256="0" * 64,
        )
        return provisional.model_copy(update={"snapshot_sha256": provisional.recompute_digest()})

    def recompute_digest(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"snapshot_sha256"}))

    def validate_integrity(self) -> None:
        KnowledgeSnapshot.model_validate(self.to_wire())
        if self.snapshot_sha256 != self.recompute_digest():
            raise KnowledgeError("SNAPSHOT_INTEGRITY")


class KnowledgeCitation(DomainModel):
    document_id: KnowledgeId
    scope: KnowledgeScope
    document_sha256: Digest
    chunk_id: Digest
    chunk_sha256: Digest
    source_uri: NonEmptyStr


class KnowledgeChunk(DomainModel):
    citation: KnowledgeCitation
    title: NonEmptyStr
    section_path: tuple[str, ...] = ()
    ordinal: Annotated[int, Field(ge=0)]
    content: Annotated[str, StringConstraints(max_length=4096)]
    terms: tuple[str, ...] = ()


class KnowledgeHit(DomainModel):
    citation: KnowledgeCitation
    title: NonEmptyStr
    section_path: tuple[str, ...]
    matched_terms: tuple[str, ...]
    score: Annotated[int, Field(ge=1)]
    snippet: Annotated[str, StringConstraints(max_length=800)]


class KnowledgeRunBinding(DomainModel):
    run_id: RunId
    task_id: TaskId | None = None
    role: TeamRole
    team_id: TeamId
    project_id: ProjectId
    requirement_id: KnowledgeId
    repository_ids: Annotated[tuple[RepositoryId, ...], Field(min_length=1, max_length=64)]
    source_revision: NonEmptyStr
    context_manifest_id: ContextId
    snapshot_sha256: Digest


class KnowledgeSearchRequest(DomainModel):
    operation_id: KnowledgeId
    binding: KnowledgeRunBinding
    query: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    scopes: tuple[KnowledgeScope, ...] = ()
    limit: Annotated[int, Field(ge=1, le=20)] = 8


class KnowledgeReadRequest(DomainModel):
    operation_id: KnowledgeId
    binding: KnowledgeRunBinding
    search_evidence_id: Digest
    citation: KnowledgeCitation


class KnowledgeEvidence(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    binding: KnowledgeRunBinding
    operation_id: KnowledgeId
    operation: Literal["search_knowledge", "read_knowledge"]
    request_sha256: Digest
    query: str = ""
    scopes: tuple[KnowledgeScope, ...] = ()
    status: Literal["HIT", "MISS", "READ", "REJECTED"]
    hits: tuple[KnowledgeHit, ...] = ()
    chunk: KnowledgeChunk | None = None
    error_code: str | None = None
    evidence_id: Digest

    def validate_integrity(self) -> None:
        if self.evidence_id != digest(self.model_dump(mode="json", exclude={"evidence_id"})):
            raise KnowledgeError("EVIDENCE_INTEGRITY")


class KnowledgeRunManifest(DomainModel):
    binding: KnowledgeRunBinding
    snapshot_sha256: Digest
    evidence_ids: tuple[Digest, ...]
    citations: tuple[KnowledgeCitation, ...]
    manifest_sha256: Digest

    def validate_integrity(self) -> None:
        if self.manifest_sha256 != digest(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise KnowledgeError("MANIFEST_INTEGRITY")
