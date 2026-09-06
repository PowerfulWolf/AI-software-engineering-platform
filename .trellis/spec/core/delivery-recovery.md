# Explicit delivery recovery — T044

## Scope / Trigger

Use when capturing interrupted Coder work or extending terminal delivery recovery. This first
increment is a **read-only Python repository seam**, not a production recovery command. Existing
`resume`, Task terminal guards, role cleanliness guards and artifact gates remain unchanged.

## Signatures

```python
GitWorktreeManager.capture_changes(worktree: WorktreeRef, permissions: AgentPermissions,
                                   *, denied_paths: tuple[str, ...] = ()) -> WorktreeChangeCapture
GitWorktreeManager.verify_capture(capture: WorktreeChangeCapture, permissions: AgentPermissions,
                                  *, denied_paths: tuple[str, ...] = ()) -> None
```

Implementation: `git/capture.py`, `git/worktree.py`. `WorktreeChangeCapture` is a frozen in-process
dataclass like `WorktreeRef`, not a public JSON/wire or persisted Artifact contract. Fields: exact
`worktree` identity, HEAD-to-working-tree `patch` bytes, `index_diff_sha256`, and sorted
`file_sha256s` pairs `(path, current_file_sha256)`. `capture_sha256` binds these with canonical JSON
and the patch SHA. No timestamp, approval, Task status or verdict is included.

## Contracts

- Caller must establish the old executor has stopped. Two equal complete observations detect observed
  drift; they are not a lock or proof of absence of concurrent writers.
- Validate registered ownership, exact Coder branch/path/common directory and full original HEAD.
  Reject partial commits/HEAD drift, not guess a baseline.
- Reuse WorkspacePolicy read **and** write permissions with explicit deny globs. Changed-file reads
  use no-follow directory descriptors; final open is nonblocking, regular-file-only and bounded.
- v1 supports only modifications to existing regular UTF-8 text files with unchanged mode. Clean
  captures are allowed but prove no delivery. New/deleted/renamed/untracked files, binary, index-only
  changes, assume-unchanged/skip-worktree flags and submodules fail closed. Ignored build scratch is
  not copied. Limit: 256 changed files; 1,000,000 combined before/current content bytes; 1,000,000 bytes
  per captured diff. No truncation. Git diff disables optional locks, hooks, fsmonitor, external diff
  and textconv. Repository checkout filters remain rejected by existing guards.
- Staged and unstaged edits combine into the HEAD-to-working-tree patch; staging has a separate
  digest. Capture never stages, commits, stashes, rebases, applies or deletes files.
- Diffs use zero context (`--unified=0 --inter-hunk-context=0`) and full blob IDs, so unchanged nearby
  secrets/test fixtures are not copied. Strip optional source labels after hunk `@@` ranges as they
  can also contain unchanged lines; preserve ranges and all actual edit bytes. Future application
  must explicitly support zero-context
  patches and verify exact base/target hashes; do not apply fuzzily to an arbitrary checkout.
- Existing secret detection scans working and staged diffs. Reject hits: redacting a reusable patch
  silently changes code. Rejection messages contain neither patch nor secret. Pattern matching is
  conservative, not a guarantee that every possible secret will be found.
- `verify_capture` reobserves the source with current permissions and compares the whole capture.
  A digest proves identity, not trusted origin/approval/authority. Nothing persists or applies it.

## Validation & Error Matrix

| Input / failure | Result |
|---|---|
| Non-Coder, unsupported change, UTF-8/binary/size/secret failure | `WorktreeCaptureRejected`; no effects |
| Read/write/deny failure | Existing `PathPolicyViolation`; rejected file not read |
| Forged path/common-dir/ref | Existing ownership/identity error; source retained |
| HEAD no longer original full SHA | `WorktreeRevisionDrift`; no checkout/reset |
| Files/index change during or after capture | `WorktreeCaptureRejected`; no implicit acceptance |
| Identical identity/staging/content | Equal capture/digest; no index/ref/file writes |

## Good / Base / Bad Cases

- Good: preserve staged + unstaged edits, exact replay returns the same capture and index digest.
- Base: clean worktree yields empty patch, with no implied candidate or passing verdict.
- Bad: treating capture as implementation report, arbitrary dirty adoption, or resetting BLOCKED
  Task attempts/status because quota returned.

## Tests Required

`tests/git/test_capture.py` uses real temporary Git without model/network/DB. Assert patch/file hashes,
index bytes/HEAD/main checkout unchanged, replay, content/staging/HEAD/payload drift, permissions,
role/forged root, unsupported changes, symlink/FIFO, secret and size rejection. Full regression,
Ruff, strict Mypy, lock/build and diff checks remain gates.

## Wrong vs Correct

```python
# Wrong: unverified edits become authority.
task.status = "IMPLEMENTING"
git_apply(arbitrary_patch)

# Correct: observe facts; authorize a new execution in a SEPARATE future service.
capture = manager.capture_changes(coder_ref, assigned_permissions, denied_paths=denied)
manager.verify_capture(capture, assigned_permissions, denied_paths=denied)
# Neither call creates Task, approval or candidate.
```

## Remaining production recovery (not implemented in this increment)

1. Sidecar append-only plan/receipt binds failed parent/child/Task/dispatch/upstream digests and
   capture; trusted human authorization binds the exact recovery plan.
2. Explicit carry-forward of approved content onto a newly prepared base; never overwrite historical
   profile/spec/approval hashes. Base conflicts or changed current rules block.
3. Fresh execution/Task/run/branch and resource allocation with recovery-of lineage. Bound snapshot
   application supplies untrusted Coder input, not a candidate commit. Original worktree is retained.
4. Coder completes/commits/reports; fresh independent QA/Reviewer validate that candidate. Joint
   integration/evaluation retain failure and human intervention. Receipt replay avoids duplicate calls;
   a second interruption needs a new explicit linked recovery.
