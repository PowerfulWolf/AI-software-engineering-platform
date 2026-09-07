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

## Production recovery roadmap

1. Increment B below implements the append-only plan/receipt and authorization service seam.
   Production adapters must still resolve native failed parent/child/Task/dispatch/upstream facts
   and actual human authorization; hashes supplied by callers are not sufficient evidence.
2. Explicit carry-forward of approved content onto a newly prepared base; never overwrite historical
   profile/spec/approval hashes. Base conflicts or changed current rules block.
3. Fresh execution/Task/run/branch and resource allocation with recovery-of lineage. Bound snapshot
   application supplies untrusted Coder input, not a candidate commit. Original worktree is retained.
4. Coder completes/commits/reports; fresh independent QA/Reviewer validate that candidate. Joint
   integration/evaluation retain failure and human intervention. Receipt replay avoids duplicate calls;
   a second interruption needs a new explicit linked recovery.

## Increment B contract — durable recovery intent

Scope: `recovery/` holds proposed recovery and verified human decision facts, not Task execution.

```python
RecoveryAuthorizationService.propose(plan: RecoveryPlan) -> RecoveryPlan
RecoveryAuthorizationService.authorize(command: RecoveryApprovalCommand) -> RecoveryAuthorization
RecoveryAuthorizationService.require_current_authorization(plan_sha256: str) -> RecoveryPlan
FileRecoveryStore.initialize(root: str | Path, *, scope: RecoveryScope) -> FileRecoveryStore
FileRecoveryStore(root: str | Path, *, scope: RecoveryScope)  # existing store, no mkdir
FileRecoveryStore.put_plan(plan: RecoveryPlan) -> RecoveryPlan
FileRecoveryStore.get_plan(plan_sha256: str) -> RecoveryPlan
FileRecoveryStore.put_authorization(record: RecoveryAuthorization) -> RecoveryAuthorization
FileRecoveryStore.get_authorization(plan_sha256: str) -> RecoveryAuthorization
```

`RecoveryPlan` contains failed-source lineage, embedded `CapturedChanges`, target base/preparation,
permissions/denies, aware creation time and `plan_sha256`. `RecoveryAuthorization` contains the exact
approval command plus verifier-issued decision and `authorization_sha256`; one decision per plan.
`schemas/delivery-recovery.schema.json` describes plan/authorization union; model and wire validation
both reject extras. Integrity is not trusted origin: application ports must independently verify facts.

The service has no model, Task/state, Git apply or dispatch port. Propose and fresh approval verify
current facts and the exact capture. Human verification is followed by a second freshness check before
one complete receipt publish. Exact receipt replay needs no callbacks; execution gate separately
requires APPROVED and revalidates current source/target/capture. New Task identity is derived from plan
digest, not the old Task ID. No completed plan or receipt may be overwritten.

Store opens existing root without writes; initialize creates one directory under an existing sidecar.
Persist `scope.json` binding company/project/delivery and canonical project root, including after
restart; a constructor argument alone cannot establish durable ownership. Reject overlapping/symlinked paths, inode
replacement, nonregular files, invalid identity/digest and bounded-size violations. Use private files,
dirfd/no-follow operations, write-all, fsync and exclusive publication. Plan embeds the patch so no
partial multi-file snapshot exists. Successful publication followed by process loss replays from the
single full receipt. Crash before receipt depends on verifier's own command idempotency.

| Case | Required result |
|---|---|
| Exact plan/command replay | Same original fact, no second human-verifier call |
| Changed command for decided plan | Recovery conflict; preserve first decision |
| Verifier mismatches plan/reference or time | Refuse before receipt |
| Current facts or capture changed | Refuse at proposal/approval/execution gate |
| Human rejects | Durable rejection, no execution authorization |
| Tampered digest/patch/filename or cross-company/source | Fail closed |
| Concurrent differing decisions | One exclusive winner; loser cannot overwrite |
| Read-only open / denied root / secret | No project writes; no raw secret in error |

