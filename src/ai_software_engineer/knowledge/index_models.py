"""Versioned, digest-bound records for deterministic knowledge indexing."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel, ensure_unique
from ai_software_engineer.knowledge.models import (
    Digest,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeError,
    digest,
    text_digest,
)
from ai_software_engineer.knowledge_documents import (
    KnowledgeDocumentError,
    KnowledgeDocumentId,
    SourceName,
    _validate_source_name,
)

IndexVersion = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9._-]{1,40}$")]
JobStatus = Literal["QUEUED", "PROCESSING", "READY", "FAILED", "RETIRED"]


class KnowledgeIndexJob(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    job_id: Digest
    scope: Literal["team", "project"]
    team_id: TeamId
    project_id: ProjectId | None = None
    document_id: KnowledgeDocumentId
    source_name: SourceName
    source_sha256: Digest
    normalized_sha256: Digest | None = None
    replaces_document_id: KnowledgeDocumentId | None = None
    parser_version: IndexVersion
    index_version: IndexVersion
    status: JobStatus = "QUEUED"
    attempts: Annotated[int, Field(ge=0)] = 0
    created_at: AwareDatetime
    updated_at: AwareDatetime
    retry_at: AwareDatetime | None = None
    error_code: Literal["DOCUMENT_INVALID", "INDEX_INVALID", "REPLACEMENT_STALE"] | None = None
    job_sha256: Digest

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        try:
            _validate_source_name(self.source_name)
        except KnowledgeDocumentError as error:
            raise ValueError("index job source name is invalid") from error
        if (self.scope == "project") != (self.project_id is not None):
            raise ValueError("index job owner mismatch")
        if self.document_id != "knowledge_document_" + self.source_sha256[:32]:
            raise ValueError("index job document mismatch")
        if self.job_id != self.identity_digest():
            raise ValueError("index job identity mismatch")
        if self.status == "READY" and self.normalized_sha256 is None:
            raise ValueError("ready index job requires normalized digest")
        if (self.status == "FAILED") != (self.error_code is not None):
            raise ValueError("index job error status mismatch")
        if self.status == "PROCESSING" and self.attempts < 1:
            raise ValueError("processing index job requires attempt")
        return self

    def identity_digest(self) -> str:
        return digest(
            (
                self.scope,
                self.team_id,
                self.project_id,
                self.source_sha256,
                Path(self.source_name).suffix.lower(),
                self.replaces_document_id,
                self.parser_version,
                self.index_version,
            )
        )

    def validate_integrity(self) -> None:
        KnowledgeIndexJob.model_validate(self.to_wire())
        if self.job_sha256 != digest(self.model_dump(mode="json", exclude={"job_sha256"})):
            raise KnowledgeError("INDEX_JOB_INTEGRITY")

    def sealed(self) -> Self:
        return self.model_copy(
            update={"job_sha256": digest(self.model_dump(mode="json", exclude={"job_sha256"}))}
        )


class KnowledgeChunkCache(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    cache_key: Digest
    parser_version: IndexVersion
    index_version: IndexVersion
    document: KnowledgeDocument
    chunks: Annotated[tuple[KnowledgeChunk, ...], Field(max_length=1024)]
    cache_sha256: Digest

    @staticmethod
    def key(document: KnowledgeDocument, parser_version: str, index_version: str) -> str:
        return digest(
            (document.model_dump(mode="json", exclude={"content"}), parser_version, index_version)
        )

    def validate_integrity(self) -> None:
        KnowledgeDocument.model_validate(self.document.to_wire())
        if self.cache_key != self.key(
            self.document, self.parser_version, self.index_version
        ) or self.cache_sha256 != digest(self.model_dump(mode="json", exclude={"cache_sha256"})):
            raise KnowledgeError("INDEX_CACHE_INTEGRITY")
        for ordinal, chunk in enumerate(self.chunks):
            citation = chunk.citation
            if (
                chunk.ordinal != ordinal
                or text_digest(chunk.content) != citation.chunk_sha256
                or (
                    citation.document_id,
                    citation.scope,
                    citation.document_sha256,
                    citation.source_uri,
                )
                != (
                    self.document.document_id,
                    self.document.scope,
                    self.document.document_sha256,
                    self.document.source_uri,
                )
            ):
                raise KnowledgeError("INDEX_CHUNK_INTEGRITY")


class KnowledgeIndexEntry(DomainModel):
    document_id: KnowledgeDocumentId
    normalized_sha256: Digest
    cache_key: Digest
    selected: bool


class KnowledgeIndexManifest(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    scope: Literal["team", "project"]
    team_id: TeamId
    project_id: ProjectId | None = None
    parser_version: IndexVersion
    index_version: IndexVersion
    documents: Annotated[tuple[KnowledgeIndexEntry, ...], Field(max_length=1024)] = ()
    manifest_sha256: Digest

    @model_validator(mode="after")
    def validate_owner(self) -> Self:
        if (self.scope == "project") != (self.project_id is not None):
            raise ValueError("index manifest owner mismatch")
        ensure_unique((entry.document_id for entry in self.documents), "indexed documents")
        return self

    def validate_integrity(self) -> None:
        if self.manifest_sha256 != digest(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise KnowledgeError("INDEX_MANIFEST_INTEGRITY")


class KnowledgeIndexStatus(DomainModel):
    scope: Literal["team", "project"]
    team_id: TeamId
    project_id: ProjectId | None = None
    jobs: tuple[KnowledgeIndexJob, ...]
    backlog: Annotated[int, Field(ge=0)]
    failed: Annotated[int, Field(ge=0)]
    oldest_pending_seconds: Annotated[float, Field(ge=0)]
    active_manifest: KnowledgeIndexManifest | None = None
