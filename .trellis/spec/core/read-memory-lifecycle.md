# Read-side memory lifecycle

## 1. Scope / trigger

Long-lived Console polling must release completed Project histories. Apply this contract when
changing native acceptance admission, historical design correction, Team snapshots or HTTP read
lifetimes. Read integrity and complete audit history remain mandatory.

## 2. Signatures

```python
native_acceptance_mapping(AcceptanceMappingDraft) -> AcceptanceDesignMapping
unstarted_design_rejection(JointCheckpoint) -> JointDesignVerificationRejected | None
JointJournal.history(delivery_id: str) -> tuple[JointCheckpoint, ...]
_team_snapshot(reader: TeamReader, project_id: str | None, gate: LockType) -> Response
GET /api/v1/team?project_id=project_<id>
```

## 3. Contracts

- In `manager/production_agents.py::native_acceptance_mapping`, classify Pydantic validation
  failure from `ValidationError.errors(include_input=False, include_url=False)`. `ctx.error` is
  local diagnostic data only. A nested `BaseException` must lose `__traceback__`, `__context__`
  and `__cause__` before the safe `AcceptanceVerificationRejected` escapes. Preserve the existing
  criterion ID, code, safe Chinese message and top-level exception chaining. Never log or return
  Pydantic inputs or context objects.
- Pydantic's native validation error may own a validator's Python exception through references
  outside Python GC traversal. Its traceback's `f_back` chain can retain the caller's complete
  Project journal, even after the request returns and `gc.collect()` runs. Dropping only the
  outer traceback, cloning the aggregate error, increasing RAM or forcing GC is insufficient.
- `create_console_app` owns one application-local, nonblocking `threading.Lock` for Team reads,
  shared across Project selections. The actual synchronous worker acquires it and keeps it through
  `reader.snapshot`, `TeamSnapshot.to_wire` and `JSONResponse.render`. Its `finally` releases it
  on success, safe read error or unexpected exception. HTTP cancellation is not worker completion.
- A competing Team GET returns fixed `503 TEAM_READ_IN_PROGRESS` without reading another Project.
  `TeamReadError` retains fixed `503 TEAM_UNAVAILABLE`; unexpected errors keep the ordinary safe
  500 response. Other Console endpoints remain available. Host/origin checks and security headers
  precede/cover admission. Do not queue blocked readers or cache snapshots across requests.
- Continue verifying every historical byte/hash/path, predecessor, ownership and current-scope
  distinction. Never truncate history, remove retired audit records, weaken validation or mutate
  durable delivery facts to reduce memory.

## 4. Validation matrix

| Scenario | Required result |
| --- | --- |
| Valid native mapping | Original typed mapping and validation semantics |
| Invalid historical inspection levels | Original safe rejection; completed caller scope releases |
| Native or joint rejection repeated, then discarded | Weak caller-lifetime references die after GC |
| One Team read held in reader, wire conversion or JSON rendering | Second Project GET returns busy; reader entered once |
| First HTTP caller cancelled while reader still held | Busy admission remains until actual worker finishes |
| Safe or unexpected read failure | Original safe error; next read succeeds |
| Subsequent Project GET | New Project facts, never prior snapshot reuse |
| Invalid origin during held read | 403 without entering reader |
| Real filesystem replay repeated | Bounded traced allocation after release; unchanged file inventory, SQL calls zero |

## 5. Good / base / bad

Good: the original sealed design correction is fully validated on each poll, then its entire
history is released. Base: physical allocator memory can plateau above traced live allocations
after a large read; measure both. Bad: interpret low RSS as low memory ownership while macOS has
compressed/swapped several GiB, or declare a concurrency gate sufficient for serial retention.

## 6. Incremental tests and measurements

`tests/manager/test_verification_memory.py` exercises the actual native and joint admission path
from a caller with a weak lifetime sentinel. The sentinel represents snapshot locals retained by
validator traceback `f_back`, so it need not be passed to the validator. Both cases must fail
without nested-context detachment and pass with it. Retain admission/correction/journal-reuse and
production-Agent behavior regressions.

`tests/web_console/test_transport.py` covers public ASGI concurrent and cancelled callers,
selected Projects, busy/safe/500 errors, origin/security headers, and gates held through wire and
JSON serialization. Cancellation probes must not await middleware's shielded caller until the
blocked synchronous worker is released.

Production diagnosis uses numeric `vmmap -summary` physical footprint (compressed/swapped memory
included) and bounded isolated `tracemalloc` replay. Do not take heap/core content dumps or flood a
pressured production reader. The 2026-10-06 fixture contained 222 JSON records / 250,405,968 bytes:
old serial filesystem replay retained about 449 MB per read; repaired three-round replay retained
272,969 bytes total, with all Journal weak references released and unchanged sources. Physical
footprint after release plateaued at about 0.414 GiB; remaining large single-read peak is distinct
from a leak. Machine-specific footprint thresholds are operational gates, not portable unit tests.

## 7. Wrong / correct

Wrong: normalize a `ValidationError` to safe text while its nested validator exception still owns
the complete read stack; release an async lock when the HTTP caller is cancelled.

Correct: discard nested diagnostic execution frames locally while preserving the safe rejection,
and bind nonblocking admission to the actual worker's read-and-serialize lifetime.

## Existing data, rollback and prevention

No SQL/journal migration is required. The leak is ephemeral diagnostic-object retention; all
Requirement, Task, Operation, approval, candidate and history bytes remain valid. Capture memory
facts, verify Console operations are idle, then use the trusted service script to load the repair.
Refresh the same Project. Restart relieves an already-leaked process but does not itself fix it.
Roll back code while idle and retain every durable fact; regression of this repair restores growth.

The root cause was an implicit assumption that discarded native validation errors were fully
GC-visible. Previous functional tests verified rejection correctness, not completed-caller
lifetime. Prevent recurrence with lifetime tests at the real failing boundary and serial replay
before attributing memory growth to concurrency. No generated spec/template mirror exists here.
