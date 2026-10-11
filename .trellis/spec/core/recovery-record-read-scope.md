# Synchronous recovery record decoding scope

## Scope and signatures

Recovery preparation, exact approval and offline Task sealing repeatedly replay the same
baseline Plan/Start and failed Context. Reuse only their immutable typed decoding during a
single synchronous service call. This is a reading optimization, never an execution or
approval decision. The permitted internal ports are:

```python
recovery_record_read_scope() -> ContextManager[RecoveryRecordReads]
current_recovery_record_reads() -> RecoveryRecordReads | None
finish_recovery_record_reads() -> None
decode_verified_record(
    *, path: Path,
    kind: Literal["baseline-plan", "baseline-start", "context"],
    model: type[T], record_key: str, payload: bytes, allow_reuse: bool = True,
) -> T
KnowledgeRecordStore.read_recovery_record(
    namespace: str, key: str, model: type[T],
    *, kind: RecordKind, optional: bool = False,
) -> T | None
```

`payload` must be the current complete bytes read through the original store's trusted
file port. There is no caller-provided decoder or validator and no Agent-exposed cache API.
Exact allowed models are `ExecutionBaselinePlan`, `BaselineOperationStart`, and
`ContextBundle`. Subclasses, authority records and current Task/READY/facts models cannot
register themselves by claiming another kind.

## Validation and freshness contracts

Every store consumer opens and reads the complete original file again, checking its regular
file/no-symlink path contract and existing size limits. `KnowledgeRecordStore` retains its
20,000,000-byte limit, directory identity, `O_NOFOLLOW`, envelope shape and canonical envelope
digest checks. `FileContextStore` has no total record-size limit; a cache scope must not add
one. Its scoped port performs `O_NOFOLLOW`/regular-file checks, full reading and explicit
UTF-8 decoding. An existing large valid Context still fully decodes when optimization
capacity is exhausted. Native recovery's independent preflight limits remain unchanged.

Only a match of absolute path, kind, exact model class, requested record key, and SHA-256 of
all freshly read bytes can reuse a decoded record. A cache miss executes fixed envelope/schema
decoding for Plan/Start or UTF-8/schema decoding for Context. Registration additionally
executes the complete Plan/Start `validate_integrity()` or content-addressed Context manifest
validation and verifies the exact Plan SHA, Start's embedded Plan SHA, or Context ID.
Malformed envelope bytes cannot be registered by returning an unrelated valid model.

Each result is a deep copy of a private validated model. Nested Task metadata in a historical
Plan and other mutable containers cannot poison later consumers. On bytes changing, discard
the old decoded entry before full validation; failed/absent records never reuse an earlier
model. Envelope corruption keeps `KnowledgeError("STORE_CORRUPT")`; missing required records
keep `KnowledgeError("RECORD_NOT_FOUND")`; Context decoding/path/identity failures keep
`ContextCorruption`. Unsupported kinds/models or key drift reject with `ValueError`; native
facts admission continues to translate validation failure to its existing `RecoveryRejected`.

Embedded historical Task, source captures and authority hashes are historical data only.
Every consumer independently reruns current SQL/Task/lease/Git/process/inventory and
before/after capture checks. `BaselineOperatorAuthorization`, `EngineeringAdmission`,
HumanAction and native rule epochs are fresh normal reads/decodes. Bindings are not cached;
their predecessor and currently available authorization chains remain fully checked.
Do not cache `NativeRecoveryFacts`, current permission, terminal stop proof, approved receipt,
Task status, usable claim or a successful recovery/READY conclusion.

## Ownership, capacity and execution lifecycle

The capacity is aggregate across all roots and namespaces: at most 512 entries and 32 MiB of
summed complete raw plus typed serialization footprints, path keys and digest overhead.
This is an optimization accounting bound, not a claim about total Python heap or process RSS.
Overflow returns the fully decoded/validated result without retaining it or evicting evidence.
No prefix read, truncation, mtime-only identity or forced GC substitutes for validation.

