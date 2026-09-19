# Incremental knowledge indexing (T049)

## Scope and signatures

Applies to `knowledge/index*.py`, the Web Console knowledge upload and index management APIs.
`KnowledgeIndexer` is a deterministic application service; it has no Agent, Task, approval, model
or executable Spec authority. Team and Project each own `knowledge/index/index.sqlite3`.

```python
KnowledgeIndexer(workspace, *, parser_version="markdown-v1", index_version="lexical-v1")
KnowledgeIndexer.enqueue(filename, content, replaces_document_id=None) -> KnowledgeIndexJob
KnowledgeIndexer.tick(*, limit=4) -> tuple[KnowledgeIndexJob, ...]
KnowledgeIndexer.status() -> KnowledgeIndexStatus
KnowledgeIndexer.retry(job_id) -> KnowledgeIndexJob
IndexedKnowledgeRetrieval(indexes).search(snapshot, query, *, limit=8)
IndexedKnowledgeRetrieval(indexes).read(snapshot, citation)
retrieval_for_project(project) -> IndexedKnowledgeRetrieval
```

## Contracts

- Upload validates a safe basename and bounded source bytes, then commits the source and a typed,
  owner-bound job in one SQLite transaction. HTTP returns 202 without PDF/DOCX extraction.
- Jobs are `QUEUED/PROCESSING/READY/FAILED/RETIRED`; deterministic IDs bind owner, source digest,
  parser format (filename suffix), replacement identity and parser/index version. SQLite
  `BEGIN IMMEDIATE` claims with an owner token
  and expiry; stale workers cannot publish a result. Batches and retries are bounded.
  Jobs and source bytes commit together; every state update also appends immutable digest-addressed
  `job_history` within the same transaction. Explicit retries retain earlier failed attempts.
  Per-scope jobs are capped at 4,096; automatic claims stop after three attempts, including crashes.
  Claim scans select at most 32 eligible metadata records, never source BLOBs; only the chosen
  job's source is fetched by exact job ID inside the claim transaction. Completed history therefore
  cannot multiply the 10 MB upload allowance into worker resident memory.
- Workers normalize with the existing document store and verify its manifest/content before parsing.
  Exact document replay checks immutable existing data before extraction. Cached chunks bind document
  identity, normalized digest, owner/source metadata, parser and index versions; unchanged documents
  are not parsed again. Descriptive chunks never become executable Specs.
- Immutable complete verified manifests and the active pointer publish in one database transaction.
  Sources that have never acquired a verified cache are omitted until ready; a failed unrelated import
  cannot block already verified documents or a valid replacement. Missing/corrupt caches previously
  published as trusted fail closed. An incomplete parser/index version upgrade keeps the old generation.
  A failed selected replacement preserves the old selection and document. Retirement filters current queries immediately;
  immutable old documents/chunks remain available only through exact frozen historical snapshots.
  `current_documents()` intersects the published manifest's selected entries with the current live
  selection and active document inventory. Deselection excludes content even before the next tick.
- A replacement is published only after its normalization and chunk construction succeed. Its selected
  state transfers from the old document; old immutable files remain. Competing replacements of an
  already retired document fail closed. Selection-only changes reuse the same chunks.
  Before transferring a selected replacement, publish a generation containing both verified old/new
  entries; live selection still authorizes only the old entry. Then transfer the selection and retire
  the old document. A crash before selection keeps old available; a crash after selection serves new.
  Publication failure cannot retire old. Current reads take the same scope lock around this sequence.
  A durable replacement fence permits one pending replacement per old document. A failed replacement
  may be superseded by a new upload, but its prior worker can no longer apply that replacement.
- `knowledge_mutation_lock(knowledge_root)` serializes read-modify-write across scope-local Console
  selection/replace/delete, index replacement, and document retirement/restore. It uses a regular,
  no-follow `mutation.lock` and `flock`; same-thread nested stores reuse the held lock. Explicit
  selection ID validation runs inside the lock. An overlapping user deselection cannot be overwritten
  by an index worker's earlier selection snapshot, and two retirements cannot lose either ID.
