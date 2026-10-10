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

## Diagnostic boundary: baseline capture replay and idle operations (2026-10-09)

After rescue/baseline records are published, include `engineering_history`,
`FileExecutionBaselineStore.bindings_for_task/plan/required_context` and recursive capture
validation in the read performance probe. Journal/evaluation reuse alone does not bound this
cost. Measure SQL execute time separately, and do not sum nested profiler cumulative times.
Also inspect idle `ProjectConsole._run → claim_next → _list_current`: a short wait interval
does not bound a full-history scan containing large nested plans. A Team busy admission response
is not a MySQL connection error, and low RSS alone is not proof of no memory pressure.

The actual 2026-10-09 diagnosis, measurements, limits and diagnosis-stage follow-up proposals are
recorded in [`docs/archive/2026-10-09-console-slow-read-diagnosis.md`](../../../docs/archive/2026-10-09-console-slow-read-diagnosis.md).
This records diagnostic knowledge only; it does not authorize caching across reads, skipping
secret/integrity validation, rewriting history, changing dispatch, or restoring delivery work.

## Bounded source-inspection reuse and idle dispatch (2026-10-09)

### Scope and signatures

Apply to repeated recursive capture validation in one synchronous Team/engineering/Operation read,
and the existing idle Console dispatch loop. No Schema, SQL, stage or approval changes.

```python
redaction.source_inspection_scope() -> Iterator[None]  # context manager
redact_text(content: str) -> RedactedText
source_secret_occurrences(content: str, *, source_path: str | None = None)
    -> tuple[RedactionOccurrence, ...]
patch_secret_occurrences(content: str) -> tuple[RedactionOccurrence, ...]
ProductionTeamReader.snapshot(project_id: str | None = None) -> TeamSnapshot
engineering_history(sidecar: Path, task: Task, scope: EngineeringScope,
                    requirement_id: str) -> tuple[TimelineEntry, ...]
FileConsoleOperationStore._operation_inventory_sha256() -> str
FileConsoleOperationStore.claim_next(*, at: datetime) -> ConsoleOperation | None
```

### Contracts

- `source_inspection_scope` owns a ContextVar cache of pure immutable detection tuples, keyed by
  exact `(source|patch, source_path|None, complete_text)`. Text equality, not a digest alone,
  selects reuse. Source and patch are separate namespaces; language/path cannot borrow another
  entry's exception. Both safe and sensitive results retain the original conservative semantics.
  AST/token rules and strong credential detection are unchanged.
- Generic `redact_text(content: str) -> RedactedText` may reuse only its own zero-occurrence fact,
  keyed by `(generic, actual_immutable_pattern_tuple, complete_text)`. The tuple includes kind,
  compiled pattern definitions/flags and order; changing any of those requires a fresh scan.
  Python's immutable compiled-pattern equality may reuse semantically identical replacement
  objects; a mere change of object identity does not imply different rules.
  Generic mode cannot borrow a source/patch language exception. A hit creates a fresh
  `RedactedText(content, ())`; never cache `RedactedText`, explicit-secret processing or a generic
  input that produced any occurrence. All matching input still follows the original replacements
  and counts on every call. Existing source/patch sensitive facts retain their prior semantics.
- At most 512 entries / 16 MiB of UTF-8 key text including paths are admitted. An over-bound or
  non-UTF-8 key is simply not memoized: always return the actual scanner result. Reject oversized
  keys by character lower bound before allocating their UTF-8 encoding. Complete original keys
  stay only in this bounded memory scope; never log, return or persist them. Entry count bounds
  object overhead; the byte limit is key content, not a claim about total Python heap size.
  Generic, source and patch share these limits. The generic key references the immutable rules
  tuple without copying its regex text; the payload byte limit counts complete input and source
  paths. During a source/patch cache-miss scan, an internal nested depth guard disables generic
  memo reads/writes: all original regex scans execute, and the parent source/patch fact retains
  its existing admission priority. `finally` restores the depth on success or exception without
  clearing the outer cache or creating another scope. Independently seeded generic entries are
  opportunistic: a source/patch admission may evict only generic entries when necessary to retain
  its original capacity. First reject an individually oversized/non-UTF-8 key; then require that
  evicting generic entries can actually fit the target alongside all retained source/patch facts.
  A per-entry UTF-8 payload-size ledger allows exact byte subtraction without reencoding removed
  text. Never evict source/patch facts or expand either limit. An evicted or denied generic fact
  simply rescans its complete input next time; a fact denied capacity is never assumed clean.
