# Legacy capacity parent journal observation

## Scope / Trigger

An exact legacy no-start Context capacity source checks Requirement retirement once, then
locates its parent before and after other source facts. Creating a new JointJournal at all
three sites repeats full typed decoding of unchanged historical requirements. Reuse the
existing journal decoder only within one synchronous LegacyContextCapacitySourceReader
observation. This does not change recovery authorization or the number of observations.

## Signatures

```python
LegacyContextCapacitySourceReader.discover(scope: RecoveryScope) -> NativeRecoverySource
LegacyContextCapacitySourceReader.inspect(
    scope: RecoveryScope, receipt_sha256: str,
) -> NativeRecoverySource
LegacyContextCapacitySourceReader._inspect(
    scope: RecoveryScope, receipt: ContextCapacityReceipt | None,
) -> NativeRecoverySource
```

The private observation owns a local `dict[Path, JointJournal]`, passed through the existing
`_require_native_active(..., journal=...)` and `_parent(..., journals=...)` seams. No public
cache parameter, new persisted record or new Agent capability is introduced.

## Contracts

- The map is created afresh for each `_inspect`; it is never stored on the reader, Host,
  HTTP request cache, process global or recovery record decoding scope.
- Each retirement/parent observation still performs complete path/no-symlink preflight,
  reads every historical journal byte and hashes it. Existing exact-byte and exact-
  predecessor matches may reuse only JointCheckpoint decoding and successor validation.
  Size/mtime do not establish equality. Current parent selection and retirement decisions
  are recomputed through the original helpers each time.
- The existing JointJournal maximum of 512 retained entries remains unchanged. This is
  its existing count bound, not a new claim about serialized bytes, Python heap or RSS.
- Preserve every before/after SQL, Task, claim, baseline epoch, permission, original Plan,
  approved stage, no-start inventory and Git capture check. There is no cached READY or
  current authority conclusion. Context directory scanning is outside this optimization.
- On success or exception, clear every locally owned journal's existing `_verified`
  decoder entries and then clear the map. A retained exception traceback can hold a
  helper's journal local after return; clearing only the outer map does not release its
  decoded models. Do not change or clear any externally owned journal.
- The next public discover/inspect, including reuse of the same reader object, starts
  empty and decodes every current historical byte again. Exceptions retain the original
  RecoveryRejected cause and safe public message; no durable fact is rewritten.

## Validation & Error Matrix

| Input or lifetime | Required behavior |
| --- | --- |
| Unchanged retired prefix and replacement, three source observations | Journal full reads three times plus three existing regular preflight reads; one typed decode per file |
| Next public observation on the same reader | All bytes reread and decoded again |
| Same-size/mtime corrupt ancestor | Original digest/path rejection remains |
| Missing history, symlink, resealed ancestor with stale successor | Refuse source; preserve stored facts |
| Valid new tail during source observation | Final parent read sees it; original relevant-source comparison remains authoritative |
| New or changed retirement record | Read and verify current retirement again; never reuse an earlier active decision |
| Normal return or retained RecoveryRejected cause | Local journal decoder entries are empty |
| SQL/claim/no-start/capture fake counters | Same two before/after observations per source |

## Good / Base / Bad Cases

Good: a local map shares only exact-byte journal decoding while all three ownership reads
remain fresh. Base: no journal history still gives the existing empty parent result.
Bad: keep the map on a long-lived reader, return an old current checkpoint without reading
its prefix, merge the before/after checks, or clear a writer/external journal's cache.

## Tests Required

`tests/recovery/test_capacity_parent_journal_scope.py` uses real temporary Team, Project,
Repository, native checkpoint, Requirement retirement and complete parent journals. Only
unrelated SQL, baseline, stage, Context and Git ports are explicit offline fakes. Count full
Journal Path.read_bytes, independent regular preflight reads and JointCheckpoint decodes,
compare preserved complete patch and fresh
source check counts, retain failure objects when checking cache release, and exercise
historical corruption plus new tails. Existing JointJournal corruption/copy/bound and
legacy capacity source/approval tests remain incrementally required. Fixture reductions
do not prove production latency or total memory improvements.

## Wrong vs Correct

Wrong: `self.parent_journals = {...}` persists decoded models across public observations,
or merely clearing a local map leaves a traceback-held journal's decoded history alive.
Correct: create the map for one `_inspect`, pass it to the existing fully fresh readers,
and clear its private decoded entries plus map in `finally`.

## Existing data and rollback

No data migration or production write is needed. Requirement, Task, Operation, receipt,
approval, patch and checkpoint bytes/hashes remain unchanged. Deploy only after active
execution is idle through the controlled service restart; continue the same Requirement
through its existing public approval/execution path. Revert this local read composition
while idle to roll back; retain every old/new audit record and preserved worktree.