- The retrieval adapter uses exact frozen `KnowledgeSnapshot` documents, not the current catalog.
  Cached payloads are typed and digest checked. Legacy/non-imported snapshot documents may use the
  same deterministic parser; the authorization/evidence registry remains unchanged.
  Cache lookup binds exact owner, document ID, original digest and parser/index versions. Since frozen
  contexts may have redacted text and heading-based titles, verify redacted content equivalence then
  rebind title and source URI to the frozen document. No current catalog broadens the frozen scope.
- Loopback management exposes per-scope jobs, backlog, oldest pending age, stable error codes and
  explicit retries. Worker lifecycle belongs to the Web application, never the read-only renderer.
  Every Team/Project worker tick isolates scope failures; a corrupt Team index or one failed Project
  does not starve the remaining Projects. Missing/unprepared Team is a setup condition, not a delivery failure. No secrets/raw parser errors
  are returned. The existing synchronous document-store seam remains for trusted internal workflows.

## Validation matrix and tests

| Input / event | Expected result |
| --- | --- |
| Valid upload, parser not yet called | durable QUEUED job and 202 |
| Same bytes/version/owner twice | exact job replay, one parse |
| Same bytes first uploaded as PDF then corrected to Markdown | distinct parser-format job; failed PDF cannot poison the Markdown import |
| Failed extraction or parse | FAILED with safe code, previous active digest unchanged |
| Expired PROCESSING lease | reclaim; stale owner publication rejected |
| New parser/index version | explicit new jobs; unchanged version reuses cached chunks |
| Selection changed | new atomic manifest, no repeated parse |
| Selected document disabled | immediate exclusion from current view; historical snapshot remains readable |
| Retired document | absent from future selection/query; frozen historical read remains valid |
| Project B cache presented to Project A | reject owner mismatch |
| Chunk/job/manifest digest drift | fail closed |
| Old selected A, unrelated failed B, ready replacement C | C becomes queryable; B cannot strand retired A's prior pointer |
| Replacement publication fails | A remains selected, active and readable |
| User deselect races a selected replacement | serialized selection remains empty after the deselection completes |
| Two retirement RMW operations overlap | both retired IDs persist |
| Team/one Project index fails | healthy Project jobs still advance in the same tick |
| Ready source history plus one pending job | metadata scan is bounded; only the chosen source is read |

`tests/knowledge/test_index.py` covers lifecycle, failure/retry, concurrency/restart, scope isolation,
version changes, atomic publication and retrieval parity. Web tests cover 202/status/retry and the
UI contract. Good: upload, observe QUEUED, worker publishes READY, select for new requirements.
Base: an empty library publishes an empty manifest. Bad: parse a PDF inside the upload handler,
query another Project's current library, or discard historical bytes during retirement.

## Operations and existing data

`GET /api/v1/admin/team/knowledge/index` and
`GET /api/v1/admin/projects/<project_id>/knowledge/index` return typed status. POST the matching
`/index/<job_id>/retry` to retry a failed job (202). Knowledge upload/replacement now returns a
`KnowledgeIndexJob` (202), not a ready document manifest; clients must wait for READY before enabling
the new document. The browser exposes queue state, failure text and retry and refreshes every 5 s.
The application-owned worker runs every 2 s, handles at most four jobs per scope per tick, and holds
a nonblocking process lock while processing. Claims expire after 300 s. Shutdown waits at most 5 s;
interrupted jobs retain source bytes and resume after their claim expires.

On startup each known scope reconciles existing verified document manifests and queues only missing
versioned work. Existing selection, Requirement approvals and frozen contexts remain untouched.
Failed jobs show a bounded stable error; fix the source by a new upload or explicitly retry from the
management page. Automatic retries stop after three attempts. A stopped process resumes pending or
expired claims on startup. Rollback may stop the index worker and return retrieval to the baseline
adapter; preserve the external index database and immutable documents for audit/replay.

### Resume findings (2026-09-19)

No production facts or approved Requirement snapshots were modified during these fixes. Existing
index databases need no direct SQL repair: after deploying the fixed worker, the next tick rebuilds
the active manifest from verified caches and live selection, including a READY replacement previously
stranded by an unrelated failed import. Preserve the failed job/history for diagnosis; retry that
job through the management endpoint after correcting its source. If an earlier selection race already
changed a user's intended selection, the user explicitly saves the desired Team/Project selection
again; the worker cannot infer that intent or silently widen it. No Task/Operation/approval is reset.
