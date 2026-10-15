# Complete workspace inventory and exact maintenance observation

## Scope and signatures

Apply when observing native worktree mutations, admission, baseline preparation or external
engineering preservation. Git-ignored files still belong to the complete observation.

```python
capture_mutation_inventory(root: Path, *,
    known_oversized_file: MutationFile | None = None) -> WorkspaceMutationInventory
changed_mutation_paths(before, after) -> tuple[str, ...]
is_execution_cache_path(path: str) -> bool
```

Runtime callers omit `known_oversized_file`. They retain the 16,000,000-byte per-file bound,
256,000,000-byte total bound and 20,000-file bound. Two complete stable no-follow passes bind
path/kind/SHA/mode/size. Never skip ignored content, follow links, or infer authorization from
an inventory's success. Protected rules and VCS remain outside cache-write exceptions.
Legacy rescue may additionally capture an ignored regular file when its exact path passes the
frozen read/write policy; explicit execution-cache paths remain outside mutation bodies and are
validated only by the complete inventory. An ignored path that is not policy-authorized remains
uncaptured and blocks rescue without changing or deleting the file.

Trusted external maintenance can supply one exact `MutationFile` already known by full SHA,
canonical relative path, regular-file kind, mode and size. Size must exceed the default and
remain within the unchanged total budget. Only that exact path can exceed the default; both
passes must observe the entire supplied fingerprint. Missing/changed files, other oversized
files, total/count overflow and unstable filesystem observations still reject. This grants
no writing, result acceptance, queue change, retry budget or role permissions. No model/API
body or provider tool exposes this capability, and no global limit is temporarily changed.

## Validation matrix

| Facts | Required result |
| --- | --- |
| Ordinary file above 16MB | Original rejection |
| Exact known file, full stable hash within total budget | Complete maintenance inventory |
| Changed path/hash/mode/size/kind or missing expected file | Reject |
| Another oversized file, total bytes/count overflow | Reject |
| Symlink/FIFO/root substitution | Existing no-follow/fail-closed observation |
| Successful maintenance observation | No write or delivery authority |

Good: an exact stopped-run cache is fully preserved externally, then default inventory resumes.
Base: runtime callers and canonical hashes are unchanged. Bad: approve arbitrary ignored writes,
remove a big cache before recording its original bytes, or treat an inventory as Coder success.

## Existing-data handling and rollback

The scoped script in `.trellis/tasks/10-11-run7-cache-maintenance/cache_quarantine.py` prepares
a complete exact plan under original Task process lock and idle queue fence. Separate delegated
engineering authority records SUPPLY_EVIDENCE, preserves the four cache files by no-overwrite
same-device rename into private sidecar audit storage, verifies every retained byte and checks
that default after inventory differs only by those files. HEAD/index/full source capture,
Task/queue/start/stop/outcome are unchanged. It never recovers a lost report or starts delivery.
Original live Task facts belong to private audit storage; only the plan digest is recorded here.

Failures reuse the first immutable authorization time. Archive-only retries verify the entire
archive and complete after inventory before finishing completion; exact completed replays keep
the original bytes/time. Both source/archive or neither, drift, conflicting authority and bad
directory permissions reject. Failures can leave the cache in the private archive; do not
assume its original path remains. Ordinary continuation still requires an exact public decision.

Incremental tests: `test_exact_oversized_inventory.py`, existing mutation inventory/capture tests,
and `test_cache_quarantine_maintenance.py` with real rename/hash and failed completion replay.
Rollback restores the code capability during an idle reload. Returning a preserved archive
requires another explicit idle maintenance verification; never delete or overwrite either side.

### Exact retained source and Git ignore rules

`GitWorktreeManager.capture_mutations` accepts `retained_source_paths=()` independently of initial
legacy-only `include_ignored` discovery. Capture verification derives that exact scope from its
immutable mutation list. Both modes retain regular-file/body bounds and frozen policy checks;
execution caches remain excluded. Downstream inventory, preview trees, accepted progress,
interruption receipts and candidate commits must agree on every present retained source path.
`StoredCoderExecutionInputResolver.retained_source_paths` derives this set from validated rescue
lineage; `GitCandidateCommitSkill` force-adds only its actual ignored untracked intersection with
literal pathspecs. See [legacy execution rescue](legacy-execution-rescue.md) for signatures,
validation matrix and end-to-end assertions. A legal retained file omitted from a new capture is a
platform capture failure, not authorization to classify it as cache or silently drop its bytes.

Automatic `GitWorktreeManager.remove` checks ignored untracked files before writing a removal
marker. Any noncache file raises `DirtyWorktree` and preserves the checkout; Git's ordinary clean
status cannot prove an ignored-only draft is saved. Explicit execution caches remain removable;
explicit archive-and-release uses its own existing contract. `verify_base_paths(worktree,
permissions, paths, denied_paths=(), base_revision=None)` permits an inherited tracked edit to
vanish from a final mutation capture only after current no-follow text bytes and mode equal its
immutable regular base blob. A retained addition has no such base and cannot use this exception.