- Team snapshot, direct engineering history and Operation list/current reads enter the scope.
  Nested synchronous reads share it; success and exception reset it in `finally`. Independent
  threads and subsequent polls get fresh scopes. Do not carry it across async work or a worker's
  lifetime. Domain models, digests, source bytes, path policy, ownership, exact approvals and
  predecessor chains are still validated; no successful approval or snapshot is cached here.
- In one `engineering_history`, call `bindings_for_task(task.id)` once and reuse that complete
  local tuple for timeline and lookup. Every plan/capture still follows the original store checks.
- `claim_next` retains the existing exclusive flock. Every idle invocation checks all matching
  operation directories and every complete JSON byte through the regular/no-symlink/16 MiB reader.
  Its inventory digest includes ordered directory/file names and content hashes, not mtime/inode.
  Only an identical inventory previously fully replayed with **no QUEUED Operation** can skip
  model replay and return `None`. Before remembering that conclusion, reread the inventory and
  require it to equal the pre-replay inventory. A change invokes ordinary full `_list_current`
  decoding and integrity/sequence/successor checks. `_append` invalidates the idle digest.
  New processes do a full first replay; public list/get always fully validate the current history.
  No durable index, cached model, queued-work decision or second dispatch path is introduced.

### Validation matrix / required regressions

| Scenario | Result and assertion |
| --- | --- |
| Same complete source/patch in nested read | Expensive parser runs once; next scope runs again |
| Same clean generic body and rules in nested read | Six regex substitutions once; next scope scans again |
| Generic rule definition/flags/kind/order or complete text changes | Full generic scan; no inherited clean result |
| Source/patch exemption then generic scan | Generic still redacts its own supported secret shapes |
| Generic match, overflow or non-UTF-8 body | Preserve original text/count semantics; do not memoize input |
| Source/patch internal generic scan, including failure | No generic cache read/write; parent fact priority and depth finally restored |
| Source/patch needs shared entry/byte capacity | Reclaim only necessary generic clean facts; exact bytes remain within both caps |
| Target exceeds total cap, cannot encode or cannot fit retained source/patch | No eviction; original scanner result returned |
| Changed text/path, unknown language or patch-lookalike source path | No borrowed exemption; secrets still detected |
| Sensitive result already cached | Same immutable rejection facts, not an empty safe tuple |
| Entry/byte limit or non-UTF-8 key | No new detector semantics or skipped validation |
| Exception / independent read thread | Scope reset / isolated fresh checks |
| Existing baseline starts/bindings | One bindings read; complete unchanged timeline and source files |
| Repeated idle claim, all terminal | One model replay; complete bytes checked every time; no writes |
| External store submits new queued work | Next claim discovers it; existing lock still prevents double claim |
| Historical same-size/same-mtime corruption or broken parent | Full validation rejects; never inherit idle conclusion |
| Same-body symlink or path substitution | Original path/regular-file checks reject |
| Public list after an idle hit | Full current model validation, not cached idle models |

Tests: `tests/context/test_source_inspection_scope.py`, `test_generic_redaction_scope.py`,
`test_source_secret_detection.py`,
`tests/web_console/test_idle_replay.py`, operation core/budget/transport/shutdown cases,
`tests/team_view/test_engineering_history.py` and the existing verification-memory/baseline cases.
Good: unchanged captures reuse scans inside one read while the next poll rechecks all bytes.
Base: no scope means original scanner semantics; a new store replays its first idle check.
Bad: retaining a SAFE/READY model across polls or using metadata to hide same-byte-length tampering.
Correct: reuse only pure complete-text detection and a byte-rechecked no-work conclusion.

