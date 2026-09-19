"""Bounded deterministic Markdown retrieval; no model or storage authority."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from ai_software_engineer.knowledge.models import (
    KnowledgeChunk,
    KnowledgeCitation,
    KnowledgeDocument,
    KnowledgeError,
    KnowledgeHit,
    KnowledgeSnapshot,
    digest,
    text_digest,
)
from ai_software_engineer.redaction import redact_text

PARSER_VERSION = "markdown-v1"
INDEX_SCHEMA_VERSION = "lexical-v1"
MAX_CHUNK_CHARS = 4096


class KnowledgeRetrieval(Protocol):
    def search(
        self, snapshot: KnowledgeSnapshot, query: str, limit: int = 8
    ) -> tuple[KnowledgeHit, ...]: ...

    def read(self, snapshot: KnowledgeSnapshot, citation: KnowledgeCitation) -> KnowledgeChunk: ...


def terms(text: str) -> tuple[str, ...]:
    """Stable words and CJK bigrams without locale/model-dependent tokenization."""
    words = re.findall(r"[a-z0-9_]+", text.casefold())
    for sequence in re.findall(r"[\u3400-\u9fff]+", text):
        words.extend(sequence[i : i + 2] for i in range(max(1, len(sequence) - 1)))
    return tuple(sorted(set(words)))


def parse_document(document: KnowledgeDocument) -> tuple[KnowledgeChunk, ...]:
    KnowledgeDocument.model_validate(document.to_wire())
    safe = redact_text(document.content).text
    sections: list[tuple[tuple[str, ...], str]] = []
    headings: list[tuple[int, str]] = []
    lines: list[str] = []
    fenced = False
    for line in safe.splitlines(keepends=True):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        heading = None if fenced else re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            if lines:
                sections.append((tuple(title for _, title in headings), "".join(lines)))
                lines = []
            level, title = len(heading[1]), heading[2]
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
        lines.append(line)
    if lines:
        sections.append((tuple(title for _, title in headings), "".join(lines)))
    chunks: list[KnowledgeChunk] = []
    for section_path, body in sections:
        for offset in range(0, len(body), MAX_CHUNK_CHARS):
            content = body[offset : offset + MAX_CHUNK_CHARS]
            ordinal = len(chunks)
            chunk_id = digest(
                (
                    document.scope,
                    document.document_id,
                    document.document_sha256,
                    PARSER_VERSION,
                    section_path,
                    ordinal,
                )
            )
            chunks.append(
                KnowledgeChunk(
                    citation=KnowledgeCitation(
                        document_id=document.document_id,
                        scope=document.scope,
                        document_sha256=document.document_sha256,
                        chunk_id=chunk_id,
                        chunk_sha256=text_digest(content),
                        source_uri=document.source_uri,
                    ),
                    title=redact_text(document.title).text,
                    section_path=section_path,
                    ordinal=ordinal,
                    content=content,
                    terms=terms(content),
                )
            )
    return tuple(chunks)


def score_chunks(
    chunks: Iterable[KnowledgeChunk], query: str, limit: int = 8
) -> tuple[KnowledgeHit, ...]:
    if not 1 <= limit <= 20 or not 1 <= len(query) <= 512:
        raise KnowledgeError("QUERY_LIMIT")
    query_terms = set(terms(query))
    hits: list[KnowledgeHit] = []
    for chunk in chunks:
        matched = tuple(sorted(query_terms.intersection(chunk.terms)))
        if matched:
            hits.append(
                KnowledgeHit(
                    citation=chunk.citation,
                    title=chunk.title,
                    section_path=chunk.section_path,
                    matched_terms=matched,
                    score=len(matched),
                    snippet=chunk.content[:800],
                )
            )
    return tuple(
        sorted(
            hits,
            key=lambda hit: (
                -hit.score,
                hit.citation.scope,
                hit.citation.document_id,
                hit.citation.chunk_id,
            ),
        )[:limit]
    )


class MarkdownKnowledgeRetrieval:
    def search(
        self, snapshot: KnowledgeSnapshot, query: str, limit: int = 8
    ) -> tuple[KnowledgeHit, ...]:
        snapshot.validate_integrity()
        return score_chunks(
            (chunk for doc in snapshot.documents for chunk in parse_document(doc)), query, limit
        )

    def read(self, snapshot: KnowledgeSnapshot, citation: KnowledgeCitation) -> KnowledgeChunk:
        snapshot.validate_integrity()
        for doc in snapshot.documents:
            if (doc.scope, doc.document_id, doc.document_sha256) == (
                citation.scope,
                citation.document_id,
                citation.document_sha256,
            ):
                for chunk in parse_document(doc):
                    if chunk.citation == citation:
                        return chunk
        raise KnowledgeError("CITATION_NOT_IN_SNAPSHOT")