Good: close/reopen and replay exact approval offline. Base: durable rejection. Bad:
`store.get_authorization(sha)` used as permission without `require_current_authorization(sha)`.
Tests in `tests/recovery/` must assert callback counts, zero runtime/target effects, all failure cases,
real-Git capture round-trip, schema parity, file mode, concurrent first-winner and interrupted publish.

`RecoverySource` binds `scope`, BLOCKED `task_id/task_revision/task_sha256`, `checkpoint_sha256`,
`dispatch_sha256`, `preparation_sha256`, approved `product_spec_sha256/approval_sha256`,
`technical_design_sha256/execution_plan_sha256`, `failed_run_id/failed_context_id`, `base_revision`
and optional paired `parent_delivery_id/parent_checkpoint_sha256`. `RecoveryPlan` additionally binds
`target_base_revision/target_preparation_sha256`. Full commits have exactly 40 or 64 hex characters.
Paths, permission strings and approval metadata reject detected secrets before persistence; a patch
is rejected rather than redacted. Recovery permissions cannot grant Coder state-change or merge rights.

Double freshness checks do not lock Git or external databases. The trusted caller must establish the
old executor has stopped; future dispatch must add its own current-fact fence. This seam supplies no
production fact verifier, human channel, Task, dispatch, seed application or CLI command.

## Increment C1 — read original production facts

Scope: `recovery/native.py` inspects the original failed production delivery. This is not the full
`RecoveryFactsVerifier`: it does not validate a new target preparation/current rules or authorize a
new execution. Use only after the old executor has stopped; storage remains trusted organization
infrastructure, not an OS security sandbox against concurrent arbitrary writers.

```python
NativeRecoverySourceReader(config: ProductionConfig, environment: Mapping[str, str])
NativeRecoverySourceReader.inspect(
    scope: RecoveryScope, *, failed_run_id: str, failed_context_id: str,
) -> NativeRecoverySource
```

The frozen in-process result contains `source: RecoverySource`, original `permissions/denied_paths`
and typed `preparation/product/approval/design/plan`. It is not a new wire Artifact or approval.
Company is selected by config; manifests must bind the exact company/project/code directory. Read
the terminal native journal and one MySQL REPEATABLE READ / CONSISTENT SNAPSHOT / READ ONLY
transaction for `tasks`, `state_events` and `dispatch_commits`; no repository constructor/DDL,
prepare, model, Task mutation or dispatch call. Reuse existing SQL row decoders and stage validators.

Require BLOCKED before candidate creation, attempt 1, exact Task revision, unchanged immutable
dispatch intent and contiguous state events ending IMPLEMENTING→BLOCKED. Read the native completed
Product approval, Designer/Planner commits and authoritative READY request revision; verify stage
digests, original preparation and semantic coverage through `validate_stage_chain`. Read the failed
Coder route and its exact ContextBundle, rather than accepting caller-supplied permissions. Missing
or successful routes, wrong role/base/attempt/context and route index gaps reject.

Discover parent ownership from company joint journals and deterministic child identity. A delegated
joint approval must match the parent approval reference and exact stored child checkpoint; callers
cannot opt out of parent lineage. Recheck native checkpoint, SQL Task/dispatch, current request and
parent at the end. This detects observed drift, not a cross-filesystem/database transaction or lock.

The existing `FileProductRecordStore`, `FileDesignRecordStore`, `FileExecutionPlanStore`,
`FileProjectPreparationStore` and `FileContextStore` accept `read_only: bool = False` as a keyword-only
constructor option. True never initializes missing roots; writes (including exact write replay) and
Product revision fences reject. Default production writers are unchanged. Inspection rejects symlink
roots and preflights bounded regular context/route/parent files before native parsing. SQL credentials
come only from `config.database.dsn_env`; public failure is safe `RecoveryRejected`, without raw cause.