### Measurements, existing data and rollback

The isolated sequential real-data probe is
`.trellis/tasks/10-09-console-read-performance/read_probe.py`. It loads the trusted baseline modules
from Git in memory or the working tree, calls only ProductionTeamReader's existing READ ONLY SQL
and pure operation reads, and prints counts/timings/digests, not content or credentials. Never call
production `claim_next` to benchmark it: that could dispatch authorized work.

With the old service still running, baseline `ab5dead` took 25.4233 s and the repair 4.5794 s.
Snapshot source scans fell 14,848 → 67; all 190 SQL calls remain, totaling about 0.28 s. Full operation
replay fell 2.6256 → 0.3206 s; unchanged idle byte inventory took 0.1057 s. These are online-load
measurements, not universal latency bounds or a deployed HTTP comparison. Complete wire SHA-256
excluding `as_of` is identical; 15,935 JSON files / 688,207,263 bytes stayed unchanged.

No migration, history trimming, evidence repair, requirement recreation or automatic continuation
is needed. Load code and frozen frontend assets through an idle controlled service restart, then
refresh the same Project. Rollback this repair and restart restores the previous repeated-work
cost; Task, Operation, approvals, candidate and history are unaffected.

## Synchronous baseline validation scopes (2026-10-10)

### 1. Scope / trigger

Baseline proposal/execution/explicit continuation recursively validate complete retained source.
The read-side scope above does not cover these synchronous mutation services by itself.

### 2. Signatures

```python
ExecutionBaselineService.propose(target_base_ref, *, input_mode, purpose) -> ExecutionBaselinePlan
ExecutionBaselineService.execute(plan_sha256, *, authority) -> ExecutionBaselineBinding
ExecutionBaselineService.continue_execution(binding_sha256, *, authority) -> bool
FileExecutionBaselineStore.plan(sha256) -> ExecutionBaselinePlan
FileExecutionBaselineStore.start(plan_sha256) -> BaselineOperationStart | None
FileExecutionBaselineStore.bindings_for_task(task_id) -> tuple[ExecutionBaselineBinding, ...]
FileExecutionBaselineStore.required_context(binding) -> str
FileContinuationStore.get_receipt(run_id) -> ExecutionInterruptionReceipt
FileContinuationStore.receipts_for_task(task_id) -> tuple[ExecutionInterruptionReceipt, ...]
```

### 3. Contracts

- Each service enters `source_inspection_scope` around its existing execution lock, fact fence,
  complete current capture, preview/apply, publication and validation. Nested leaf reads share only
  exact pure scanner facts. The service exits before Host's subsequent delivery/model kickoff;
  never place this scope around the whole Host, an async task or a worker lifetime.
- Standalone plan/start/bindings/context reads and plan/start/binding publications own their own
  scope. Receipt reads/list/publication likewise include predecessor/admission recursion. Independent
  calls start fresh; all outer scopes reset on both success and failure. Existing 512-entry / 16 MiB
  admission limits, complete-text/path keys and conservative scanner fallbacks remain unchanged.
- Every file, envelope/body/plan digest, structural model, predecessor, exact authority, native-rule
  epoch, Task/queue/claim/stop fact and current Git/worktree observation is still read/checked.
  This is neither a model cache nor authorization reuse. Preserve all original wire and audit bytes.

### 4. Validation / error matrix

| Scenario | Required result |
| --- | --- |
| Real proposal, execution and explicit continue with repeated complete Python body | One parse of that exact body/path per call; unchanged complete inputs/results |
| Standalone plan/start/bindings/context or receipt/list/replayed put | Recursive validators share scanning; next call scans anew; store bytes unchanged |
| Service returned to caller/model kickoff | Cache absent; caller's same-source scan is fresh |
| Plan integrity fails after valid source inspection | Original rejection; cache absent after exception |
| Same outer scope, file body/path changes or envelope digest corrupts | Fresh file read rejects; changed sensitive body/path cannot borrow safe scan |
| Actual current Git/index/inventory or exact authorization changes | Original service/fence rejection; no cached observation or approval |

