# Reduce complete K1 detail read latency

## Proven problem
A successful real K1 request detail took13.04s. Independent ProductionTeamReader.detail
profile:11.571s wall/10.898s CPU; DB0.37s. Detail performs2 snapshots,24 task details,
24 engineering-history projections,4 joint history reads/166checkpoint validations and
12 baseline-plan reads. JSON, deepcopy and Pydantic dominate. Global bounded read gate
correctly refuses competing query modes with TEAM_READ_IN_PROGRESS503 while occupied.

## Goal and scope
Reduce duplicate validation and copying within one synchronous read observation while
retaining exact full bytes, Schema, lineage, integrity and independently fresh final source.
No cross-request cached authority or unbounded history retention. No removal of the memory
read gate, write-side changes, SQL migrations, process injection or active K1 workspace edits.

## Acceptance
- Real complete detail succeeds with an independently measured reduction in duplicate work.
- Fresh snapshot/source at publication remains required; stale facts fail closed.
- Corrupt/mutated immutable bytes, authority changes and query scope drift are rejected.
- Scope lifetime ends on success, error and cancellation; nested/cross-request reuse cannot leak.
- Existing summary/detail and engineering-history tests, strict types/lint, independent review.
- No production migration is needed: all existing facts remain read-only and byte-identical.

## Ownership and rollback
read_latency_fix owns reader.py/engineering_history.py, a necessary tightly scoped read helper
and corresponding tests. Root owns this task and spec documents and later integration.
Independent audit provides measurements and a separate reviewer validates correctness.
All workers share the checkout and preserve each other's changes. Main is not edited during
active delivery. Rollback uses controlled safe stop before reverting platform code; no data
rollback or deletion is required.

## Follow-up scope — 2026-10-19

Goal: reuse only the existing JointJournal exact-complete-byte decoder between the two
observations of one synchronous `detail()` call. Each observation still creates its own
history snapshot, enumerates/reads/hashes every original file, validates current ownership
and retirement, and opens a new SQL snapshot. Public history/current deep copies remain.
No Plan/Start optimization, cross-request cache, database connection or production operation.

Allowed paths: `src/ai_software_engineer/team_view/reader.py`, the necessary cache-release
method in `multi_directory/store.py`, corresponding file/fake unit tests, this task's
documents and `.trellis/spec/core/team-summary-detail.md`. `run6_owned_uncertainty` owns
these edits; other maintainers' files and existing changes must remain intact.

- Good: unchanged full history decodes once per record across two observations, with
  two full reads and identical typed results; next detail starts cold.
- Base: empty history and cache eviction still return complete original results.
- Bad: changed bytes/predecessor/path/retirement or final SQL authority still refuses;
  successful and exceptional exits clear the shared decoder even with a retained traceback.

Acceptance uses actual decode/full-read counts, corruption and lifetime tests before/after
implementation. No portable timing threshold and no claimed production latency reduction.
Rollback removes only call-local reuse and restores repeated decoding. Existing data needs
no migration. Do not deploy or restart while K1 is active; parent owns later controlled loading.