| Input/failure | Result |
|---|---|
| Native single-project failed Coder | Exact source and approved documents; no writes |
| Joint child failed Coder | Same plus mandatory verified parent ID/checkpoint |
| Missing platform/root/record/approval | Reject; never initialize or fabricate facts |
| Wrong scope, Task revision/status, run/context, dispatch or upstream digest | Reject |
| Rejected/changed approval, later READY revision, tampered stage commit | Reject |
| Read-only put/fence | Typed native store error before file/lock publication |
| Complete result replay | Same facts, no Agent/model calls |

Good: real temporary Git/MySQL + offline interrupted Coder, then two byte-preserving inspections.
Base: no platform exists, rejection creates nothing. Bad: feeding the returned source directly into
dispatch without separately authorizing new preparation and recovery intent.

Tests: `tests/recovery/test_native.py` covers single/joint production fixtures, read-only store modes,
cross-company/missing run/context, corrupted Product/approval/Designer/Planner/parent records and
byte snapshots of project/sidecar. Dedicated MySQL test DB only; real source observation is separately
recorded and is not independent QA/Review evidence for the original feature.

Wrong: assume `route.completed_at <= checkpoint.checkpointed_at` proves ownership. Legacy native
checkpoints retain the initiating command timestamp, which may precede a run. Correct: bind explicit
run/task/context/revision and state/approval chains; do not rewrite historical timestamps or infer
provider failure cause from them.

## Increment C2 — seed a fresh repository checkout

Scope: repository operation in `git/worktree.py`, not a production recovery entry or approval.

```python
GitWorktreeManager.seed_changes(
    capture: WorktreeChangeCapture, target: WorktreeRef,
    source_permissions: AgentPermissions, target_permissions: AgentPermissions,
    *, source_denied_paths: tuple[str, ...] = (), target_denied_paths: tuple[str, ...] = (),
) -> WorktreeChangeCapture
```

Caller must first authorize exact recovery/target preparation, create a fresh Task and exclusively
hold both worktrees with the previous executor stopped. Require different Task IDs, target Coder
attempt 1, registered full-SHA identity, clean target and target base descending from source base.
Revalidate original capture and both read/write/deny policies; target paths must be bounded regular
UTF-8 files. Reject effective external filter/merge-driver configuration and merge attributes.
Reject `.gitattributes` edits so the applied patch cannot change its own merge behavior.
No model, state, dispatch, approval, commit, ref rewrite, reset or old worktree write occurs here.

Use full-index zero-context three-way Git apply with fixed text default, whitespace behavior and
existing hook/fsmonitor guards. Preflight actually applies with `--cached --3way --unidiff-zero` to
a disposable copied index (`GIT_INDEX_FILE`); Git may create unreachable shared objects, but no
target index/files/refs change. Recheck source, target and configuration, then apply with `--index`
to target. Return a revalidated target capture; independent newer-base changes remain. Original
source is checked again. Observation is not an OS lock against concurrent hostile writers.

| Case | Result |
|---|---|
| Compatible newer base or same base | Target capture; source content/index/HEAD unchanged |
| Empty source or changes already in new base | Empty capture, not a candidate or delivery |
| Conflict, old/unrelated base, dirty/wrong identity, denied path or merge driver | `WorktreeSeedRejected`; retain source and target |
| Preflight failure | Original target files/index unchanged; temporary index disposed |
| Failure after actual apply | Preserve new target changes for diagnosis; never reset/reapply blindly |
| Replay onto dirty target | Reject; future receipt-aware application must verify prior capture |

Good: source changes VALUE, newer base changes FOOTER, result retains both. Base: empty capture.
Bad: use returned capture as implementation-report or bypass provider dirty-worktree admission.
`tests/git/test_seed.py` uses real temporary Git: both bases, empty/already-applied, conflicts,
source drift, dirty/forged role/root/Task, narrowed permission/deny, external driver/attribute,
preflight/post-apply process loss, source/index/ref preservation and dirty replay.

Wrong: successful `git apply --check --3way` means no conflict. A real Git test demonstrated that
check can succeed before actual application writes unmerged entries/conflict markers. Correct:
run a real three-way merge in an isolated index and reject its nonzero result before touching target.
Future CLI/dispatch/seed receipt and provider admission remain unimplemented.