### 5. Good / base / bad

Good: complete retained source is parsed once while all nested digest/authority checks still execute.
Base: a later independent call reads and scans the same source again. Bad: scope the entire Host
resume, cache an approved plan/binding, or remove independent live capture observations.

### 6. Required tests and measurement limits

`tests/manager/test_baseline_source_inspection_scope.py` uses real Git/private store interfaces,
a large complete Python body and stdlib AST work counters. It checks unchanged models/bytes,
success/exception release, explicit caller-after-service lifetime, and same-scope text/path/hash
tampering. Keep existing baseline/pause/receipt/source-scope tests for permission, integrity and
serialization behavior. Operation construction/publication also runs Git and I/O: sealed reread
speedups do not prove that all minutes of a historical operation were AST work.

### 7. Wrong / correct, existing data and rollback

Wrong: only wrap a leaf plan read while proposal repeatedly captures/parses outside it, or wrap
`TeamHost.continue_execution_baseline` so a long model call retains complete source keys.
Correct: wrap the synchronous service and standalone leaf validation boundaries; let nested scopes
share detection tuples and end before the caller starts a model.

No Schema, SQL or durable record migration is needed. Existing K1 plans, complete receipts,
bindings and approvals keep their original hashes and validity. An idle code restart loads the
optimization; continuation still requires its original exact authorization. Roll back only code
while idle to restore previous cost; never erase history, reset the workspace or recreate a Requirement.

## Synchronous terminal recovery inspection scopes (2026-10-10)

### Scope, signatures and contracts

Terminal recovery proposals and exact approval repeat complete-source validation through the
native source reader, current-facts double reads, capture verification and immutable publication.
Leaf scopes alone end before the next stage repeats the same pure scanner work.

```python
NativeRecoveryEntry.propose(...) -> tuple[RecoveryPlan, Path]
NativeRecoveryEntry.propose_delivery(checkpoint, ...) -> tuple[RecoveryPlan, Path]
NativeRecoveryEntry.approve(path, *, confirmed_plan, reference) -> None
NativeRecoveryFactsVerifier.inspect(plan) -> NativeRecoveryFacts
read_terminal_workspace_snapshot(config, environment, original, capture, ...) -> RecoveryWorkspaceSnapshot | None
```

Each listed synchronous call owns `source_inspection_scope`. Nested readers share only immutable
detection tuples for exact scanner mode, path and complete text. Existing 512-entry/16 MiB limits,
overflow fallback and exception cleanup apply. No file/SQL/Git/inventory/capture/process/claim,
plan integrity or exact authorization observation is cached or removed. In particular, both
native-current and terminal-workspace observations remain independent. Existing wire/audit bytes
and scope/stop/authority gates remain unchanged.

The envelope ends when the synchronous call returns or raises. Do not decorate
`NativeRecoveryEntry.execute`, `resume_execution`, async work, the Host or a worker/model lifetime.
Approval publishes and seals deterministic authorized data; actual model execution is a later
separate operation and cannot borrow this inspection cache.

### Validation matrix and examples

| Scenario | Required result |
| --- | --- |
| Proposal/discovery/approval repeat the same complete source | One AST parse per exact body/path inside that outer call |
| Current facts or terminal workspace are checked twice | Both fresh reads occur; both captures/inventories/stop checks still execute |
| Second observation changes safe source text or another fact | Changed bytes scan independently; original drift rejection remains |
| Source+path exactly fills admission limit; larger patch is encountered | Cache stays bounded; larger patch still scans completely |
| Success, drift exception, independent call or approval replay | Scope resets; later call scans afresh and preserves exact approval semantics |

