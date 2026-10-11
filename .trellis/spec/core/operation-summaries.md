# Bounded Operation Summary Reads

## Scope / signatures
`FileConsoleOperationStore.summary_page(query: OperationSummaryQuery) -> OperationSummaryPage`
`GET /api/v1/operation-summaries?project_id=...&delivery_id=...&page_size=25&cursor=...`

## Contracts
Version `v0.1` is advertised through `operation_summary_contract_version`. The endpoint is read-only. Full GET/mutation/claim retain their previous contracts. Summaries never contain intent, complete result, patch, plan, approval body or READY authority. Short texts are reading projections, not approval facts.

Every request hashes all complete numbered JSON bytes under shared flock and validates regular files, no symlink, and the 16 MiB per-record boundary. A changed/missing cache entry executes ordinary complete typed/digest/predecessor replay. Only exactly unchanged operation inventory reuses a reading projection. Cache retains at most 512 entries / 2 MiB serialized projection+inventory identities; eviction only increases work. No mtime shortcuts. Cross-request reuse is exclusively this bounded read-side protocol and never applies to gates or complete reads.

Page size defaults to 25 and is capped at 50. Sort is requested_at then operation_id descending. Scope combines optional project_id/delivery_id; delivery filter requires project. Cursor binds exact inventory, scope, page size and sort; drift returns 409 OPERATION_CURSOR_STALE. All scoped active summaries are included regardless of page; >64 is unavailable, never silently incomplete. Page serialized bytes are limited to 256 KiB. Every ETag/304 requires a fresh complete inventory read. Invalid query returns fixed 400; corrupted state/cache overflow active/page returns fixed 503. No raw validation input leaks.

## Validation matrix / tests
Good: complete history paginates without omission, old active work outside first page stays visible. Base: cache overflow rereads full uncached operations. Bad: same size/mtime history mutation must invalidate/reject; missing history/symlink/hash/scope/cursor drift cannot return 304. Tests must assert bounded cached bytes/entries, no retained complete models, old wire unchanged, no write/claim calls, proper 304 and fixed failure envelopes.

## Existing data / rollback
No persisted fact is rewritten. Existing operation history remains complete and directly readable. Load code at idle controlled restart; refresh the same project. Rollback removes only this read protocol/cache and restores old polling costs.

## Wire fields and exact-detail separation

Production plumbing is `ProjectConsole.summary_page` → `ConsoleOperationStore.summary_page`;
transport capability is optional `_OperationSummaryReader`, so setup/legacy consoles do not advertise
an unsupported endpoint. HTTP query rejects unknown and duplicated keys. Four static contracts are
`schemas/console-operation-{summary,page,cursor,query}.schema.json`; they exactly match strict
Pydantic models in `src/ai_software_engineer/web_console/summary_models.py`.

Page JSON explicitly includes null optional fields:

```json
{
  "schema_version": "v0.1", "team_id": "team_test",
  "scope": {"project_id": "project_alpha", "delivery_id": null},
  "inventory_sha256": "<64 lowercase hex>", "items": [],
  "next_cursor": null, "total_count": 0, "active": [], "active_complete": true
}
```

Each summary exposes `operation_id`, `team_id`, `project_id`, `delivery_id`, `action`, `status`,
`sequence`, `requested_at`, `updated_at`, `operation_sha256`, `error_code`, `error_summary`,
`result_stage`, `next_step`, `summary`, `approval_kind` and `has_details=true`. Stage is at most
128 characters; reading texts at most 512, with an explicit ellipsis when shortened. Full reasons
remain in single-operation GET. Scope identity uses submitted Project/Requirement. Only
CREATE_PROJECT and CREATE_REQUIREMENT may supply a newly created identity from their result.
Foreign Project and Team still reject before filtering; a different delivery in the same
Project is an independently scoped historical result, not evidence of parent/child membership.

`result_scope_relation` is a typed enum: `NO_RESULT`, `SAME_RESOURCE`,
`CREATED_RESOURCE`, `NO_RESOURCE`, `UNVERIFIED_RESOURCE`. Independent
`result_project_id`/`result_delivery_id` retain exact result locators. A delivery-bound
DELETE_REQUIREMENT returning no delivery is the known `NO_RESOURCE` producer;
any other delivery-bound result lacking its resource is `UNVERIFIED_RESOURCE`.
Both relations retain neutral intent/command metadata but publish no result stage,
checkpoint, approval, result-derived task/work, baseline, diagnostic or next-step
semantics. Full GET remains complete and immutable for explicitly scoped audit.
The additive reading fields keep `v0.1`: new clients independently scope complete
records from their real intent/result; absent fields from old summary servers cannot
authorize an unrelated full result. Full Operation schema and hash chain are unchanged.

