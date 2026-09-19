"""Build retrieval snapshots exclusively from already-verified frozen Context sources."""

from __future__ import annotations

from urllib.parse import urlparse

from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.models import (
    KnowledgeDocument,
    KnowledgeError,
    KnowledgeSnapshot,
    digest,
    text_digest,
)
from ai_software_engineer.manager.baseline import ProjectSpecBaseline
from ai_software_engineer.redaction import redact_text


class _TeamContext(DomainModel):
    team_id: str
    team_manifest_sha256: str
    documents: tuple[ContextSource, ...]
    interpretation: str


class _SpecBody(DomainModel):
    spec_id: str
    spec_key: str
    version: int
    title: str
    body_markdown: str
    roles: tuple[TeamRole, ...]
    stages: tuple[str, ...]
    repository_ids: tuple[str, ...]
    path_globs: tuple[str, ...]
    verification: str


def snapshot_from_sources(
    *,
    team_id: str,
    project_id: str,
    requirement_id: str,
    repository_ids: tuple[str, ...],
    sources: tuple[tuple[str, ContextSource], ...],
) -> KnowledgeSnapshot:
    documents: dict[tuple[str, str], KnowledgeDocument] = {}

    def add(document: KnowledgeDocument) -> None:
        key = (document.scope, document.document_id)
        prior = documents.get(key)
        if prior is not None and prior != document:
            if prior.model_dump(exclude={"repository_ids"}) != document.model_dump(
                exclude={"repository_ids"}
            ):
                raise KnowledgeError("FROZEN_SOURCE_CONFLICT")
            document = document.model_copy(
                update={
                    "repository_ids": tuple(
                        sorted(set(prior.repository_ids + document.repository_ids))
                    )
                }
            )
        documents[key] = document

    def visit(repository_id: str, source: ContextSource) -> None:
        if source.content is None:
            raise KnowledgeError("UNRESOLVED_SOURCE")
        parsed = urlparse(source.uri)
        content = redact_text(source.content).text
        if parsed.scheme == "baseline":
            baseline = ProjectSpecBaseline.model_validate_json(source.content)
            baseline.validate_integrity()
            if baseline.repository_id != repository_id:
                raise KnowledgeError("BASELINE_REPOSITORY")
            for rule in baseline.rules:
                if rule.field == "context.team":
                    context = _TeamContext.model_validate(rule.value)
                    if context.team_id != team_id:
                        raise KnowledgeError("CONTEXT_TEAM")
                    for nested in context.documents:
                        visit(repository_id, nested)
                elif rule.field.startswith("governance."):
                    spec = _SpecBody.model_validate(rule.value)
                    safe = redact_text(spec.body_markdown).text
                    add(
                        KnowledgeDocument(
                            document_id=spec.spec_id,
                            scope="spec",
                            team_id=team_id,
                            project_id=None
                            if rule.source_uri.startswith("platform://")
                            else project_id,
                            repository_ids=tuple(
                                r for r in spec.repository_ids if r in repository_ids
                            ),
                            roles=spec.roles,
                            title=redact_text(spec.title).text,
                            source_uri=rule.source_uri,
                            document_sha256=rule.source_sha256,
                            content_sha256=text_digest(safe),
                            content=safe,
                        )
                    )
            return
        if parsed.scheme in {"team", "project"} and "/knowledge/" in parsed.path:
            expected = team_id if parsed.scheme == "team" else project_id
            if parsed.netloc != expected:
                raise KnowledgeError("SOURCE_OWNER")
            parts = parsed.path.split("/")
            identity = next(
                (part for part in parts if part.startswith("knowledge_document_")),
                "document_" + digest(source.uri)[:32],
            )
            uri = f"knowledge://{parsed.scheme}/{expected}/{identity}"
            add(
                KnowledgeDocument(
                    document_id=identity,
                    scope="team" if parsed.scheme == "team" else "project",
                    team_id=team_id,
                    project_id=None if parsed.scheme == "team" else project_id,
                    title=content.splitlines()[0].lstrip("# ")[:300]
                    if content.strip()
                    else identity,
                    source_uri=uri,
                    document_sha256=parsed.fragment or text_digest(content),
                    content_sha256=text_digest(content),
                    content=content,
                )
            )
        elif source.source_id.startswith("native.rule."):
            add(
                KnowledgeDocument(
                    document_id="native_" + digest((repository_id, source.uri))[:32],
                    scope="repository",
                    team_id=team_id,
                    project_id=project_id,
                    repository_ids=(repository_id,),
                    title=source.source_id,
                    source_uri=source.uri,
                    document_sha256=text_digest(content),
                    content=content,
                )
            )

    for repository_id, source in sources:
        if repository_id not in repository_ids:
            raise KnowledgeError("SOURCE_REPOSITORY")
        visit(repository_id, source)
    return KnowledgeSnapshot.create(
        team_id=team_id,
        project_id=project_id,
        requirement_id=requirement_id,
        repository_ids=repository_ids,
        documents=tuple(documents.values()),
    )