Good: share pure scans while repeating all fresh observations. Base: the next proposal/approval
starts a fresh bounded cache. Bad: memoize `NativeRecoveryFacts`, reuse a prior approval as current
authority, drop the second audit, or enclose the later Agent execution.

`tests/recovery/test_terminal_source_inspection_scope.py` uses real temporary Git captures and
immutable recovery publication with explicit offline native-source/current-facts seams. Its
terminal helper keeps two source/facts/capture/inventory observations. Its approval case uses real
authorization/receipt publication and an explicit offline fresh-facts sealing seam; it does not
replace full Task derivation tests. Keep `tests/context/test_source_inspection_scope.py` for
mode/path/full-text, capacity, exceptions and thread isolation, and existing terminal workspace
negative tests for actual gates.

### Existing data, limits and rollback

No Schema or persisted fact migration is needed. Existing plans, hashes, approvals, failure history
and retained workspaces remain unchanged. An idle code restart loads the optimization; exact
approval and fresh facts remain required. Roll back the envelope/imports to restore previous cost.
Scanner-count reductions do not prove that every second of production preparation was scanner
work; measure the public operation separately and record differing baselines/inputs.

## Synchronous recovery execution preparation scopes (2026-10-10)

### 1. Scope / trigger

An exact authorized recovery Task can be sealed while execution preparation still repeats
complete source/patch validation before any seed or provider invocation is published. On the
new-dispatch path, seven Builder calls perform seventy fresh current-fact observations. Leaf
inspection scopes alone cannot reuse scans across those adjacent synchronous checks.

### 2. Signatures

```python
AuthorizedRecoveryTaskBuilder.build(plan_sha256) -> RecoveryTaskDraft
RecoveryTaskSealingService.seal(plan_sha256) -> RecoveryTaskRecord
RecoveryTaskSealingService.require_current(plan_sha256) -> RecoveryTaskRecord
RecoveryAllocator.allocate(plan_sha256) -> RecoveryDispatchRecord
RecoverySeedService.seed(target: WorktreeRef) -> RecoverySeedRecord
RecoverySeedService.authorize(request: AgentRequest, workspace_root: Path) -> None
```

### 3. Contracts

- These six synchronous preparation methods own `source_inspection_scope`; nested calls reuse
  only existing pure complete-text detection facts. Limits remain 512 entries / 16 MiB and
  zero-occurrence generic facts keep their existing detector-definition key and admission policy.
- Preserve every original method body, file getter, model/hash validation, authorization check,
  before/after fact observation, capture/stop/inventory check and MySQL commit fence. Neither a
  successful Builder nor an approved plan is cached. Capacity exhaustion still scans fully.
- The preparation scope resets in `finally` on success and failure. The next independent call
  rereads and rescans. `authorize` returns to the adapter before it starts the provider; its cache
  is already absent. Never decorate `_execute`, `execute`, resume/run, async work or the model
  lifetime, and do not add an outer preparation scope around a provider callback.

### 4. Validation / error matrix

| Scenario | Required result |
| --- | --- |
| Builder repeats full source, nonempty patch and clean generic text | One full source/patch scanner and six generic substitutions per call; 10 facts / 2 capture checks remain |
| Seal or require-current includes store and Builder validation | Getters still repeat; next independent call repeats the same getter counts and fresh scans |
| New allocation includes both fenced validations | 40 facts / 8 capture checks and both fences remain; scans share only within allocate |
| Existing allocation replay | 30 facts / 6 capture checks remain; no previous call's cache survives |
| Second fence changes complete source body | Original rejection; no dispatch published and cache released |
| Safe or sensitive source changes after success or exception | Fresh read rejects; repeated failure cannot borrow an old clean fact |
| Stored plan bytes change after its patch was scanned | Fresh envelope/hash validation rejects; next call still rejects |
| Cache budget is zero | Complete scanners and all fresh checks execute; no new rejection |
| Seed replay or one-use provider admission | Fresh sealing/capture checks remain; invocation replay rejected and cache absent before provider |

### 5. Good / base / bad

