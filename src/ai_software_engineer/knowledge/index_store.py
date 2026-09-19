"""SQLite transactions for source ingestion, fenced jobs and immutable index generations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from ai_software_engineer.knowledge.index_models import (
    KnowledgeChunkCache,
    KnowledgeIndexJob,
    KnowledgeIndexManifest,
)
from ai_software_engineer.knowledge.models import KnowledgeDocument, KnowledgeError


class KnowledgeIndexStore:
    def __init__(
        self, root: Path, *, scope: Literal["team", "project"], team_id: str, project_id: str | None
    ) -> None:
        self.root = root
        self.path = root / "index.sqlite3"
        self.scope = scope
        self.team_id = team_id
        self.project_id = project_id
        self._guard_path()
        root.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS owner (id INTEGER PRIMARY KEY CHECK(id=1),
                    scope TEXT NOT NULL, team_id TEXT NOT NULL, project_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    source BLOB, claim_owner TEXT, claim_until REAL);
                CREATE TABLE IF NOT EXISTS chunks (
                    cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS manifests (
                    digest TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS active (
                    id INTEGER PRIMARY KEY CHECK(id=1), digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS replacements (
                    document_id TEXT PRIMARY KEY, job_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS job_history (
                    job_sha256 TEXT PRIMARY KEY, job_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS job_insert_history AFTER INSERT ON jobs BEGIN
                    INSERT OR IGNORE INTO job_history VALUES (
                        json_extract(NEW.payload,'$.job_sha256'), NEW.job_id, NEW.payload);
                END;
                CREATE TRIGGER IF NOT EXISTS job_update_history
                AFTER UPDATE OF payload ON jobs BEGIN
                    INSERT OR IGNORE INTO job_history VALUES (
                        json_extract(NEW.payload,'$.job_sha256'), NEW.job_id, NEW.payload);
                END;
            """)
            connection.execute(
                "INSERT OR IGNORE INTO owner VALUES (1, ?, ?, ?)",
                (scope, team_id, project_id or ""),
            )
            owner = connection.execute("SELECT scope, team_id, project_id FROM owner").fetchone()
            if owner != (scope, team_id, project_id or ""):
                raise KnowledgeError("INDEX_OWNER_MISMATCH")

    def _guard_path(self) -> None:
        if any(path.is_symlink() for path in (self.path, *self.path.parents)):
            raise KnowledgeError("INDEX_UNSAFE_PATH")
        if any(Path(str(self.path) + suffix).is_symlink() for suffix in ("-wal", "-shm")):
            raise KnowledgeError("INDEX_UNSAFE_PATH")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self._guard_path()
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("PRAGMA synchronous = FULL")
            with connection:
                yield connection
        except sqlite3.Error as error:
            raise KnowledgeError("INDEX_STORE_UNAVAILABLE") from error
        finally:
            connection.close()

    def _job(self, payload: str) -> KnowledgeIndexJob:
        try:
            job = KnowledgeIndexJob.model_validate_json(payload)
            job.validate_integrity()
        except ValueError as error:
            raise KnowledgeError("INDEX_JOB_INTEGRITY") from error
        if (job.scope, job.team_id, job.project_id) != (self.scope, self.team_id, self.project_id):
            raise KnowledgeError("INDEX_OWNER_MISMATCH")
        return job

    def enqueue(self, job: KnowledgeIndexJob, source: bytes | None) -> KnowledgeIndexJob:
        job.validate_integrity()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if job.replaces_document_id is not None:
                previous = connection.execute(
                    "SELECT j.payload FROM replacements r JOIN jobs j ON j.job_id=r.job_id "
                    "WHERE r.document_id=?",
                    (job.replaces_document_id,),
                ).fetchone()
                if previous is not None:
                    previous_job = self._job(str(previous[0]))
                    if previous_job.job_id != job.job_id and previous_job.status != "FAILED":
                        raise KnowledgeError("REPLACEMENT_STALE")
                connection.execute(
                    "INSERT INTO replacements VALUES (?,?) ON CONFLICT(document_id) "
                    "DO UPDATE SET job_id=excluded.job_id",
                    (job.replaces_document_id, job.job_id),
                )
            row = connection.execute(
                "SELECT payload FROM jobs WHERE job_id=?", (job.job_id,)
            ).fetchone()
            if row:
                existing = self._job(str(row[0]))
                if existing.status != "RETIRED":
                    return existing
                restored = existing.model_copy(
                    update={
                        "status": "QUEUED",
                        "attempts": 0,
                        "updated_at": job.updated_at,
                        "retry_at": None,
                        "error_code": None,
                    }
                ).sealed()
                connection.execute(
                    "UPDATE jobs SET payload=?,source=COALESCE(?,source) WHERE job_id=?",
                    (restored.model_dump_json(), source, job.job_id),
                )
                return restored
            count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()
            if count is not None and int(count[0]) >= 4096:
                raise KnowledgeError("INDEX_JOB_CAPACITY")
            connection.execute(
                "INSERT INTO jobs (job_id,payload,source) VALUES (?,?,?)",
                (job.job_id, job.model_dump_json(), source),
            )
        return job

    def owns_replacement(self, job: KnowledgeIndexJob) -> bool:
        if job.replaces_document_id is None:
            return True
        with self.connection() as connection:
            row = connection.execute(
                "SELECT job_id FROM replacements WHERE document_id=?", (job.replaces_document_id,)
            ).fetchone()
        return row is not None and str(row[0]) == job.job_id

    def jobs(self) -> tuple[KnowledgeIndexJob, ...]:
        with self.connection() as connection:
            rows = connection.execute("SELECT payload FROM jobs ORDER BY job_id").fetchall()
        return tuple(
            sorted(
                (self._job(str(row[0])) for row in rows),
                key=lambda job: (job.created_at, job.job_id),
            )
        )

    def history(self, job_id: str) -> tuple[KnowledgeIndexJob, ...]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM job_history WHERE job_id=? ORDER BY rowid", (job_id,)
            ).fetchall()
        return tuple(self._job(str(row[0])) for row in rows)

    def claim(
        self, *, now: datetime, parser_version: str, index_version: str, lease_seconds: float = 300
    ) -> tuple[KnowledgeIndexJob, bytes | None, str] | None:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Source bytes can be large (the upload limit is intentionally generous).  Keep
            # the claim scan bounded to the small typed job payload; fetch one source only
            # after an eligible job has been selected.  A READY/RETIRED row must never pull
            # its BLOB into the worker's memory just because it shares this scope.
            rows = connection.execute(
                "SELECT job_id,payload,claim_until FROM jobs "
                "WHERE json_extract(payload,'$.parser_version')=? "
                "AND json_extract(payload,'$.index_version')=? AND ("
                "json_extract(payload,'$.status')='QUEUED' OR ("
                "json_extract(payload,'$.status')='FAILED' "
                "AND json_extract(payload,'$.attempts')<3 "
                "AND julianday(json_extract(payload,'$.retry_at'))<=julianday(?)) OR ("
                "json_extract(payload,'$.status')='PROCESSING' AND COALESCE(claim_until,0)<=?)) "
                "ORDER BY rowid LIMIT 32",
                (parser_version, index_version, now.isoformat(), now.timestamp()),
            ).fetchall()
            for row in rows:
                job = self._job(str(row[1]))
                if (job.parser_version, job.index_version) != (parser_version, index_version):
                    continue
                expired = job.status == "PROCESSING" and float(row[2] or 0) <= now.timestamp()
                if expired and job.attempts >= 3:
                    exhausted = failed_job(job, "INDEX_INVALID", now)
                    connection.execute(
                        "UPDATE jobs SET payload=?,claim_owner=NULL,claim_until=NULL "
                        "WHERE job_id=?",
                        (exhausted.model_dump_json(), job.job_id),
                    )
                    continue
                eligible = (
                    job.status == "QUEUED"
                    or (
                        job.status == "FAILED"
                        and job.attempts < 3
                        and job.retry_at is not None
                        and job.retry_at <= now
                    )
                    or expired
                )
                if not eligible:
                    continue
                token = uuid4().hex
                claimed = job.model_copy(
                    update={
                        "status": "PROCESSING",
                        "attempts": job.attempts + 1,
                        "updated_at": now,
                        "retry_at": None,
                        "error_code": None,
                    }
                ).sealed()
                connection.execute(
                    "UPDATE jobs SET payload=?,claim_owner=?,claim_until=? WHERE job_id=?",
                    (claimed.model_dump_json(), token, now.timestamp() + lease_seconds, job.job_id),
                )
                source_row = connection.execute(
                    "SELECT source FROM jobs WHERE job_id=?", (job.job_id,)
                ).fetchone()
                source = source_row[0] if source_row is not None else None
                if source is not None and not isinstance(source, bytes):
                    raise KnowledgeError("INDEX_SOURCE_INTEGRITY")
                return claimed, source, token
        return None

    def finish(self, job: KnowledgeIndexJob, token: str, *, now: datetime) -> None:
        job.validate_integrity()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute(
                "UPDATE jobs SET payload=?,claim_owner=NULL,claim_until=NULL "
                "WHERE job_id=? AND claim_owner=? AND claim_until>?",
                (job.model_dump_json(), job.job_id, token, now.timestamp()),
            )
            if result.rowcount != 1:
                raise KnowledgeError("INDEX_CLAIM_LOST")

    def renew(self, job_id: str, token: str, *, now: datetime) -> None:
        """Reject an expired owner before it can update current-library selection/retirement."""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                "UPDATE jobs SET claim_until=? WHERE job_id=? AND claim_owner=? AND claim_until>?",
                (now.timestamp() + 300, job_id, token, now.timestamp()),
            )
            if updated.rowcount != 1:
                raise KnowledgeError("INDEX_CLAIM_LOST")

    def retry(self, job_id: str, *, now: datetime) -> KnowledgeIndexJob:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise KnowledgeError("INDEX_JOB_NOT_FOUND")
            job = self._job(str(row[0]))
            if job.status != "FAILED":
                raise KnowledgeError("INDEX_RETRY_REQUIRES_FAILED")
            retried = job.model_copy(
                update={
                    "status": "QUEUED",
                    "attempts": 0,
                    "updated_at": now,
                    "retry_at": None,
                    "error_code": None,
                }
            ).sealed()
            connection.execute(
                "UPDATE jobs SET payload=? WHERE job_id=?", (retried.model_dump_json(), job_id)
            )
        return retried

    def retire(self, active_ids: set[str], *, now: datetime) -> None:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT payload FROM jobs").fetchall()
            for row in rows:
                job = self._job(str(row[0]))
                if job.status == "READY" and job.document_id not in active_ids:
                    retired = job.model_copy(
                        update={"status": "RETIRED", "updated_at": now}
                    ).sealed()
                    connection.execute(
                        "UPDATE jobs SET payload=? WHERE job_id=?",
                        (retired.model_dump_json(), job.job_id),
                    )

    def cache(self, cache_key: str) -> KnowledgeChunkCache | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM chunks WHERE cache_key=?", (cache_key,)
            ).fetchone()
        if row is None:
            return None
        try:
            cached = KnowledgeChunkCache.model_validate_json(str(row[0]))
            cached.validate_integrity()
        except ValueError as error:
            raise KnowledgeError("INDEX_CACHE_INTEGRITY") from error
        if cached.cache_key != cache_key or (
            cached.document.scope,
            cached.document.team_id,
            cached.document.project_id,
        ) != (self.scope, self.team_id, self.project_id):
            raise KnowledgeError("INDEX_OWNER_MISMATCH")
        return cached

    def put_cache(self, cached: KnowledgeChunkCache) -> None:
        cached.validate_integrity()
        if (cached.document.scope, cached.document.team_id, cached.document.project_id) != (
            self.scope,
            self.team_id,
            self.project_id,
        ):
            raise KnowledgeError("INDEX_OWNER_MISMATCH")
        existing = self.cache(cached.cache_key)
        if existing is not None and existing != cached:
            raise KnowledgeError("INDEX_CACHE_CONFLICT")
        with self.connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO chunks VALUES (?,?)",
                (cached.cache_key, cached.model_dump_json()),
            )

    def find_cache(
        self, document: KnowledgeDocument, *, parser_version: str, index_version: str
    ) -> KnowledgeChunkCache | None:
        if (document.scope, document.team_id, document.project_id) != (
            self.scope,
            self.team_id,
            self.project_id,
        ):
            raise KnowledgeError("INDEX_OWNER_MISMATCH")
        with self.connection() as connection:
            row = connection.execute(
                "SELECT cache_key FROM chunks "
                "WHERE json_extract(payload,'$.document.document_id')=? "
                "AND json_extract(payload,'$.document.document_sha256')=? "
                "AND json_extract(payload,'$.parser_version')=? "
                "AND json_extract(payload,'$.index_version')=? ORDER BY cache_key LIMIT 1",
                (document.document_id, document.document_sha256, parser_version, index_version),
            ).fetchone()
        return self.cache(str(row[0])) if row is not None else None

    def active(self) -> KnowledgeIndexManifest | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT a.digest,m.payload FROM active a "
                "LEFT JOIN manifests m ON m.digest=a.digest WHERE a.id=1"
            ).fetchone()
        if row is None:
            return None
        if row[1] is None:
            raise KnowledgeError("INDEX_MANIFEST_MISSING")
        try:
            manifest = KnowledgeIndexManifest.model_validate_json(str(row[1]))
            manifest.validate_integrity()
        except ValueError as error:
            raise KnowledgeError("INDEX_MANIFEST_INTEGRITY") from error
        if (manifest.scope, manifest.team_id, manifest.project_id) != (
            self.scope,
            self.team_id,
            self.project_id,
        ):
            raise KnowledgeError("INDEX_OWNER_MISMATCH")
        if manifest.manifest_sha256 != str(row[0]):
            raise KnowledgeError("INDEX_MANIFEST_INTEGRITY")
        return manifest

    def publish(self, manifest: KnowledgeIndexManifest) -> None:
        manifest.validate_integrity()
        if (manifest.scope, manifest.team_id, manifest.project_id) != (
            self.scope,
            self.team_id,
            self.project_id,
        ):
            raise KnowledgeError("INDEX_OWNER_MISMATCH")
        for entry in manifest.documents:
            cached = self.cache(entry.cache_key)
            if cached is None or (cached.document.document_id, cached.document.document_sha256) != (
                entry.document_id,
                entry.normalized_sha256,
            ):
                raise KnowledgeError("INDEX_INCOMPLETE_MANIFEST")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO manifests VALUES (?,?)",
                (manifest.manifest_sha256, manifest.model_dump_json()),
            )
            connection.execute(
                "INSERT INTO active VALUES (1,?) "
                "ON CONFLICT(id) DO UPDATE SET digest=excluded.digest",
                (manifest.manifest_sha256,),
            )


def failed_job(
    job: KnowledgeIndexJob,
    code: Literal["DOCUMENT_INVALID", "INDEX_INVALID", "REPLACEMENT_STALE"],
    now: datetime | None = None,
) -> KnowledgeIndexJob:
    timestamp = now or datetime.now(UTC)
    return job.model_copy(
        update={
            "status": "FAILED",
            "error_code": code,
            "updated_at": timestamp,
            "retry_at": timestamp + timedelta(seconds=min(300, 5 * 2 ** min(job.attempts, 6))),
        }
    ).sealed()
