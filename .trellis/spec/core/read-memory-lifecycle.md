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

## Snapshot-local history reuse (2026-10-09)

### Scope and signatures

Apply when a Team read projects retired Requirements, historical native Tasks and independent
verification reservations. A five-second poll must not re-read the same large history separately
for retirement validation, presentation, ownership and Project counts.

```python
RequirementCheckpointReader.current(delivery_id: str) -> JointCheckpoint | None
RequirementRetirementStore.retired_delivery_ids(reader: RequirementCheckpointReader) -> frozenset[str]
_JointHistorySnapshot.history(delivery_id: str) -> tuple[JointCheckpoint, ...]
_EvaluationEventCache.events(root: Path) -> tuple[EvaluationEvent, ...]
_TaskReadSnapshot.read(native: _Native, base: TaskView,
                       *, dispatch_override: DeliveryAllocation | None = None) -> TaskView
```

### Contracts

- `ProductionTeamReader._snapshot` owns a fresh `_JointHistorySnapshot`. Its first read of each
  Requirement uses the ordinary read-only `JointJournal.history` and validates every historical
  byte, digest, path, filename, predecessor and schema. Retirement validation and ownership consume
  that exact complete prefix; the selected Project count reuses its captured directory inventory
  and validated retirement set. Other Project counts retain isolated ownership validation and
  reuse any shared replacement history only within that Project's count read.
- Reuse never weakens `JointJournal`'s public contract. Independent `current`/`history` calls still
  re-read bytes and return private deep copies; a caller's nested dictionary edits cannot poison
  the journal's verification cache. The private captured models are inspected without mutation.
- `_EvaluationEventCache` captures and fully validates every event in a sidecar once. Each Task
  still selects only its own events at or before its durable `updated_at`; unrelated/future events
  cannot become its Run evidence. New publications enter the next Team snapshot.
- `_TaskReadSnapshot` owns one read-only SQL cursor. Reuse requires an exact sidecar, Team,
  checkpoint digest, intake digest, complete presentation-base digest and optional successor
  dispatch digest. A verification source can reuse its already validated native Task projection;
  different Tasks, scopes, checkpoints or dispatches cannot inherit that result. Candidate
  verification lineage and independent completion validation remain unchanged.
- All three helpers are local to one snapshot. Success/failure releases them with the worker's
  read scope; no application-global or reader-instance snapshot cache is introduced. The next
  poll observes append-only tails and rechecks historical corruption and symlinks. Complete
  Requirement, Task, QA/Review and handling histories remain visible and unchanged.

### Validation and test points

| Case | Expected result |
| --- | --- |
| Retired history and replacement used by retirement, display and count | Each complete history read once in that snapshot |
| Multiple retired entries reference one other-Project replacement | One validated replacement read, correct isolated counts |
| Requirement published after selected directory capture | Absent from this read/count; visible together on the next poll |
| Subsequent snapshot after append | New checkpoint and action visible |
| Historical body/digest/path/ancestor or retirement tampered; replacement missing | Entire snapshot fails closed |
| Evaluation ledger projected for several historical Tasks | Each event decoded once; per-Task/time filtering preserved |
| Later evaluation publication or historical tampering | Next cache sees new facts or rejects corruption |
| Same native projection referenced by independent verification | Exact reuse; changed scope/checkpoint gets a fresh projection |

Regression tests are `tests/team_view/test_joint_history_snapshot.py`,
`tests/team_view/test_task_read_snapshot.py`, related non-MySQL live reader/retirement/design-budget
cases, and existing `tests/manager/test_joint_journal_read_reuse.py`. Real performance measurement
must run sequentially: concurrent full Project hashing or HTTP reads invalidate a latency comparison.
The measured production histories contain 225 numbered JSON records / 253,531,912 bytes; the old
successful snapshot read them 557 times in total / 623,760,450 bytes. After snapshot-local capture,
each history is read once. Evaluation event reads fall from 8,028 to 223 and native Task projection
calls from 37 to 26. These are concrete work counts, not portable latency thresholds.

### Existing data and rollback

No migration, SQL write, history truncation, approval or execution restart is needed. The optimization
only removes repeated work while reading unchanged facts. Users refresh the same Project after an
idle controlled service restart loads the repaired code. Rollback restores the previous reader and
its repeated read cost; all durable records and user decisions remain untouched.
