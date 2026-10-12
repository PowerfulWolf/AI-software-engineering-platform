# Compact native Requirement history observation

## Scope and signatures

Legacy no-start Context-capacity recovery repeatedly checks retired native children and
their current joint parent. Those checks must reread complete history without keeping
hundreds of complete historical JointCheckpoint graphs throughout recovery admission.
Use the fixed internal observer in `multi_directory/history_observation.py`:

```python
class JointRecordFacts(DomainModel):
    delivery_id: DeliveryId
    sequence: int  # >= 1
    checkpoint_sha256: Sha256
    previous_checkpoint_sha256: Sha256 | None
    team_id: TeamId
    team_manifest_sha256: Sha256
    project_id: ProjectId
    project_manifest_sha256: Sha256
    child_delivery_ids: tuple[DeliveryId, ...]

class _VerifiedJointEdge(DomainModel):
    codec_version: Literal["native-joint-prefix-v1"]
    predecessor_payload_sha256: Sha256 | None
    facts: JointRecordFacts

@dataclass(frozen=True)
class NativeRequirementPrefix:
    current: JointCheckpoint | None
    records: tuple[JointRecordFacts, ...]

observe_native_requirement_prefix(root: Path, delivery_id: str) -> NativeRequirementPrefix
NativeHistoryJournal.native_prefix(delivery_id: str) -> NativeRequirementPrefix
NativeChildHistoryReader.native_child_history(delivery_id: str) -> tuple[JointRecordFacts, ...]
```

`NativeHistoryJournal` inherits ordinary `JointJournal.history/current` unchanged. Only
native recovery composition opts into `native_prefix`; the optional typed retirement
port preserves the original full-history fallback. No Agent tool can register a receipt,
choose a decoder/validator, or obtain new filesystem/SQL/approval authority.

## Complete bytes, identity and successor contract

Each observation performs the original independent complete regular-file preflight and
Journal read. Preflight freshly enumerates all JSON paths, enforces the original 8,000,000
byte regular-file limit and no-symlink ancestors. The Journal phase enumerates again, sorts
the complete second inventory, rechecks every path and reads every complete payload.
It computes SHA-256 over all second-read bytes. Neither inventory nor current/head is
reused across observations. Missing directories keep ordinary empty-prefix semantics.

The owning `RecoveryRecordReads` key contains absolute path, fixed internal kind
`joint-history`, exact `_VerifiedJointEdge` model and delivery ID. A hit additionally
requires the current complete payload SHA and the preceding payload SHA from this same
fresh prefix. Codec version is fixed by the DTO. Sequence and filename are checked against
the current complete inventory even on a hit. Mtime, size, semantic checkpoint digest or
another Project's path cannot stand in for complete-byte identity.

Every miss uses fixed `JointCheckpoint.model_validate_json`, `validate_integrity`,
filename/delivery validation and original `multi_directory.store._validate_successor`.
Only successful full validation can derive `JointRecordFacts` and register an edge receipt.
Never reimplement approved-product, Manager-coordination, integration retry, knowledge
recheck, planning, native acceptance or DONE rules from compact fields.

The head is independently fully decoded and integrity-checked on **every** observation,
including a receipt hit, and returned as a private deep copy. An exact head edge may reuse
its previously proven successor relation; head model/integrity validation never reuses a
prior model. Compact historical facts are private copies. Returned nested attempts cannot
poison another observation.

One pass keeps only the previous payload locally to reconstruct its complete model when
a miss follows a compact hit. This adds no file read and retains no full prefix of raw
bytes. The original successor validator always receives complete models. Clear observer
working references on all exits; validator exception frames may retain their own inputs,
distinct from the owner-retained receipt graph.

A changed record invalidates its receipt before validation. Its next edge must match the
new predecessor bytes. A missing first/middle record, resealed ancestor, wrong name,
symlink, corrupt body or invalid successor rejects the complete observation. A valid new
tail is fully read/validated and becomes the new head immediately. An incomplete prefix
cannot return a formerly cached head.

## Shared lifecycle and retirement integration

