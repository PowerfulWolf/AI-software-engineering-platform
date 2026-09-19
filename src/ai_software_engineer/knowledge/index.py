"""Bounded deterministic background indexing and frozen-snapshot retrieval adapter."""

from __future__ import annotations

import fcntl
import hashlib
import os
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

from ai_software_engineer.knowledge.index_models import (
    KnowledgeChunkCache,
    KnowledgeIndexEntry,
    KnowledgeIndexJob,
    KnowledgeIndexManifest,
    KnowledgeIndexStatus,
)
from ai_software_engineer.knowledge.index_store import KnowledgeIndexStore, failed_job
from ai_software_engineer.knowledge.models import (
    KnowledgeChunk,
    KnowledgeCitation,
    KnowledgeDocument,
    KnowledgeError,
    KnowledgeHit,
    KnowledgeSnapshot,
    digest,
)
from ai_software_engineer.knowledge.mutation import knowledge_mutation_lock
from ai_software_engineer.knowledge.retrieval import (
    INDEX_SCHEMA_VERSION,
    PARSER_VERSION,
    parse_document,
    score_chunks,
)
from ai_software_engineer.knowledge_documents import (
    KnowledgeDocumentError,
    KnowledgeDocumentManifest,
    ProjectKnowledgeDocumentStore,
    TeamKnowledgeDocumentStore,
    _read_bounded,
    _validate_source_name,
)
from ai_software_engineer.knowledge_selection import (
    KnowledgeSelectionError,
    ProjectKnowledgeSelectionStore,
    TeamKnowledgeSelectionStore,
    effective_project_knowledge_paths,
    effective_team_knowledge_paths,
)
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.team_workspace import (
    MAX_TEAM_KNOWLEDGE_DOCUMENT_BYTES,
    MAX_TEAM_KNOWLEDGE_SOURCE_BYTES,
    TeamWorkspace,
)

Workspace = TeamWorkspace | ProjectWorkspace