Good: reuse complete text scans across allocation's synchronous fenced preparation while every
current fact is actually reobserved. Base: a separate seed or authorization starts a fresh cache.
Bad: cache an approved RecoveryTaskDraft/authorization or wrap the whole execution/model call.

### 6. Required tests and measurement limits

`tests/recovery/test_preparation_inspection_scope.py` runs real authorization, Builder, sealing,
allocation and seed/admission service bodies and private immutable file stores, with explicit
offline native-fact/Git/MySQL authority seams. Full source and nonempty patch scanner counters
measure real detector misses; a 179,583-byte clean body measures actual regex substitutions.
Existing terminal/capture/authorization and adapter admission tests remain required. Fixture
scanner reductions do not prove current production latency, SQL stop facts or runtime completion.

### 7. Existing data and rollback

No Schema, SQL, Task, approval, plan, seed, invocation or history migration is required. All
existing bytes and hashes remain unchanged; scopes hold only temporary pure detection facts.
Deployment uses the existing idle controlled restart. Continue the same Requirement through its
existing exact authorization and fresh-fact gates; do not recreate it or rewrite old failures.
Rollback removes these imports/decorators while idle, restoring previous cost without altering
durable records. Any actual production wait still needs separate public-path verification.

## Copy only the current joint checkpoint (2026-10-10)

### Scope, signatures and contracts

`src/ai_software_engineer/multi_directory/store.py` exposes
`JointJournal.current(delivery_id: str) -> JointCheckpoint | None` and
`JointJournal.history(delivery_id: str) -> tuple[JointCheckpoint, ...]`.
Both consume the private complete `_validated_history` iterator. `current` must exhaust it before
returning one deep copy of the final model; `history` returns an independent deep copy of each item.
Empty reads return `None` / `()`. No caller receives the private validated model or iterator.

The iterator retains the existing complete fresh reads, no-symlink checks, byte SHA, model/integrity,
filename, identity and predecessor validation and 512-entry cache policy. Matching bytes and exact
predecessor may reuse the original validation; mtime/size alone never qualify. Do not take only the
last file, stop on the first match, truncate history, or add a cached latest-state decision.
Returning only one copy reduces discarded allocations, not the bytes inspected or verdict gates.
The count limit of the existing model cache is unchanged; this is not a new total Python heap bound.

### Validation matrix and tests

| Case | Required result |
| --- | --- |
| Four valid records, cold or warm current | Read every record; deep-copy exactly one return |
| Same four records, history | Deep-copy all four and isolate nested mutable data |
| Valid append after warm read | Immediately observe the new head, decode the new bytes |
| Same-length/mtime historical corruption | Reject actual digest change |
| Missing prefix/middle, resealed ancestor, wrong filename or symlink | Reject path/chain/identity failure |
| Caller mutates returned attempts dict | Private cache and all later current/history results remain unchanged |
| Empty history | No model reads or copies; return the existing empty value |

`tests/multi_directory/test_current_journal_copy.py`,
`tests/manager/test_joint_journal_read_reuse.py` and
`tests/team_view/test_joint_history_snapshot.py` cover these contracts and the existing 512-entry
limit. Good: verify the complete prefix and return an isolated head. Base: full history keeps all
independent copies. Bad: return a cached head without rereading its ancestors.

### Existing data, observations and rollback

There is no Schema or persisted-data change. Existing requirements, approvals and checkpoints keep
their exact bytes/digests; the same public recovery operation remains authoritative. Controlled
deployment loads the getter implementation without restarting a Requirement or changing its target.
Rollback restores the old `current -> history` path and its allocation cost.

The current K1 parent has 41 sealed JSON files /58,218,393 bytes; its Project parent-lookup range
contains 229 files /261,344,996 bytes. These are bounded read-only size observations, not an end-to-end
profile. The four-record regression's copy reduction does not establish production speed or prove
the absence of a memory leak. Measure the actual public operation separately.

## Snapshot-local complete baseline bindings (2026-10-10)

### Scope and signatures