| Scope scenario | Summary and client behavior |
| --- | --- |
| Good: actual DELETE producer, result delivery absent | owner remains intent; NO_RESOURCE, HTTP 200/304; neutral command-only history |
| Good: CREATE has no new submitted identity | CREATED_RESOURCE uses the actual result identity; scoped full hydration matches |
| Base: same resource or older server without additive locators | normal full detail and approvals still require exact result/checkpoint and fresh gates |
| Bad: same Project different or missing non-DELETE delivery result | UNVERIFIED_RESOURCE, no result semantic locators/current authority; explicit separate historical audit |
| Bad: foreign Project/Team, broken bytes/digest/predecessor | whole read fails closed even for another filter; no 304 or partially omitted history |

Regression assertions live in `tests/web_console/test_operation_summaries.py` and
`tests/team_view/{operation-summary-reading,recovery-progress-summary}.test.cjs`.
The real deletion result must originate from ManagerConsoleAdapter, pass the actual
FileConsoleOperationStore hash-chain replay and HTTP endpoint, and preserve complete
GET/files. Hydration and historical rendering tests execute the shipped app.js.

Bounded locator fields `result_checkpoint_sha256`, `intent_checkpoint_sha256`,
`submitted_approval_sha256`, `submitted_approval_kind` (plan/scope/repair), `intent_plan_sha256`,
`approval_plan_sha256`, `baseline_plan_sha256`, `baseline_purpose`, `has_baseline_binding`, `task_id`
and `work_item_id` permit choosing which single full record to read. They never grant authority,
prove current readiness, or replace a current full-record/checkpoint/plan validation. Work identity
comes from explicit intent then typed result facts; opaque legacy work IDs exceeding the 128-character
locator budget are absent, never truncated into a different identity. The original complete record
is unchanged.

Cursor is a canonical bounded URL-safe base64 encoding of the typed Cursor JSON: exact inventory,
filter scope, page size, fixed sort and exact last timestamp/ID. It is a read position, not a signed
command token. Its anchor must exist in the verified current scope. Global inventory changes even
outside a selected filter invalidate old pages conservatively. `ETag` hashes the exact page JSON;
`If-None-Match` equality can return 304 only after all bytes have been rechecked and a full bounded
current page safely computed. No ordinary browser HTTP cache can skip these checks.

| Condition | HTTP / action |
| --- | --- |
| Valid first/read-next page | 200, bounded typed page, ETag |
| Exact unchanged page and matching ETag | 304, no body, after complete inventory recheck |
| Invalid/duplicate/unknown query, noncanonical cursor | 400 `OPERATION_SUMMARY_QUERY_INVALID` |
| Inventory/filter/page-size/anchor drift | 409 `OPERATION_CURSOR_STALE`, rebuild latest first page |
| Foreign/malformed/oversized/symlink/hash/chain history | 503 `OPERATION_STATE_INVALID`, no partial page or 304 |
| More than 64 active or 256 KiB page | Same fixed 503, never truncate current execution facts |
| Cache entry/serialized-byte capacity | Complete uncached replay and complete pagination |
| Server lacks capability | 404 `NOT_AVAILABLE`, no manifest feature |

## Incremental verification and measured work

`tests/web_console/test_operation_summaries.py` covers complete stable pagination, equal-time ordering,
created result scope, old active work beyond page, same-size/mtime HTTP ETag tampering, broken prefix,
symlinks/oversize/new file/new operation, failed replay, foreign Team/result scope, exact cursor drift,
512-entry overflow and separate byte cap, generated Schema equality and actual wire validation, old
GET/claim still rejecting corruption, and full large Plan weak-reference release. Existing
`test_transport.py`, `test_core.py`, `test_idle_replay.py`, `test_operation_budget.py`,
`test_scope_contract.py` remain incremental compatibility gates. No full suite or production service
operation is needed to prove this read protocol.

Sequential private-copy probe of the existing 327 Operations /981 numbered files /28,380,820 bytes
on 2026-10-12: cold summary CPU1.676s /wall1.739s, 327 full decodes; 25-entry response33,802 bytes.
Fifty warm reads CPU mean0.156s (max0.187s), wall mean0.168s, zero full Operation decodes. All 981
complete file bytes are still read/hashed per request. Cache retains327 projections /452,021
serialized bytes. All read full Operation weak references released; full Operation and full
ExecutionBaselinePlan live-object counts remain zero at all six post-GC samples. RSS varied
258–298MB and ended at a stable298MB; this bounded test does not establish hours-long leak absence.
Old complete-list response in the same prior private fixture was25,028,308 bytes /CPU1.347s.
Cold reads can be slower due to extra inventory checks; steady-state polling is the intended gain.
The inventory/weakref/work-count assertions are stable contracts; latency/RSS are input/machine-specific.


## Wrong vs correct

Wrong: reuse a complete READY/approved Operation on mtime equality and send it back as current execution
authority. Correct: rehash every historical byte and path, reuse only the immutable bounded summary when
its full byte inventory is identical, then independently GET and revalidate complete current facts before
any execution/approval.