class KnowledgeIndexer:
    """Owns one scope; never receives delivery state or model ports."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        parser_version: str = PARSER_VERSION,
        index_version: str = INDEX_SCHEMA_VERSION,
        fallback_paths: tuple[str, ...] = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        workspace.validate_current()
        self.workspace = workspace
        self.documents: TeamKnowledgeDocumentStore | ProjectKnowledgeDocumentStore
        self.selection: TeamKnowledgeSelectionStore | ProjectKnowledgeSelectionStore
        if isinstance(workspace, TeamWorkspace):
            self.documents = TeamKnowledgeDocumentStore(workspace)
            self.selection = TeamKnowledgeSelectionStore(workspace)
        else:
            self.documents = ProjectKnowledgeDocumentStore(workspace)
            self.selection = ProjectKnowledgeSelectionStore(workspace)
        self.parser_version = parser_version
        self.index_version = index_version
        self.fallback_paths = fallback_paths
        self.clock = clock
        self.store = KnowledgeIndexStore(
            workspace.root / "knowledge" / "index",
            scope=self.documents.scope,
            team_id=self.documents.team_id,
            project_id=self.documents.project_id,
        )

    def enqueue(
        self, *, filename: str, content: bytes, replaces_document_id: str | None = None
    ) -> KnowledgeIndexJob:
        self.workspace.validate_current()
        _validate_source_name(filename)
        if not content or len(content) > MAX_TEAM_KNOWLEDGE_SOURCE_BYTES:
            raise KnowledgeDocumentError("knowledge document violates upload size limit")
        if replaces_document_id is not None and replaces_document_id not in {
            item.document_id for item in self.documents.list()
        }:
            raise KnowledgeError("REPLACEMENT_STALE")
        source_sha = hashlib.sha256(content).hexdigest()
        return self.store.enqueue(
            self._new_job(filename, source_sha, replaces_document_id), content
        )

    def _new_job(
        self, filename: str, source_sha: str, replaces_document_id: str | None = None
    ) -> KnowledgeIndexJob:
        now = self.clock()
        job_id = digest(
            (
                self.documents.scope,
                self.documents.team_id,
                self.documents.project_id,
                source_sha,
                Path(filename).suffix.lower(),
                replaces_document_id,
                self.parser_version,
                self.index_version,
            )
        )
        return KnowledgeIndexJob(
            job_id=job_id,
            scope=self.documents.scope,
            team_id=self.documents.team_id,
            project_id=self.documents.project_id,
            document_id="knowledge_document_" + source_sha[:32],
            source_name=filename,
            source_sha256=source_sha,
            replaces_document_id=replaces_document_id,
            parser_version=self.parser_version,
            index_version=self.index_version,
            created_at=now,
            updated_at=now,
            job_sha256="0" * 64,
        ).sealed()

    def _paths(self) -> tuple[str, ...]:
        if isinstance(self.workspace, TeamWorkspace):
            return effective_team_knowledge_paths(self.workspace, self.fallback_paths)
        return effective_project_knowledge_paths(self.workspace, self.fallback_paths)

    def _reconcile(self) -> None:
        existing = {
            (job.document_id, job.parser_version, job.index_version) for job in self.store.jobs()
        }
        active = self.documents.list()
        for manifest in active:
            if (manifest.document_id, self.parser_version, self.index_version) not in existing:
                self.store.enqueue(
                    self._new_job(manifest.source_name, manifest.source_sha256), None
                )
        self.store.retire({manifest.document_id for manifest in active}, now=self.clock())

    def tick(self, *, limit: int = 4) -> tuple[KnowledgeIndexJob, ...]:
        if not 1 <= limit <= 32:
            raise KnowledgeError("INDEX_BATCH_LIMIT")
        self.workspace.validate_current()
        lock_path = self.store.root / "worker.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return ()
            self._reconcile()
            results: list[KnowledgeIndexJob] = []
            for _ in range(limit):
                claimed = self.store.claim(
                    now=self.clock(),
                    parser_version=self.parser_version,
                    index_version=self.index_version,
                )
                if claimed is None:
                    break
                job, source, token = claimed
                try:
                    result = self._process(job, source, token)
                except (KnowledgeDocumentError, KnowledgeSelectionError, UnicodeError, ValueError):
                    result = failed_job(job, "DOCUMENT_INVALID", self.clock())
                except (KnowledgeError, OSError) as error:
                    result = failed_job(
                        job,
                        "REPLACEMENT_STALE"
                        if str(error) == "REPLACEMENT_STALE"
                        else "INDEX_INVALID",
                        self.clock(),
                    )
                self.store.finish(result, token, now=self.clock())
                results.append(result)
            self._publish()
            self.store.retire({m.document_id for m in self.documents.list()}, now=self.clock())
            return tuple(results)
        finally:
            os.close(descriptor)

    def _process(
        self, job: KnowledgeIndexJob, source: bytes | None, token: str
    ) -> KnowledgeIndexJob:
        if not self.store.owns_replacement(job):
            raise KnowledgeError("REPLACEMENT_STALE")
        if source is not None:
            if hashlib.sha256(source).hexdigest() != job.source_sha256:
                raise KnowledgeError("INDEX_SOURCE_INTEGRITY")
            manifest = self.documents.import_document(filename=job.source_name, content=source)
        else:
            found = next(
                (m for m in self.documents.list() if m.document_id == job.document_id), None
            )
            if found is None:
                return job.model_copy(
                    update={"status": "RETIRED", "updated_at": self.clock()}
                ).sealed()
            manifest = found
        document = self._document(manifest)
        key = KnowledgeChunkCache.key(document, self.parser_version, self.index_version)
        if self.store.cache(key) is None:
            provisional = KnowledgeChunkCache(
                cache_key=key,
                parser_version=self.parser_version,
                index_version=self.index_version,
                document=document,
                chunks=parse_document(document),
                cache_sha256="0" * 64,
            )
            self.store.put_cache(
                provisional.model_copy(
                    update={
                        "cache_sha256": digest(
                            provisional.model_dump(mode="json", exclude={"cache_sha256"})
                        )
                    }
                )
            )
        if job.replaces_document_id and job.replaces_document_id != manifest.document_id:
            with knowledge_mutation_lock(self.workspace.root / "knowledge"):
                self.store.renew(job.job_id, token, now=self.clock())
                if not self.store.owns_replacement(job):
                    raise KnowledgeError("REPLACEMENT_STALE")
                old = next(
                    (m for m in self.documents.list() if m.document_id == job.replaces_document_id),
                    None,
                )
                if old is not None:
                    selected = set(self._paths())
                    if old.normalized_relative_path in selected:
                        # Publish both verified entries before replacing the live selection.
                        # A crash before selection still serves old; a crash after serves new.
                        # Queries intersect this generation with the live scope selection.
                        prepared = selected | {manifest.normalized_relative_path}
                        if not self._publish(selected_paths=prepared):
                            raise KnowledgeError("INDEX_INCOMPLETE_MANIFEST")
                        selected.remove(old.normalized_relative_path)
                        selected.add(manifest.normalized_relative_path)
                        self.selection.save(tuple(sorted(selected)))
                    self.documents.retire(old.document_id)
                elif (
                    job.replaces_document_id not in self.documents.retirement().retired_document_ids
                ):
                    raise KnowledgeError("REPLACEMENT_STALE")
        return job.model_copy(
            update={
                "status": "READY",
                "normalized_sha256": manifest.normalized_sha256,
                "updated_at": self.clock(),
                "retry_at": None,
                "error_code": None,
            }
        ).sealed()

    def _document(self, manifest: KnowledgeDocumentManifest) -> KnowledgeDocument:
        owner = self.documents.project_id or self.documents.team_id
        # The caller obtained a verified manifest. Read its one content file directly;
        # re-listing the entire library per document makes a tick quadratic in library size.
        content = _read_bounded(
            self.documents.root / manifest.document_id / "content.md",
            MAX_TEAM_KNOWLEDGE_DOCUMENT_BYTES,
        ).decode("utf-8")
        return KnowledgeDocument(
            document_id=manifest.document_id,
            scope=self.documents.scope,
            team_id=self.documents.team_id,
            project_id=self.documents.project_id,
            title=manifest.source_name,
            source_uri=f"knowledge://{self.documents.scope}/{owner}/{manifest.document_id}",
            document_sha256=manifest.normalized_sha256,
            content=content,
        )

    def _publish(self, *, selected_paths: set[str] | None = None) -> bool:
        with knowledge_mutation_lock(self.workspace.root / "knowledge"):
            return self._publish_locked(selected_paths=selected_paths)

    def _publish_locked(self, *, selected_paths: set[str] | None) -> bool:
        selected = set(self._paths()) if selected_paths is None else selected_paths
        previous = self.store.active()
        previous_keys = {entry.cache_key for entry in previous.documents} if previous else set()
        entries: list[KnowledgeIndexEntry] = []
        for manifest in self.documents.list():
            document = self._document(manifest)
            key = KnowledgeChunkCache.key(document, self.parser_version, self.index_version)
            if self.store.cache(key) is None:
                if key in previous_keys:
                    raise KnowledgeError("INDEX_INCOMPLETE_MANIFEST")
                if previous is not None and (previous.parser_version, previous.index_version) != (
                    self.parser_version,
                    self.index_version,
                ):
                    return False  # A version upgrade must preserve its previous generation.
                # A newly imported source that failed parsing has never entered the trusted
                # index. It must not prevent independently ready documents being published.
                continue
            entries.append(
                KnowledgeIndexEntry(
                    document_id=document.document_id,
                    normalized_sha256=document.document_sha256,
                    cache_key=key,
                    selected=manifest.normalized_relative_path in selected,
                )
            )
        provisional = KnowledgeIndexManifest(
            scope=self.documents.scope,
            team_id=self.documents.team_id,
            project_id=self.documents.project_id,
            parser_version=self.parser_version,
            index_version=self.index_version,
            documents=tuple(sorted(entries, key=lambda e: e.document_id)),
            manifest_sha256="0" * 64,
        )
        self.store.publish(
            provisional.model_copy(
                update={
                    "manifest_sha256": digest(
                        provisional.model_dump(mode="json", exclude={"manifest_sha256"})
                    )
                }
            )
        )

        return True

    def current_documents(self) -> tuple[KnowledgeDocument, ...]:
        """Current scope view excludes retired data even before the next worker tick."""
        with knowledge_mutation_lock(self.workspace.root / "knowledge"):
            return self._current_documents_locked()

    def _current_documents_locked(self) -> tuple[KnowledgeDocument, ...]:
        active = self.store.active()
        if active is None:
            return ()
        current = {manifest.document_id: manifest for manifest in self.documents.list()}
        selected = set(self._paths())
        result: list[KnowledgeDocument] = []
        for entry in active.documents:
            manifest = current.get(entry.document_id)
            if (
                entry.selected
                and manifest is not None
                and manifest.normalized_relative_path in selected
                and manifest.normalized_sha256 == entry.normalized_sha256
            ):
                cache = self.store.cache(entry.cache_key)
                if cache is None:
                    raise KnowledgeError("INDEX_INCOMPLETE_MANIFEST")
                result.append(cache.document)
        return tuple(result)

    def status(self) -> KnowledgeIndexStatus:
        jobs = self.store.jobs()
        pending = tuple(job for job in jobs if job.status in {"QUEUED", "PROCESSING"})
        return KnowledgeIndexStatus(
            scope=self.documents.scope,
            team_id=self.documents.team_id,
            project_id=self.documents.project_id,
            jobs=jobs,
            backlog=len(pending),
            failed=sum(job.status == "FAILED" for job in jobs),
            oldest_pending_seconds=max(
                (max(0.0, (self.clock() - job.created_at).total_seconds()) for job in pending),
                default=0.0,
            ),
            active_manifest=self.store.active(),
        )

    def retry(self, job_id: str) -> KnowledgeIndexJob:
        return self.store.retry(job_id, now=self.clock())


class IndexedKnowledgeRetrieval:
    """Cache acceleration only: the frozen authorized documents remain the authority."""

    def __init__(self, indexes: tuple[KnowledgeIndexer, ...] = ()) -> None:
        self.indexes = indexes

    def _chunks(self, snapshot: KnowledgeSnapshot) -> tuple[KnowledgeChunk, ...]:
        snapshot.validate_integrity()
        result: list[KnowledgeChunk] = []
        for document in snapshot.documents:
            cached: KnowledgeChunkCache | None = None
            for index in self.indexes:
                if (document.scope, document.team_id, document.project_id) != (
                    index.documents.scope,
                    index.documents.team_id,
                    index.documents.project_id,
                ):
                    continue
                cached = index.store.find_cache(
                    document, parser_version=index.parser_version, index_version=index.index_version
                )
                if cached is not None:
                    if (
                        redact_text(cached.document.content).text
                        != redact_text(document.content).text
                    ):
                        raise KnowledgeError("INDEX_DOCUMENT_INTEGRITY")
                    break
            if cached is None:
                result.extend(parse_document(document))
            else:
                result.extend(
                    chunk.model_copy(
                        update={
                            "title": redact_text(document.title).text,
                            "citation": chunk.citation.model_copy(
                                update={"source_uri": document.source_uri}
                            ),
                        }
                    )
                    for chunk in cached.chunks
                )
        return tuple(result)

    def search(
        self, snapshot: KnowledgeSnapshot, query: str, limit: int = 8
    ) -> tuple[KnowledgeHit, ...]:
        return score_chunks(self._chunks(snapshot), query, limit)

    def read(self, snapshot: KnowledgeSnapshot, citation: KnowledgeCitation) -> KnowledgeChunk:
        for chunk in self._chunks(snapshot):
            if chunk.citation == citation:
                return chunk
        raise KnowledgeError("CITATION_NOT_IN_SNAPSHOT")


class KnowledgeIndexWorker:
    """One service-owned daemon; a stop event bounds shutdown waiting."""

    def __init__(self, tick: Callable[[], None], *, interval: float = 2.0) -> None:
        if not 0.1 <= interval <= 60:
            raise ValueError("invalid index interval")
        self.tick = tick
        self.interval = interval
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = Thread(target=self._run, name="knowledge-indexer", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            # Durable job status carries safe errors; never log parser/document payloads.
            with suppress(
                KnowledgeError,
                KnowledgeDocumentError,
                KnowledgeSelectionError,
                OSError,
                ValueError,
            ):
                self.tick()
            self._stop.wait(self.interval)

    def close(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0, timeout))


def retrieval_for_project(project: ProjectWorkspace) -> IndexedKnowledgeRetrieval:
    """Compose the selected Project with its owning Team, without parsing or changing selection."""
    return IndexedKnowledgeRetrieval((KnowledgeIndexer(project.team), KnowledgeIndexer(project)))