Engineering history, pending continuation and interruption history can project the same Task's
complete baseline prefix in one HTTP read. A finite read projection may share that already verified
immutable prefix, without changing execution services or current authorization observations.

```python
BaselineBindingSnapshot.bindings_for_task(
    store: FileExecutionBaselineStore, task_id: str,
) -> tuple[ExecutionBaselineBinding, ...]
engineering_history(..., *, baseline_bindings: BaselineBindingSnapshot | None = None)
read_pending_baseline_continuation(..., baseline_bindings: BaselineBindingSnapshot | None = None)
_continuation_history(..., *, baseline_bindings: BaselineBindingSnapshot | None = None)
```

### Contracts and validation matrix

- `_TaskReadSnapshot` owns a fresh `BaselineBindingSnapshot`; it explicitly passes that object
  through `_read_task_details` to all three read callers. No global, ContextVar, reader-instance,
  writer-store or execution-service cache is allowed.
- Only an already constructed `read_only=True` store is accepted. Exact absolute store root and
  Task ID form the key. The first access invokes the original full `bindings_for_task`, including
  plan/start/authority/capture/context/predecessor checks. Register only a successful tuple,
  including empty. Callers inspect these immutable binding models without mutation.
- Existing caller Task/scope/receipt/policy validation, authority-file reads, SQL release/claim and
  heartbeat observations remain unchanged. `None` preserves standalone full-read behavior.
- A subsequent snapshot starts empty and rereads every historical byte, path and digest. Finite
  prefix sharing is not a current execution authorization and never enters an Agent call.

| Scenario | Required result |
| --- | --- |
| Three actual projections, exact root and Task | One complete binding validation; equal projection results |
| Different root or Task, even with shared helper | Separate complete reads |
| Empty prefix, followed by append | Empty stays finite in this read; next snapshot sees appended binding |
| Historical plan/authority/capture tamper or symlink | Next snapshot rejects, with original checks intact |
| First full validation fails | No registered tuple; retry performs complete validation |
| Writer store supplied | Reject before reading or reusing a tuple |
| HTTP success or failure returns | Snapshot-local helper and complete prefix can be released |

Good: three presentation callers consume one verified immutable binding prefix. Base: independent
direct callers retain complete reads. Bad: reuse between polls or treat a saved binding as current
authority to execute. Tests must exercise the real three callers and `_TaskReadSnapshot` wiring,
not only the helper. Latency claims require a short-deadline real read comparison.

### Existing data and rollback

No Schema, SQL, Requirement, Task, approval or historical file migration is required. Original
progress and audit bytes remain valid. Load the read optimization at an idle controlled service
maintenance boundary, then refresh the same Project; it neither starts nor approves execution.
Rollback removes only the helper and read-side wiring, restoring repeated complete validation.

### Bounded measurements and limits

Sequential fresh-process probes on 2026-10-10 compared pre-change `267da45` with the working tree.
Both verified 263 selected Project journal/baseline JSON records /293,873,960 bytes with identical
before/after inventory SHA and identical wire SHA excluding top-level `as_of`; 2 Requirements,
25 Tasks, 202 read-only SQL statements and 2,023,014 response bytes were unchanged. Snapshot time
was 6.7796 -> 5.2838 seconds; complete binding validations 3 -> 2 (3.1226 -> 1.5624 seconds), plan
reads 20 -> 12, start/context reads 8 -> 4 each. These counts span two exact root/Task identities:
2+1 -> 1+1. The earlier aggregate of three calls did not establish that all three belonged to one
Task. A real three-caller fixture separately proves same-root/Task 3 -> 1 and equal projections.

The comparison used a 25-second process alarm, existing read-only transactions and no Host,
initialization, claims, approvals or source writes. Results are machine/input specific; active
heartbeats or appended facts can legitimately change later wire hashes. This optimization is not
evidence of, or a repair claim for, a continuous hours-long read or gate leak. Successful public
Team GETs must be considered when interpreting repeated busy responses.