Nested synchronous preparation/approval/sealing calls share the owning scope. Ownership is
the exact thread plus current asyncio Task identity (or no Task outside an event loop).
Copied ContextVars in another thread or inherited asynchronous child cannot borrow or close
the parent's cache; they can independently own another scope. Supported production entrypoints
are synchronous. Do not await or apply this decorator to asynchronous operations.

Public propose/propose_delivery/latest/require_current/approve and native source/facts
inspection own short scopes. `_continue_coder_recovery` shares the preparing and approving
phase, then explicitly closes the scope before `resume_execution` or interruption execution.
`NativeRecoveryEntry._execute` creates its own admission scope and closes it before
`backend.run_prepared_allocation`; terminal-result adoption has the same boundary.
All success/failure exits clear entries and reset ContextVar state. The next public Operation,
later admission gate or model call cannot inherit the old decoded models. First-run workspace
admission continues to validate current facts in fresh short inspection scopes.

## Validation matrix and test points

| Input or lifecycle | Required behavior |
| --- | --- |
| Actual baseline selector, `require_current`, required Context and epoch consumers | Full original bytes reread for every consumer; Plan and Start each decoded once within the scope |
| Public approve → real authorization → real Task builder → real sealing | All 16 retained authorization before/after observations run fresh; redundant middle builder inspection removed by recovery-admission-facts; exact receipt/Task lineage persisted normally |
| Next independent Operation | New full Plan/Start validation, even if bytes and mtime are unchanged |
| Same-size/same-mtime old Plan/Context corruption | Fresh bytes detect the change and reject; an earlier success cannot mask it |
| Bad envelope, wrong key, authority model or missing original authority | Reject without registering a weaker validation result or inventing authority |
| Live facts change while record cache is warm | Original before/after admission rejection; no rewritten receipt or sealed Task |
| Returned historical nested metadata mutated | Later complete model results remain unchanged |
| Multiple sidecar roots exhaust entries or bytes | One aggregate limit; overflow still fully reads and validates |
| Valid Context over 8 MB / UTF-16 or UTF-32 encoding | Large UTF-8 record stays readable; non-UTF-8 still rejects in normal and scoped ports |
| Copied-thread or same-thread asyncio child ContextVars | No parent reuse or parent closure; child's independent scope releases on return |
| Success, failure, and execution callback boundary | Zero retained entries; model weakrefs release; execution callback sees no active cache |

`tests/recovery/test_record_read_scope.py` drives actual file/selector consumers and the public
approval service with real authorization, builder and sealing. Live facts/SQL ports use
deterministic fixtures rather than production stores. Keep `test_terminal_baseline_sql.py`,
`test_terminal_baseline_context.py`, `test_terminal_source_inspection_scope.py`,
`test_current.py`, native baseline service and ordinary Context/Knowledge store regressions.
Assert decode/read/observation counts and exact typed results; do not make portable latency
or RSS assertions in unit tests.

Good: reuse a fully verified Plan's typed decoding while reopening its bytes and rereading the
actual current authorization. Base: zero cache capacity still returns the full verified record.
Bad: register a valid in-memory Plan under corrupted envelope bytes, cache a READY decision,
or hold large historical models throughout a 30-minute Coder provider invocation.

## Existing data, deployment and rollback

存量数据处置：there is no Schema, SQL, journal, approval or workspace migration. Preserve all
existing Requirement/Task/Operation identities, prior evidence and drafts. This repair does
not grant execution approval or restart an interrupted operation. Load it only after the
currently authorized operation/roles end, through ordinary idle controlled maintenance;
then use the original Requirement's existing public exact approval/continue path as applicable.
Do not duplicate the Requirement, reset counters, kill an active execution, remove stop
preconditions or alter durable facts to load this optimization.

Rollback reverts the reading scope/seam and restores repeated full decoding cost. It preserves
every historical record, exact approval, Task, queue and retained worktree. Performance
measurements and incremental commands live in the matching Trellis task verification document;
finite fixture improvement does not establish production end-to-end latency or absence of
long-running memory leaks.