Journal receipts use the **same aggregate 512-entry / 32 MiB accounting budget** as
baseline Plan/Start and Context decoding in `RecoveryRecordReads`. No per-journal/root/
Project extra pool exists. Receipt accounting includes compact serialized facts, key and
fixed digest metadata; complete historical raw/model bodies are not retained by this path.
Overflow performs the same full validation and returns complete results without retaining
them. It cannot truncate child IDs, omit foreign history, add a record-size refusal or make
a previously valid record unreadable.

This accounting limit is not a total Python heap/RSS guarantee. Fresh heads, returned facts,
the previous payload, decoder temporaries and existing caller frames are outside retained
cache accounting. Measure runtime memory separately.

Native retirement still reads the current retirement file and checks every complete retired
prefix. It uses all historical `child_delivery_ids`, full latest head owner/digest, latest
plan-derived IDs and full replacement head checks. Finding a retired child cannot stop
validation of later entries/replacements. Parent search and delegation retain original
owner/approval/native ancestry/ambiguity checks. `_NativeRequirementHistory._currents` is
only observation-local; every fresh initial/parent observation uses a new adapter.

Shared receipts live only in the existing synchronous recovery preparation/admission scope,
owned by exact thread and asyncio Task identity. Copied thread/async ContextVars cannot
reuse or close a parent's owner. Normal return and failure clear all retained entries and
reset ContextVar state. Existing `finish_recovery_record_reads()` before backend/model
callbacks remains; first Coder admission uses a separate short scope. The next Operation
or HTTP request starts cold. SQL Task/claim/lease, Git/process/capture, authority and READY
conclusions are always fresh and cannot register as immutable receipts.

## Validation matrix and test points

| Case | Required outcome |
| --- | --- |
| Real Allocator → sealing → Builder with large historical requirement | Both fences and all fresh facts remain; ancestor decoding drops to one cold decode, heads remain fresh |
| Repeated observation | Two fresh inventories, separate regular preflight and complete Journal byte reads per path |
| Actual NativeFacts → exact capacity reader | Persisted receipt, source/policy and complete patch bind to plan; changes reject with warm receipts |
| Same length/mtime corruption, resealed ancestor, missing first/middle, wrong filename, symlink | Complete-prefix rejection; earlier receipt cannot authorize success |
| Changed coordination/source facts or approved product/approval | Original successor rejection after full decode |
| Integration approval wrong source/removal or consumed budget reset | Original exact approval and non-resettable attempt rejection |
| Knowledge recheck wrong previous wait/source | Original upstream handoff rejection |
| DONE with new tail | Original completed-delivery immutability rejection |
| Compact/full retirement ports | Same success/error class and reason for historical child, hash/owner corruption, missing/foreign replacement and bad ancestor |
| Context first or journal first; multiple roots reach 512; one-byte allowance | One shared budget; full results remain readable after saturation |
| Second allocation fence observes changed history | No dispatch publication; before/after fence counters reached |
| Mutated full head, retained exception, callback, thread/async child | Private values, owner cleared and independent next scope |

Executable contracts are `test_requirement_history_observer.py`,
`test_requirement_history_successors.py`, `test_requirement_history_service_scope.py` and
`test_capacity_parent_journal_scope.py` in `tests/recovery/`. Keep capacity source/SQL/entry,
original Journal reuse/private-copy, retirement/deletion, record-read scope and preparation
inspection incremental regressions.

The allocation performance fixture observes a real capacity source as a side effect while
returning independent offline preparation facts; it does not claim exact same plan/source
binding. A separate actual NativeFacts integration verifies that binding while target
Git/compiler ports are explicitly fake. Fixture decode counts establish no production
latency threshold or runtime memory guarantee.

## Existing data, deployment and rollback

存量数据处置：no durable Schema, SQL, journal, receipt, approval hash or worktree changes.
Preserve original Requirement/Task/Operation and retained K1 progress. This optimization
does not approve or resume execution. After active roles complete, load it via ordinary
controlled idle maintenance and use the original Requirement's existing exact approval or
continue operation when appropriate. Do not recreate the Requirement or bypass native gates.

Rollback reverts only internal compact observation composition and shared receipt
registration, restoring full historical decoding. Durable records and original
retirement/parent rules remain valid; rollback must not clear evidence, edit verdicts,
reset attempts or alter active execution to reduce preparation latency.
