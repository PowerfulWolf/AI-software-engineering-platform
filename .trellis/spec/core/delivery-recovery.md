# Explicit delivery recovery — T044

## Scope / Trigger

Use when capturing interrupted Coder work or extending terminal delivery recovery. Historical T044
increments below remain the break-glass foundations. The normal production continuation boundary is
now the Delivery-level `ase request resume`; Task terminal guards, role cleanliness guards and
artifact gates remain unchanged.

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
4. Coder completes the intended diff/report and the platform finalizes the validated candidate;
   fresh independent QA/Reviewer validate that commit. Joint
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
source/target permissions, denies, aware creation time and `plan_sha256`. `permissions` proves the
historical capture; optional `target_permissions` binds the current Coder policy. `RecoveryAuthorization` contains the exact
approval command plus verifier-issued decision and `authorization_sha256`; one decision per plan.
`schemas/delivery-recovery.schema.json` describes plan/authorization union; model and wire validation
both reject extras. Integrity is not trusted origin: application ports must independently verify facts.

The service has no model, Task/state, Git apply or dispatch port. Propose and fresh approval verify
current facts and the exact capture. Human verification is followed by a second freshness check before
one complete receipt publish. Exact receipt replay needs no callbacks; execution gate separately
requires APPROVED and revalidates current source/target/capture. New Task identity is derived from plan
digest, not the old Task ID. No completed plan or receipt may be overwritten.

Store opens existing root without writes; initialize creates one directory under an existing sidecar.
Persist `scope.json` binding team/project/delivery and canonical project root, including after
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
| Tampered digest/patch/filename or cross-team/source | Fail closed |
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
Target permissions must be an exact-token subset of source read/write/command permissions and retain
the same network class. Omission preserves historical plan wire/digest and means source=target.

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
Team is selected by config; manifests must bind the exact team/project/code directory. Read
the terminal native journal and one MySQL REPEATABLE READ / CONSISTENT SNAPSHOT / READ ONLY
transaction for `tasks`, `state_events` and `dispatch_commits`; no repository constructor/DDL,
prepare, model, Task mutation or dispatch call. Reuse existing SQL row decoders and stage validators.

Require BLOCKED before candidate creation, attempt 1, exact Task revision, unchanged immutable
dispatch intent and contiguous state events ending IMPLEMENTING→BLOCKED. Read the native completed
Product approval, Designer/Planner commits and authoritative READY request revision; verify stage
digests, original preparation and semantic coverage through `validate_stage_chain`. Read the failed
Coder route and its exact ContextBundle, rather than accepting caller-supplied permissions. Missing
or successful routes, wrong role/base/attempt/context and route index gaps reject.

Discover parent ownership from team joint journals and deterministic child identity. A delegated
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
cross-team/missing run/context, corrupted Product/approval/Designer/Planner/parent records and
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

## Increment C3 — current native facts and authorized Task draft

### Scope and signatures

```python
NativeRecoveryFactsVerifier(config: ProductionConfig, environment: Mapping[str, str])
NativeRecoveryFactsVerifier.validate(plan: RecoveryPlan) -> None
NativeRecoveryFactsVerifier.inspect(plan: RecoveryPlan) -> NativeRecoveryFacts
AuthorizedRecoveryTaskBuilder(authorization: RecoveryAuthorizationService,
                             facts: NativeRecoveryFactsVerifier)
AuthorizedRecoveryTaskBuilder.build(plan_sha256: str) -> RecoveryTaskDraft
```

Implementations: `recovery/current.py`, `recovery/task.py`. Frozen in-process results, no new wire
Schema, record format or database migration. Native source result additionally exposes the already
verified original READY `request: ProjectRequest` and BLOCKED `task: Task`.

### Contracts

The concrete facts verifier resolves the C1 original chain and requires exact RecoverySource,
source Coder permissions and deny list. It independently compiles the current target Coder policy and
requires exact equality with approved `effective_target_permissions`; only the plan model's conservative
exact-token subset rule permits policy tightening. It never infers glob containment or permits expansion.
Resolve the exact persisted target preparation using versioned native stores; team/project and
organization roots/IDs cannot move. Load bounded regular profile/binding records, establish scope
before following embedded paths, and use native binding environment validation. Recompile current
team knowledge and project source baseline using `production_rules(team, knowledge)`, shared
with Production Host; construction preserves previous rule fields and digests. Production currently
has no structured project-rule provider; native documents remain opaque hash-bound references.

Require profile source revision and actual Git HEAD equal the proposed full target SHA, clean logical
checkout (tracked and untracked nonignored files), and old-base ancestry. Verify the captured Coder
through the configured project worktree root, not caller-provided authority. Two complete inspections
detect observed drift; they are not cross-store locks or an OS sandbox. Git calls reuse the adapter's
fixed environment/hooks/filter guards. No register, prepare, mkdir, DDL, model or store mutation.
Caller must first prepare the new base via normal production preparation and stop concurrent writers.

`RecoveryAuthorizationService` can now use this concrete `RecoveryFactsVerifier`; proposal, fresh
approval and execution admission all revalidate current facts. Approval must explicitly cover reuse
of the original solution against the exact proposed target preparation/base. Code cannot infer
semantic design compatibility from ancestry or Git merge success.

`RecoveryTaskDraft` contains `recovery_plan_sha256`, verified `facts`, a separately `rebound_request`
and NEW `task`. Builder requires approved current authorization before and after construction. Preserve
original request ID/text/status/creation time, rebind only preparation and update time in a NEW
in-memory value. Reuse exact Product/approval/Design/Plan via `derive_delivery_task`; never change their
digests or synthesize another Product approval. New Task ID is derived from RecoveryPlan, attempts=0,
base is the exact target; original constraints/max attempts/owner/labels are preserved.

Task metadata includes `recovery_plan_sha256`, `recovery_of_task_id`, `recovery_of_delivery_id`,
`recovery_source_checkpoint_sha256`, `recovery_original_request_sha256`,
`recovery_rebound_request_sha256`, `recovery_target_preparation_sha256`, plus normal stage references.
No Task/dispatch is persisted. The same-ID rebound request must NOT overwrite the original native
request revision. Future recovery execution receipt must seal it separately with authorization and
fresh allocation, then admit the seed; current draft is not executable dispatch authority.

### Validation and examples

| Case | Result |
|---|---|
| Exact same base/preparation or clean newer prepared descendant | Verified facts, original approved content retained |
| Wrong source/team/permissions/denies/preparation/binding/profile/base | Safe `RecoveryRejected` |
| Project code dirty, untracked file, rule/team knowledge drift | Reject current execution even after approval |
| Missing environment | Reject without initializing directories or DB |
| No approved recovery decision | Task draft rejected |
| Authorized exact replay | Equal NEW Task draft and request; no writes or models |

Good: offline interrupted Coder, normal preparation at newer commit, trusted fake recovery decision,
then deterministic new Task draft while all old source files/index/records remain unchanged. Base:
same-base check, or missing environment with zero effects. Bad: persisting the rebound request over
old history or feeding a draft directly to runtime without sealed fresh dispatch/seed admission.

Tests: `tests/recovery/test_current.py` uses real temporary Git/MySQL, fake Agents and human verifier;
assert missing approval, same/new base, stale base, narrowed permissions/denies, target dirt/untracked,
team knowledge selection, corrupted profile, unchanged source, deterministic draft and zero-write
snapshots. Existing native single/joint tests and Host regression cover shared rule extraction.

## Increment D1 — sealed Task input (not dispatch)

```python
RecoveryTaskRecord.create(draft: RecoveryTaskDraft,
                          authorization: RecoveryAuthorization) -> RecoveryTaskRecord
FileRecoveryStore.put_task_record(record: RecoveryTaskRecord) -> RecoveryTaskRecord
FileRecoveryStore.get_task_record(plan_sha256: str) -> RecoveryTaskRecord
RecoveryTaskSealingService(store: FileRecoveryStore, builder: AuthorizedRecoveryTaskBuilder)
RecoveryTaskSealingService.seal(plan_sha256: str) -> RecoveryTaskRecord
RecoveryTaskSealingService.require_current(plan_sha256: str) -> RecoveryTaskRecord
```

`recovery/records.py` defines wire kind `recovery_task_record`, version v0.1, fields
`recovery_plan_sha256`, `authorization_sha256`, `rebound_request`, `task`, `record_sha256`.
Separate `schemas/recovery-task-record.schema.json`; existing plan/authorization schema unchanged.
Record digest covers every field except itself. Validate request integrity, NEW Task/attempts0,
derived Task ID and recovery/project/request metadata; reject detected sensitive text, not redact it.
Store checks exact approved plan/authorization, target repository/base/preparation, timestamps and
source/stage references. Hashes are integrity, not independent trust in a caller's constructed Task.

Store uses existing private bounded no-follow/exclusive publication at `task-<plan_sha256>.json`.
One record per plan; exact replay is read-only, changed content conflicts. Authorization and plan
must already exist in the same durable scope. No independent unbound Task file, Task DB row, lease,
assignment, dispatch, worktree write or model call is created. Crash after atomic publication can
reopen the complete record; crash before it publishes nothing executable.

`seal` builds through current authorization/native facts, then publishes. `get_task_record` checks
stored integrity/lineage only and may return valid historical data after current code drifts.
`require_current` rebuilds through the approved facts gate and compares the entire record before
future consumers may proceed. There is no permanent grant in a stored hash and no lock implied by
the comparison. Dispatch still needs a durable current-fact/allocation fence and seed admission.

| Case | Required result |
|---|---|
| Valid approved draft | One sealed Task input; no dispatch or DB Task mutation |
| Close/reopen/exact replay | Same bytes and record; no model calls |
| Missing/rejected/other authorization or changed base/Task identity | Reject |
| Different Task text under decided record identity | Conflict, preserve first record |
| Corrupt JSON/envelope/hash or unsafe file | Fail closed via existing store guards |
| Current logical checkout becomes dirty | Historical get allowed; require_current rejects |

Good: real native offline fixture seals, reopens, revalidates with old source untouched. Base: exact
replay without another write. Bad: treat raw `get_task_record()` as a fresh dispatch permission.
Required tests: `test_task_record.py` wire/schema, missing auth, replay, conflict, corruption, secret,
Task status/attempt/ID/metadata/digest/base/auth rejection; `test_current.py` real native sealing and
stale-current rejection. Generic store crash/concurrency/path protections remain under full regression.

Schema integration guard: model-generated JSON Schema is not yet a repository-registered schema.
Every `schemas/*.schema.json` requires the Draft 2020-12 `$schema` and unique project `$id`; the global
contract registry loads all files by `$id`. `test_task_record.py` checks both plus schema validity;
the full contract suite verifies registry integration. Do not weaken the registry to tolerate a
missing identity. Preserve these fields when regenerating the record schema.

## Recovery execution contract (T044 remaining integration)

`RecoveryDispatchRecord` is a distinct allocation kind, not a fabricated Planner run. It binds the
sealed Task record, approved recovery plan, current workforce snapshot and three freshly computed
Coder/QA/Reviewer allocations. MySQL publishes it in the same `dispatch_commits` reservation domain
under the existing global lock; normal dispatch must count recovery reservations too. Original
native dispatch readers remain strict. Rebuild the sealed Task and rerun deterministic scheduling
inside the commit fence. Exact replay returns the first allocation, never a second Task.

The human CLI separates proposal, exact-digest approval and execution. Execution holds a nonblocking
recovery lock, verifies current original/target facts, materializes only the new Task, opens a fresh
Coder worktree and seeds the approved capture. A private immutable seed receipt binds dispatch,
plan and actual target capture. Missing receipt after an interrupted dirty apply rejects rather than
guessing whether application completed. Receipt replay verifies the exact seed; changed seed rejects.
Provider admission is an explicit Coder-only callback immediately before invocation; default clean
worktree policy is unchanged. It verifies Task/base/attempt/role/path/policy and receipt capture.
After provider invocation, existing runtime retry/verdict/candidate rules apply unchanged; no recovery
entry may reset terminal Tasks or fabricate a completion. An interrupted provider attempt is not
silently rerun from a seed receipt. QA and Reviewer remain independently bound to candidate SHA.

Validation: real temporary Git/MySQL plus offline providers must cover full DONE chain, replay,
cross-task/capture/policy drift, missing approval, changed source/target, stale workforce and global
reservation visibility, seed receipt interruption, and unchanged original terminal history. CLI
approval requires an explicit human decision for the exact persisted plan. Actual model calls and
delivery outcomes are separately recorded, not inferred from offline tests. No automatic merge.

### Implemented entry signatures and storage

`TeamHost.recovery_entry() -> NativeRecoveryEntry` in `recovery/entry.py`:

```python
propose(*, repository_root, delivery_id, failed_run_id, failed_context_id) -> tuple[RecoveryPlan, Path]
open_recovery_plan(config: ProductionConfig, path: Path) -> tuple[FileRecoveryStore, RecoveryPlan]
approve(path: Path, *, confirmed_plan: str, reference: str) -> None
execute(path: Path, *, route_factory=None) -> RetryResult
RecoveryAllocator.allocate(plan_sha256: str) -> RecoveryDispatchRecord
RecoverySeedService.seed(target: WorktreeRef) -> RecoverySeedRecord
RecoverySeedService.authorize(request: AgentRequest, workspace_root: Path) -> None
```

The test-only trusted `route_factory(seed)` injects offline adapters; production uses
`ConfiguredDeliveryRouteAdapterFactory(initial_workspace_admission=seed)`. Codex's default clean
guard remains unchanged when this dependency is absent. Public errors never include raw provider
text/secrets; CLI returns 2 for admission failures, 3 for a non-DONE runtime result, 0 for DONE.
Recovery currently admits exactly one CODEX_CLI route and requires live_model_execution=true.

Records live at `team/projects/<project>/state/recovery-<old-delivery>/` with plan/authorization/
task/seed/invocation `<plan-sha>` names plus scoped manifest and nonblocking advisory execution lock.
The lock covers all plans for this old delivery, not just one new Task. The trusted operator must
still stop the old executor and other code writers; this is not an OS sandbox or distributed lock.
`RecoveryDispatchRecord` reuses common task/project/phase/model fields but explicitly binds
recovery_plan_sha256 + recovery_task_record_sha256, without fabricated native Planner provenance.
MySQL JSON payload supports this second kind, requiring upgraded readers but no SQL DDL migration.
Native get_commit/_decode_commit stay strict; global reservation reads use the allocation union.

| Failure / replay | Required behavior |
|---|---|
| Missing exact human confirmation / config disabled / unsupported route | No provider |
| Stale source, target, sealed Task or policy | Reject before fresh execution |
| Exact existing allocation | Verify current Task binding; reuse first record/leases |
| Concurrent recovery execution | Nonblocking lock refusal, no second Coder |
| Missing seed receipt and dirty target | Reject; preserve both scenes |
| Wrong Task/base/attempt/path/permissions/context or changed seed | Reject provider admission |
| Provider previously admitted, including process loss | Refuse repeat Coder; inspect native Task/artifacts |
| Terminal recovery Task | Never reset; same terminal and original history remain |
| Child recovered to DONE | Report new candidate; old joint parent remains unchanged |

CaseStartedEvent for a Task carrying recovery_of_task_id is excluded from aggregate ADR; its Agent
events still persist and original failed case remains included. Never count a recovery as another
fresh demand success. Metadata/approval/dispatch/seed/invocation retain original lineage.

Good: `tests/recovery/test_execution.py` real Git/MySQL + offline Codex process yields four artifacts,
independent Coder/QA/Reviewer, candidate alignment, global capacity visibility, preserved old failure
and refused rerun. Base: CLI inspection creates no Host/organization/DB; exact seed/approval replay.
Bad: using old `project status` to inspect historical checkpoint after changing baseline (it reconciles
current preparation), or routing section names as source IDs. ContextBuilder prefixes user sources
with `source:`; restore `source:joint.approved_context` as source_id `joint.approved_context`.
The joint fixture verifies this source in every new ContextBundle without rerunning upstream models.
Tests also cover records/schema identity, allocation scope/role/hash tamper, file corruption,
seed drift, invocation lineage and scope-lock contention. Schema registry requires `$id/$schema`.

Testing note: accumulated pytest temporary Git trees can make automatic old-temp cleanup slow.
Use a fresh `mktemp -d` path as `--basetemp` for the test run; never delete a broad workspace or
mistake cleanup latency for a model call. Diagnose via bounded stack/progress, not repeated retries.

## D3: Explicit Coder reapplication on a clean base

### Scope / Signatures

For interrupted edits conflicting with a newer approved target. `RecoveryPlan.input_mode` is
optional `Literal["coder_reapply"] | None`; omission retains the historical strict Git seed path.
`NativeRecoveryEntry.propose(..., input_mode=None)`; CLI `ase recovery propose ... --coder-reapply`.
`recovery_context_sources(plan) -> tuple[ContextSource, ...]` supplies origin and optional patch.
`RecoverySeedService.seed/authorize` signatures and receipt schemas remain unchanged.

### Contracts

Mode participates in plan digest, new Task identity and exact human approval. None is omitted from
wire/digest; historical plans retain their identity. Never fall back to reapplication after a failed
Git seed under an old approval. Reapply starts at the clean exact target base, without git apply or
conflict markers. The seed record captures that empty initial workspace, not applied changes; store
and admission reject nonempty captures for this mode. Current source/target/permissions still validate.

The original full UTF-8 patch becomes required Coder-only `recovery.patch` with URI
`recovery://<plan-sha>/patch/<capture-sha>`. Ordinary routing/redaction/budget rules still apply;
immediately before provider admission require exact section URI/content/SHA and `truncated=false`.
Missing, redacted, truncated or altered patch rejects; overflow never silently drops it or increases
budget. Origin explains clean-base reapplication and treats old edits as untrusted input, not a
candidate/verdict. No old-worktree access or permission widening is granted to the Coder.
QA/Reviewer receive approved solution and the new candidate/report, not a second copy of the patch.
The normal candidate cleanliness/path checks, at-most-once invocation and independent verdict gates
are unchanged. This resolves code conflicts, not project normative conflicts (still human-owned).

### Validation matrix / examples

| Case | Result |
|---|---|
| No mode, Git conflict | Reject before provider, preserve source and clean target |
| Approved coder_reapply, same conflict | Clean target receipt + full patch context; Coder may adapt it |
| Mode altered under old digest/approval | Integrity/authorization rejection |
| Dirty target or forged nonempty receipt | Reject, never clean/reset |
| Missing/altered/truncated patch section | Reject before invocation receipt/provider |
| Required patch exceeds context cap | Existing budget BLOCKED; no provider or silent partial input |
| Invocation already recorded | Reject rerun; preserve history |

Good: real Git conflict fixture preserves newer base changes while offline Coder adapts original
edits and independent QA/Review validate one candidate. Base: absent mode preserves old digest and
strict seed behavior. Bad: catch every seed exception and launch Coder anyway.

### Tests / Wrong vs Correct

Tests cover mode Schema/digest/approval separation, required/role-scoped exact patch, budget overflow,
dirty receipt rejection, provider-admission tamper rejection, real conflict full delivery and original
history preservation. Reuse normal Git/Codex tests for dirty and candidate guards.

Wrong: `except WorktreeSeedRejected: start_coder()`.
Correct: explicitly propose/approve `input_mode="coder_reapply"`, capture a clean fresh base, route
and validate the complete approved patch, then use the normal Coder→QA→Reviewer runtime.

## D4: Source capture policy versus current target policy

### Scope / Trigger

Use this contract when a failed Coder worktree was created under an older permission policy and the
platform policy has since changed before recovery. The recovery proposal must remain executable after
safe policy tightening without treating historical capture authority as current execution authority.

### Signatures

```python
RecoveryPlan.permissions: AgentPermissions                 # exact historical/source policy
RecoveryPlan.target_permissions: AgentPermissions | None   # approved current target policy
RecoveryPlan.effective_target_permissions -> AgentPermissions
_delivery_role_permissions(role, allowed_paths, commands) -> AgentPermissions
```

### Contracts

- `permissions` remains the only policy used to verify/capture the original dirty worktree and to read
  historical plans. `target_permissions` is used for the fresh AgentDefinition, target seed, Context,
  tool policy and provider admission.
- New proposals compile target permissions from the current RepositoryProfile and original Task allowed
  paths. Both proposal and execution independently recompute that target policy through the same
  deterministic compiler and require exact equality with the approved value.
- A non-null target may only use exact read/write/command entries present in the source and must retain
  the source network class. Both policies prohibit state-change and merge. Conservative exact-token
  checks intentionally reject semantic glob guesses.
- `target_permissions=None` is omitted from wire/digest and means `target=source`, preserving old record
  identities. If current policy has tightened, such an old approval is stale and execution fails closed;
  a new proposal and exact human approval are required.
- Allocation may never choose the current permissions implicitly after approval. The newly built Coder
  definition must equal `effective_target_permissions` before worktree creation/provider admission.

### Validation & Error Matrix

| Case | Required result |
|---|---|
| Source has `git commit`, current target omits it | New hash-bound proposal; execution uses narrowed target and can reach QA |
| Target adds any read/write/command token | Plan validation rejects before persistence |
| Target changes network/state/merge authority | Plan validation rejects before persistence |
| Current target compiler differs after approval | Current-fact gate rejects; no Agent starts |
| Historical plan with no target field and unchanged policy | Original digest and behavior remain valid |
| Historical plan with no target field after tightening | Stale approval rejected; generate/approve a new plan |

### Good / Base / Bad Cases

- **Good**: historical capture is verified with its original policy while the fresh Coder receives the
  separately approved, strictly narrower current policy.
- **Base**: unchanged source/target policies remain separately hash-bound in a new proposal; legacy
  plans omit the field and preserve their identity.
- **Bad**: compare a fresh AgentDefinition directly with historical capture permissions, or silently
  replace an approved target policy with whatever the runtime currently computes.

### Tests Required

- Model/Schema tests assert optional-field legacy parity, digest separation, safe narrowing and every
  widening/network/state/merge rejection.
- Real Git/MySQL recovery starts the failed Task with legacy direct-commit commands, restores current
  no-direct-commit policy, then proves a new approved recovery reaches CandidateCommit, independent QA
  and Reviewer while old Task/worktree history stays unchanged.
- Current-fact tests mutate the approved target or current compiler result and assert rejection before
  Task/worktree/provider effects. Ruff, strict Mypy, full pytest, offline build and diff-check remain gates.

### Wrong vs Correct

```python
# Wrong: historical capture authority is assumed to be current execution authority.
assert fresh_coder.permissions == plan.permissions
```

```python
# Correct: verify source with source policy; execute only the independently approved current policy.
manager.verify_capture(plan.capture.to_capture(), plan.permissions)
assert fresh_coder.permissions == plan.effective_target_permissions
```

## E1: Candidate verification primitives (not a production entry)

### Scope / signatures

`recovery/verification.py`, `verification_records.py`, `verification_admission.py` implement:

```python
CandidateVerificationRunner.verify_candidate(inputs) -> CandidateVerificationResult
CandidateVerificationAdmission.propose(plan) -> CandidateVerificationPlan
CandidateVerificationAdmission.approve(command, *, human) -> RecoveryAuthorization
CandidateVerificationAdmission.validate_configuration(inputs, definitions) -> None
CandidateVerificationAdmission.admit(inputs, request) -> None
CandidateVerificationAdmission.complete(result) -> CandidateVerificationCompletion
VerificationFacts.validate(plan) -> None
```

### Contracts

Inputs pin Task ID/revision/digest, original plan/implementation IDs/digests, full candidate SHA
and historical run IDs. This first increment accepts only terminal QA failures directly following
`candidate_ready` with initial non-superseding implementation. It checks event continuity, artifact
kind/Task/base/parents/candidate/criteria, fresh run IDs and historical producer independence.
Task and events remain unchanged: no terminal reset, record_attempt, synthetic Coder or DONE event.
The runner reuses SerialOrchestrator's role invocation guards, not run_task/_transition. Context
honestly contains the original terminal Task; only QA then Reviewer run. Identity/criteria validation
precedes sealing. FAIL/REJECT stops, errors propagate, no automatic retry/Coder loop.
`CandidateVerificationResult.verified` is not a Handoff or joint completion authority.

`schemas/candidate-verification.schema.json` defines plan/invocation/completion/authorization union.
Plan binds scope, inputs, native checkpoint/dispatch/approved-stage/current-policy hashes, optional
paired parent ID/hash, exact role definitions and creation time. Production must independently resolve
these hashes through VerificationFacts; they do not establish origin. Definitions including model,
permissions and timeout must match approval. Verifiers cannot merge/change Task state.

FileRecoveryStore adds separate verification-plan/verification-authorization/verification-qa/
verification-reviewer categories using existing private bounded no-follow/exclusive publication.
Old categories and records are unchanged. Approval calls a trusted human verifier, rechecks facts,
and preserves exact command replay. The local verifier authorizes candidate verification only.
Admission locks scope, revalidates facts/approval/inputs, refuses an existing role receipt and seals
the complete request BEFORE provider invocation. Process loss after admission cannot authorize a
repeat. Reviewer requires this plan's sealed QA PASS bound to the admitted QA run/context/Agent and
candidate. Admission proves invocation, never completion. Production facts additionally check
allocation, candidate/worktree and policy freshness through `NativeVerificationFacts` and the MySQL
verification reservation boundary.

### Validation matrix / examples

| Case | Result |
|---|---|
| Exact candidate, QA PASS, Review APPROVE | Verification facts; original failure preserved |
| Missing approval, stale input, changed model/permissions | No provider |
| Invalid output/provider failure/QA FAIL/Review REJECT | Stop; no Coder or Task DONE |
| Reopen after consumed admission, including process loss | Refuse repeat invocation |
| Exact approval command replay | Original receipt; no repeat human callback |
| Historical run reuse/self-review/foreign scope/digest tamper | Fail closed |

Good: offline independent verifiers retain original candidate and report provenance. Base: rejection
returns findings. Bad: reset FAILED or clone a report as a fake Coder output under a new Task.
Correct: a separately authorized verification retains original identity and records each invocation.

### Tests / production boundary

`test_candidate_verification.py`: success, drift, authority, output/provider failures, rejection,
self-review and run reuse; original Task/events unchanged. `test_verification_admission.py`: real
file receipts, reopen/replay, interruption, stale facts, model binding and Schema parity. Existing
store tests retain publication/path protections. Ruff, Mypy and regression remain required.

Completion embeds sealed QA/Review reports and binds the exact authorization and per-role invocation
digests. QA FAIL permits no Review; QA PASS requires Review before completion. Store read and write
both check Task/candidate/producer/run/context/parents/time against admissions. `complete` independently
checks artifact-store equality and approved plan/implementation digests, rejects conflicting replay,
and returns an identical existing completion without creating another run. A completion is not a
Task DONE event or a joint delivery success. Provider failure leaves an invocation with no completion.

`verification_snapshot.read_candidate_snapshot` uses a consistent read-only MySQL transaction, never
repository initialization/DDL. Legacy checkpoint Task status/revision may lag SQL; immutable dispatch
identity must still match. Event count, continuity, timestamps and final post-candidate QA failure must
match actual Task facts. A checkpoint revision ahead of SQL is rejected. This is not upstream approval
validation and cannot independently authorize execution.

The native source/current-fact resolver, fresh allocation/verifier worktrees, demand association and
CLI are implemented by the production entry described below. E1 alone still neither changes
production requirements nor proves a live model delivery.

### Independent verification reservation

`MySqlDispatchAuthority.reserve_verification(repository_id, source_task_id, plan_sha256,
validate_current, build)` serializes with ordinary dispatch using the global authority lock.
The trusted builder must run Scheduler/ModelRouter against the supplied fresh snapshot; the
current-fact callback must validate approval, original candidate and historical Agent independence.
`VerificationReservation` permits exactly QA and Reviewer and distinct scoped assignments/leases.
`verification_reservations` is an additive InnoDB table keyed by plan digest, with typed JSON and
nullable completion digest. Original Task/events/dispatch are untouched.

The shared snapshot always retains verification assignment history. An uncompleted reservation's
leases remain in the capacity snapshot even when its original Task is terminal. Completion removes
only active occupancy, not assignments or SQL history. Normal Task dispatch filtering is unchanged.
`complete_verification(plan_sha256, completion_sha256, validate_completion)` uses the same lock;
the trusted callback must resolve sealed completion and validate its invocation/allocation binding.
Exact completion replay is allowed; conflicting completion and re-reservation after release reject.
No completion means no implicit success/release; existing lease expiration policy still applies.

Good: FAILED original Task plus live verification occupies both verifier leases. Base: completion
releases those leases while retaining assignments. Bad: infer verification liveness from Task status,
or call release with an unvalidated digest.
`test_verification_reservation.py` exercises the shared SQL snapshot decoder with offline row fixtures.
Real MySQL transaction/concurrency verification is still required before production use.

The targeted MySQL reservation suite now covers terminal BLOCKED/FAILED/DONE origins, concurrent
exact reservation replay, retained live occupancy, idempotent completion and rejection of reuse
after completion. It uses a dedicated test database, never the production demand database.

### Native candidate source inspection

`NativeCandidateSourceReader.inspect(scope) -> NativeCandidateSource` reads team/project binding,
native checkpoint/intake, a read-only SQL runtime snapshot, sealed original artifacts and historical
route run IDs. `read_approved_stages` is shared with pre-candidate recovery and retains the exact
Product/approval/Design/Planner/dispatch provenance checks. Joint ownership is resolved through the
existing derived-input and approval delegation checks. A blocked joint parent may legitimately retain
an older child observation while the native child appends recovery checkpoints; that observation must
be the exact record at its sequence in the validated native hash chain. Source and upstream facts are
checked again before return. The public reader wraps errors without exposing DSNs or provider output.

The shared ancestry predicates are:

```python
checkpoint_is_ancestor(
    history: tuple[ProjectDeliveryCheckpoint, ...],
    checkpoint: ProjectDeliveryCheckpoint,
) -> bool

checkpoint_sha256_is_ancestor(
    history: tuple[ProjectDeliveryCheckpoint, ...],
    checkpoint_sha256: str,
) -> bool
```

Callers must load a fully validated, delivery-scoped history and confirm its final record is the
current checkpoint before using either predicate. The object predicate is required when the caller
has the historical checkpoint body; the digest predicate is only for sealed artifacts that bind the
checkpoint digest.

Legacy QA failure events may reference Task.base_ref; accept that or the exact candidate, but no
third revision. Candidate identity must come from candidate_ready plus matching sealed implementation,
not from a stale checkpoint or terminal failure event. Source inspection does not check current model
allocation/worktree availability, create approval, invoke providers, or confer execution authority.

## E2: Production candidate verification entry

```python
CandidateVerificationEntry.propose_project(repository_root, delivery_id) -> (plan, path)
CandidateVerificationEntry.approve(path, confirmed_plan, reference) -> None
CandidateVerificationEntry.execute(path) -> CandidateVerificationCompletion
open_candidate_verification_plan(config, environment, path) -> (store, plan)
DispatchDeliveryAgentAdapter(..., plan_adapter: ExecutionPlanAgentAdapter | None, ...)
```

Top-level CLI commands are `verify-propose`, `verify-inspect`, `verify-approve`, and `verify-run`.
Proposal resolves the registered project, reads exact native/joint source facts, creates a distinct
`execution_task_id`, recomputes QA/Reviewer Scheduler and ModelRouter decisions, and exclusively
publishes a digest-bound plan. `current_policy_sha256` covers the exact role definitions and every
enabled primary/fallback route, so changing a fallback model is approval drift. Inspection opens the
exact team/project path with no-follow bounded
reads and does not initialize Team Host or invoke models. Approval seals exact human confirmation.
Only run invokes providers, and only in QA then Reviewer order.

`VerificationReservation` contains both `source_task_id` and distinct `task_id`. The former binds the
terminal Task/candidate; the latter scopes fresh Assignment/Lease/worktree identities so the shared
capacity snapshot does not release active verifier work merely because the source Task is terminal.
The adapter opens QA and Reviewer worktrees at the pinned candidate, disallows Coder, and closes only
clean worktrees. Original Task, events, dispatch, artifacts, candidate commit and parent checkpoint
remain unchanged.

Normal `DeliveryAllocation` composition requires a non-null `ExecutionPlanAgentAdapter` because it
materializes the plan from a `NEW` Task. `VerificationReservation` composition requires
`plan_adapter=None`: the approved PlanArtifact already exists and the source Task is intentionally
terminal. Candidate verification must reject Orchestrator and Coder requests before worktree or
provider creation. Never normalize the terminal source Task to `NEW` merely to satisfy the planning
adapter; doing so would replace historical identity instead of verifying the preserved candidate.

The plan binds optional joint parent delivery/checkpoint; completion binds that plan plus sealed
invocation/report digests. This is the audit association with the original demand. It does not rewrite
the historical child or parent checkpoint into DONE, run joint integration automatically, merge,
push, or deploy. A caller may accept the independently verified candidate through its normal human
delivery policy; future joint-projection support must consume this record explicitly rather than forge
a successful native Task.

Validation points: proposal and approval re-read native facts and candidate availability; run repeats
that check inside the MySQL authority fence and requires current allocation to equal approved role
definitions. Invocation records are published before each provider call. Missing approval, policy or
candidate drift, allocation difference, reused role admission, QA FAIL, Review REJECT and uncertain
provider completion fail closed without Coder or terminal Task mutation. Exact approval and completion
replay are idempotent; an admitted role with unknown result is not retried automatically.

| Delivery adapter composition | Required result |
|---|---|
| Normal allocation + planning adapter | Planning/Coder/QA/Reviewer path remains available |
| Normal allocation + no planning adapter | `ProductionConfigError` before any role run |
| Verification reservation + no planning adapter | QA/Reviewer-only composition is valid |
| Verification reservation + planning adapter | `ProductionConfigError`; do not validate terminal Task as `NEW` |
| Verification reservation + Orchestrator/Coder request | Explicit refusal before worktree/provider |

Good: a terminal candidate uses the existing sealed PlanArtifact and invokes only QA then Reviewer.
Base: the normal delivery path still requires its planning adapter. Bad: constructing
`ExecutionPlanAgentAdapter(task=terminal_task, ...)` inside candidate verification; its correct `NEW`
guard reports a misleading planning-lineage failure before QA starts.

`tests/manager/test_production_delivery.py` must assert both sides of the constructor
invariant and the explicit verification Orchestrator refusal. Candidate verification regression must
also keep QA/Reviewer invocation records empty when composition fails before provider admission.

```python
# Wrong: reuse initial-delivery planning composition for a terminal historical Task.
plan_adapter = ExecutionPlanAgentAdapter(task=source.runtime.task, ...)

# Correct: the sealed plan is already an input fact; compose only independent verifiers.
adapter = DispatchDeliveryAgentAdapter(
    dispatch=verification_reservation,
    definitions=approved_definitions,
    plan_adapter=None,
    ...,
)
```

### E2.1 Append-only verifier runs and successor plans

#### Scope / Trigger

Use after a verification role has been durably admitted. The native candidate reader will then see
that role's route attempt and, after success, its report as new run facts even though the candidate,
terminal Task and approved upstream chain did not change.

#### Signatures

```python
_verification_inputs_are_current(
    approved: CandidateVerificationInputs,
    current: CandidateVerificationInputs,
    admitted_run_ids: Set[str],
) -> bool
NativeVerificationFacts(..., store: FileRecoveryStore | None = None).validate(plan) -> None
CandidateVerificationEntry.execute(path) -> CandidateVerificationCompletion
```

#### Contracts

- Every run ID pinned before proposal remains present. Its removal is source drift.
- A run ID added after proposal is current only when an invocation for that exact plan and role was
  durably published before the provider call. An unrelated run remains source drift.
- Candidate, Task revision/digest, artifact lineage, dispatch, stage chain, parent and policy
  comparisons remain exact. `prior_run_ids` may add only runs admitted by this plan. The native
  Delivery checkpoint may advance only when the plan-bound checkpoint is still an exact ancestor in
  the validated hash chain and all pinned candidate inputs above remain unchanged; a digest that is
  absent, replaced or from another delivery is drift.
- A sealed completion may replay without another provider call. An invocation without a sealed
  completion has consumed that plan's at-most-once role slot and `verify-run` must stop before SQL
  allocation/worktree/provider effects with the run ID and successor-plan instruction.
- Continue the same candidate by running `verify-propose` again for the same project/delivery,
  explicitly approving its new digest, then running that new plan. The new plan pins the failed run
  in `prior_run_ids` and creates a fresh execution Task/run identity; it never reruns Coder.
- An expired Lease restores capacity automatically. Immediate durable release for a conclusively
  failed provider attempt requires a separately sealed failure-resolution contract; do not overload
  a completion digest or silently release an outcome whose completion is uncertain.

#### Validation & Error Matrix

| Current fact | Result |
|---|---|
| Exact approved inputs, no invocation | Current; first QA may be admitted |
| Approved history plus this plan's admitted QA/Reviewer run | Current; continue/complete |
| Native Delivery appended bookkeeping checkpoints; pinned candidate inputs unchanged | Current |
| Invocation exists but no sealed completion | Refuse same plan before provider; propose successor |
| Historical run removed or foreign run added | `verification source changed after proposal` |
| Candidate/Task/artifact/policy changed or bound checkpoint not in current chain | Exact drift rejection |

#### Good / Base / Bad Cases

- Good: QA run is sealed, its route/report becomes visible, Reviewer starts once, then completion
  replays without a provider call.
- Base: a typed `RATE_LIMITED` QA attempt consumes the old plan; a newly approved successor verifies
  the same candidate without Coder.
- Bad: compare the whole current `CandidateVerificationInputs` byte-for-byte after admitting QA, or
  rerun the old request because its provider result was a known failure.

#### Tests Required

- Assert same-plan admitted additions are accepted, foreign additions and historical removals fail,
  and changing any non-run input still fails.
- Assert a consumed invocation produces the successor-plan message and makes zero additional adapter
  calls. Retain the existing process-loss and duplicate-admission tests.
- Exercise QA PASS -> Reviewer -> completion with the native facts implementation so each
  post-provider freshness check observes its own append-only run facts.

#### Wrong vs Correct

```python
# Wrong: QA creates a route fact, so this rejects the platform's own admitted invocation as drift.
if current_inputs != plan.inputs:
    raise RecoveryRejected("verification source changed after proposal")

# Correct: exact non-run facts + preserved history + additions authorized by this plan only.
if not _verification_inputs_are_current(
    plan.inputs, current_inputs, admitted_run_ids_for(plan.plan_sha256)
):
    raise RecoveryRejected("verification source changed after proposal")
```

## Scenario: Delivery-level universal resume and candidate remediation

### 1. Scope / Trigger

Use this contract whenever the public Manager continuation entry, candidate verification,
post-verdict remediation, joint-child recovery, or adoption of a terminal Task result changes. The
unit of continuation is a Delivery aggregate. One already-admitted provider invocation remains
at-most-once; `resume` may create a new plan, Run, or successor Task but must never replay that
invocation identity.

### 2. Signatures

```python
class ResumeProjectDelivery(DomainModel):
    delivery_id: DeliveryId
    approved_plan_sha256: Sha256 | None = None
    approval_reference: NonEmptyStr | None = None

TeamHost.resume_delivery(
    command: ResumeProjectDelivery,
) -> DeliveryResumeResult | JointDeliveryResult

DeliveryResumeController.resume(command: ResumeProjectDelivery) -> DeliveryResumeResult
UnifiedProjectEntryService.begin_continuation(
    dispatch: ContinuationDispatchRecord,
    plan: CandidateVerificationPlan,
    completion: CandidateVerificationCompletion,
    *,
    at: datetime,
) -> ProjectDeliveryResult
UnifiedProjectEntryService.finish_continuation(
    dispatch: ContinuationDispatchRecord, delivery: RetryResult, *, at: datetime
) -> ProjectDeliveryResult
UnifiedProjectEntryService.accept_verification(
    plan: CandidateVerificationPlan,
    completion: CandidateVerificationCompletion,
) -> ProjectDeliveryResult

NativeRecoverySourceReader.discover_failed_coder(scope: RecoveryScope) -> NativeRecoverySource
NativeRecoveryEntry.propose_delivery(
    checkpoint: ProjectDeliveryCheckpoint,
) -> tuple[RecoveryPlan, Path]
NativeRecoveryEntry.resume_execution(path: Path) -> NativeRecoveryExecution
RetryingOrchestrator._run_coder_with_retries(
    task: Task,
    plan: PlanArtifact,
    previous: ImplementationReportArtifact | None,
    qa: QaReportArtifact | None,
    review: ReviewReportArtifact | None,
    progress: CoderProgressArtifact | None,
    seen_run_ids: set[str],
    run_ids: list[str],
    context_ids: list[str],
) -> tuple[ImplementationReportArtifact | CoderProgressArtifact, Task, str] | BlockedResult
DispatchRoleWorktreeCoordinator.open_coder(
    dispatch: DeliveryAllocation,
    definitions: Mapping[AgentRole, AgentDefinition],
    *,
    source_revision: str | None = None,
    recover: bool = False,
) -> RoleWorktreeBinding
verification_snapshot.candidate_event(
    events: tuple[StateEvent, ...],
) -> tuple[int, StateEvent]
verification_snapshot.terminal_candidate_event(
    task: Task,
    events: tuple[StateEvent, ...],
) -> StateEvent
resolve_planner_dispatch(
    current: DeliveryAllocation,
    allocations: Mapping[str, DeliveryAllocation],
    history: tuple[ProjectDeliveryCheckpoint, ...],
) -> DispatchCommitRecord
allocation_preparation_sha256(
    allocation: DeliveryAllocation,
    original_preparation_sha256: str,
) -> str
UnifiedProjectEntryService.begin_recovery(
    plan: RecoveryPlan, dispatch: RecoveryDispatchRecord, *, at: datetime
) -> ProjectDeliveryResult
UnifiedProjectEntryService.finish_recovery(
    plan: RecoveryPlan,
    dispatch: RecoveryDispatchRecord,
    delivery: RetryResult,
    *,
    at: datetime,
) -> ProjectDeliveryResult
```

CLI:

```text
ase request resume DELIVERY_ID
ase request resume DELIVERY_ID --approve-plan PLAN_SHA256 \
  --approval-reference AUDIT_REFERENCE
```

`ContinuationDispatchRecord` is stored in the ordinary MySQL `dispatch_commits` authority and in
`schemas/recovery-execution.schema.json`. Required lineage fields are:

```text
kind = continuation_dispatch
continuation_kind = verification_remediation
continuation_sha256                 # rejected verification completion
continuation_plan_sha256            # exact approved verification plan
continuation_context_sha256         # sealed completion + candidate patch context
target_preparation_sha256           # current project preparation used by successor
source_delivery_id / source_task_id
source_base_revision / source_revision / source_dispatch_id
task / phases[Coder, QA, Reviewer] / workforce_snapshot_sha256
dispatch_sha256
```

### 3. Contracts

- `approved_plan_sha256` and `approval_reference` are an all-or-none pair. Approval is
  for an exact emitted plan, not for the candidate or Delivery in general.
- PREPARING through DELIVERING reuse the existing immutable stage artifacts and continue only the
  next unconsumed operation. Human gates and DONE return current facts without a provider call.
- A classified pre-Task failure records `failed_stage`; resume reopens that exact stage and clears
  the failure fields before invoking only its next operation.
- A dispatch may have materialized its Task before Delivery runtime composition fails. A terminal
  checkpoint whose Task cursor is exactly `NEW`, revision `0`, has no candidate and has zero
  Delivery attempts is a pre-invocation failure, not a failed Coder. Resume reopens `DELIVERING`
  before failed-Coder discovery. Legacy checkpoints may omit `failed_stage`; only this complete
  fact conjunction permits inferring `DELIVERING`. Runtime then reconciles the native Task: a
  concurrently advanced or terminal Task is resumed or adopted through its normal event/artifact
  gates rather than treated as a new invocation.
- A terminal Coder Task without a candidate is discovered from its exact final failed route and
  Context. Resume captures the preserved worktree and emits an exact `RecoveryPlan`; approval starts
  a new recovery Task and attaches its terminal result to the original Delivery hash chain.
- Recovery and remediation dispatches are successor allocations, not new Planner approvals.
  `resolve_planner_dispatch` must follow their digest-bound Delivery history to the original Planner
  dispatch; `allocation_preparation_sha256` separately validates the preparation used by the current
  successor Task. If that successor Coder also fails before a candidate, the same `resume` flow emits
  another fresh recovery plan and Task instead of assuming only one recovery attempt.
- A terminal Task with a durable candidate first gets independent QA/Reviewer verification. Missing
  approval returns `VERIFICATION_APPROVAL_REQUIRED` with the exact plan path/digest and next command.
- A conclusive QA criterion/test `FAIL` or Reviewer rejection routes the next Coder request from the
  preceding candidate commit, not from the Task's original `base_ref`. A QA environment/tool
  `ERROR` with no criterion/test `FAIL` is inconclusive and routes to a fresh verification plan,
  never Coder. A remediating implementation must still supersede the preceding implementation
  Artifact and include the verdict Artifact as a parent. A transient failure before the first
  candidate continues to use `task.base_ref`; a Coder-progress continuation continues to use its
  checkpoint revision.
- A process restart may reopen an existing clean Coder worktree only when its HEAD equals the exact
  `AgentRequest.source_revision`. `open_coder(source_revision=None)` retains the first-run behavior
  and resolves to `task.base_ref`; recovery callers must pass the request revision explicitly.
- A terminal retry Task can retain a trustworthy Candidate V1 even when its latest checkpoint has
  `candidate_revision = null`: the accepted candidate is the latest validated `candidate_ready` or
  `candidate_recovered` event plus its sealed implementation/plan lineage. A valid terminal tail is
  either a direct QA/Reviewer terminal failure, or QA FAIL/Review REJECT routed to Coder followed by
  a terminal Coder failure. `resume` verifies that retained candidate before attempting dirty-worktree
  failed-Coder recovery.
- A nullable Delivery checkpoint `candidate_revision` is a cursor projection, not Candidate authority.
  `begin_continuation` and `accept_verification` may consume a retained Candidate only when the exact
  verification plan and completion are supplied together: the plan's native checkpoint must be an
  ancestor of the current validated Delivery hash chain; Delivery/project/Task/dispatch identities,
  implementation parent, QA/Review candidate and direct-parent lineage must match. The current
  checkpoint must identify a terminal `DELIVERING` failure with a BLOCKED/FAILED Task. If the cursor
  contains a non-null Candidate, exact equality remains mandatory. Successful verification restores
  the proven Candidate into the DONE checkpoint; remediation starts a new Candidate-empty Task.
- An invocation with no sealed completion is ambiguous and cannot be replayed. A later `resume`
  proposes a new plan/Run for the same candidate and requires a new exact approval.
- PASS + APPROVE may seal the original Delivery DONE without rewriting its terminal Task; the
  checkpoint binds both verification plan and completion digests.
- QA FAIL or Review REJECT creates exactly one deterministic successor Task and dispatch from the
  completion digest. Required Coder context contains the sealed completion plus a bounded,
  secret-scanned diff from the original base to Candidate V1.
- The successor Task starts on the current clean project preparation/base and executes the normal
  serial Coder → QA → Reviewer runtime. Candidate V2 is recorded on the original Delivery hash chain;
  the source Task/events remain terminal and unchanged.
- If the process dies after the successor Task becomes terminal but before the Delivery checkpoint
  is appended, `run_prepared_allocation` reconstructs `RetryDeliveryResult`/`BlockedResult` from the
  Task event stream and sealed artifacts. It performs zero provider calls before the checkpoint is
  adopted.
- A joint parent resumes one incomplete child at a time, retains DONE children, then re-enters joint
  integration only after the complete candidate set exists.
- No resume path merges, pushes, deploys, relaxes project policy, silently changes team knowledge,
  or overwrites historical Task/checkpoint/verdict records.
- `DeliveryResumeResult.outcome` must reflect the returned checkpoint. Any
  `WAITING_PRODUCT_REPLY`, `WAITING_PRODUCT_APPROVAL`, `WAITING_HUMAN`, `BLOCKED`, or `FAILED`
  checkpoint is returned as `WAITING_HUMAN`; labels such as `RECOVERED` or `REMEDIATED` are forbidden
  for these terminal/human-gated states.

### 4. Validation & Error Matrix

| Durable condition | Result | Provider calls |
|---|---|---:|
| PREPARING–DELIVERING, next operation unconsumed | Continue current stage | Next role only |
| WAITING_PRODUCT_REPLY / APPROVAL / WAITING_HUMAN | Typed human gate | 0 |
| DONE | Exact checkpoint replay | 0 |
| BLOCKED/FAILED before Task, retryable `failed_stage` | Reopen exact stage | Next stage only |
| BLOCKED/FAILED after Task materialization, Task `NEW` revision 0, no candidate/Delivery attempt | Reopen `DELIVERING`; legacy `failed_stage` may be absent | Normal runtime reconciliation |
| BLOCKED/FAILED Coder, no candidate | Publish exact recovery plan | 0 |
| Recovery/remediation Coder fails again without candidate | Follow allocation ancestry; publish next recovery plan | 0 |
| QA/Review routed Coder restarts at old Task base while worktree retains Candidate V1 | Reject before provider admission; implementation bug | 0 |
| Terminal retry Task retains a validated earlier candidate | Publish candidate-verification plan before failed-Coder recovery | 0 |
| Approved recovery plan, no invocation | Fresh recovery Task: Coder → QA → Reviewer | 3+ bounded retries |
| Recovery Task already terminal, Delivery not updated | Adopt terminal Task result | 0 |
| Candidate, no current verification plan | Publish plan and exact approval command | 0 |
| Plan digest mismatch or missing audit reference | Keep current plan awaiting approval | 0 |
| Approved plan, no invocation | QA; Reviewer only after QA PASS | 1–2 |
| Admitted invocation, no completion | Publish successor plan; require approval | 0 |
| PASS + APPROVE completion | Bind verified candidate and mark Delivery DONE | 0 |
| QA criterion/test FAIL or Review REJECT completion | Deterministic continuation dispatch and fresh serial Task | 3+ bounded retries |
| QA only NOT_TESTED/ERROR, no criterion/test FAIL | Fresh verification plan and exact approval | 0 |
| Current cursor candidate null, exact retained-candidate plan/completion proof | Accept DONE or begin remediation according to verdict | 0 before the selected next operation |
| Current cursor candidate null without terminal DELIVERING marker, ancestor, or exact lineage | `continuation does not match the terminal candidate` | 0 |
| Successor Task terminal, Delivery still DELIVERING | Rebuild result and append checkpoint | 0 |
| Project/preparation/policy/candidate/parent drift | Fail closed with safe error | 0 |
| Candidate patch secret/non-UTF-8/>1 MiB | `RecoveryRejected` before allocation | 0 |

### 5. Good / Base / Bad Cases

- Good: Candidate V1 reaches QA FAIL, the completion creates one successor Task, Coder produces
  Candidate V2, independent QA/Reviewer approve it, and the original Delivery becomes DONE.
- Base: the successor Task is already DONE after a process loss; replay reconstructs its four final
  artifacts and appends the missing Delivery checkpoint without opening role worktrees.
- Base: a failed Coder has no candidate but its attempt-1 worktree and final route ledger are intact;
  resume discovers the Run/Context and requires exact approval before reusing those edits.
- Base: dispatch materialized a pristine Task and runtime composition stopped before admission;
  resume re-enters Delivery without asking failed-Coder recovery to invent a missing identity.
- Base: QA fails Candidate V1, the routed Coder then stops before Candidate V2; resume discovers the
  sealed Candidate V1 from Task events even though the latest Delivery checkpoint has no candidate.
- Bad: reset the old Task to IMPLEMENTING, run Coder against Candidate V1 before independent
  verification, restart a routed Coder from `task.base_ref`, report `REMEDIATED` with a BLOCKED
  checkpoint, reuse a consumed verifier request, or treat a digest supplied by CLI as authority.

### 6. Tests Required

- `tests/recovery/test_resume.py`: real Git + MySQL, three RATE_LIMITED QA runs, exact plan approval,
  independent QA FAIL, deterministic successor Task, Coder/QA/Reviewer order, Candidate V2, preserved
  original BLOCKED Task, process loss after successor DONE, and zero-call replay.
- The same suite must cover failed-Coder discovery, recovery-plan approval, a fresh serial recovery
  Task and attachment of its candidate to the original Delivery. It must also make the first recovery
  Coder fail, then prove a second `resume` creates a new plan/Task and reaches DONE.
- `tests/recovery/test_delivery_continuation.py`: checkpoint attachment, target preparation adoption,
  result sealing and exact replay without duplicate journal entries; both verification acceptance and
  remediation must accept the exact retained Candidate when the latest cursor is null, while an empty
  cursor without the terminal DELIVERING proof must fail closed.
- `tests/e2e/test_unified_project_entry.py`: current and legacy Delivery-startup checkpoints with a
  pristine materialized Task resume through the public controller and never call recovery/verification.
- `tests/recovery/test_execution_records.py`: continuation digest/metadata/phase validation plus
  Draft 2020-12 schema validation.
- `tests/orchestration/test_retry.py`: after QA FAIL, the second Coder request is bound to Candidate
  V1 while the first Coder request remains bound to `task.base_ref`.
- `tests/role_workspace/test_role_workspace.py`: process restart reopens the Coder worktree against
  the retry request revision rather than the frozen Task base.
- `tests/recovery/test_verification_snapshot.py`: QA FAIL → Coder → terminal failure retains a valid,
  discoverable prior candidate; malformed or foreign tails remain rejected.
- `tests/recovery/test_candidate_verification.py`: the admitted QA/Reviewer runner consumes that same
  shared terminal-tail interpretation and verifies the retained candidate without mutating the Task.
- Resume tests must assert that a BLOCKED recovery result is `WAITING_HUMAN`, never `RECOVERED` or
  `REMEDIATED`.
- Joint tests must retain DONE children and continue only incomplete children before integration.
- Source Mypy, Ruff/format, offline package build, and the full MySQL suite are release gates.

### 7. Wrong vs Correct

```python
# Wrong: the Task finished before the Delivery checkpoint, so invoke Runtime again.
runtime.run_task(task.id)  # TaskNotRunnable or duplicate provider side effect

# Correct: materialize idempotently, then adopt authoritative terminal facts.
terminal = _terminal_delivery_result(repository, artifact_store, task.id)
if terminal is not None:
    return terminal
return runtime.run_task(task.id).result
```

```python
# Wrong: QA FAIL mutates/reopens the historical Task.
old_task.status = TaskStatus.IMPLEMENTING

# Correct: immutable completion selects one deterministic successor allocation.
dispatch = authority.commit_continuation(
    continuation_sha256=completion.completion_sha256,
    validate_current=validate_current,
    build=build_successor,
)
```

```python
# Wrong: a nullable checkpoint projection erases a Candidate already proven by Task events/artifacts.
if checkpoint.candidate_revision != dispatch.source_revision:
    reject()

# Correct: a non-null cursor must match; a null cursor needs the complete sealed proof chain.
entry.begin_continuation(dispatch, verification_plan, completion, at=completion.completed_at)
```

```python
# Wrong: every Coder attempt is declared to start from the original Task base.
request = build_agent_request(candidate_revision=None)

# Correct: verdict-driven Coder work starts from the candidate that was actually reviewed.
request = build_agent_request(
    candidate_revision=(previous.content.commit_sha if previous is not None else None)
)
```

```python
# Wrong: a BLOCKED checkpoint is presented to the operator as successful remediation.
return DeliveryResumeResult(outcome=REMEDIATED, checkpoint=blocked)

# Correct: the checkpoint determines the externally visible wait state.
if checkpoint.stage in HUMAN_GATED_OR_TERMINAL_FAILURE_STAGES:
    outcome = WAITING_HUMAN
```

Root cause (B/C/D/E): retained-Candidate discovery was added at the Task event/Artifact layer, but
the downstream Delivery entry still treated its nullable checkpoint projection as authoritative.
The original continuation test covered only a checkpoint that directly stored the Candidate, so the
cross-layer propagation gap survived. The prevention mechanism is a proof-carrying continuation
signature plus paired positive/negative tests at the Delivery entry seam; never fix this by merely
dropping the Candidate comparison or by rewriting historical checkpoints.

## Scenario: QA environment-aware verification recovery

### 1. Scope / Trigger

Use when QA needs writable tool scratch, a sealed QA report is inconclusive because the verifier
environment failed, or an older platform version already created a failed Coder continuation from
such a report. This contract must not weaken candidate immutability or convert genuine defects into
verification retries.

### 2. Signatures

```python
_sandbox_mode(role: AgentRole) -> str
CandidateVerificationCompletion.disposition -> CandidateVerificationDisposition
retained_candidate_checkpoint(history, dispatch) -> ProjectDeliveryCheckpoint
read_candidate_source_snapshot(config, environment, history) -> tuple[
    ProjectDeliveryCheckpoint,             # candidate source
    ProjectDeliveryCheckpoint,             # current terminal cursor
    CandidateRuntimeSnapshot,
    ContinuationDispatchRecord | None,
]
continuation_source_checkpoints(history, allocation) \
    -> tuple[ProjectDeliveryCheckpoint, ...]
terminal_candidate_cursor_matches(checkpoint, candidate_revision) -> bool
```

`CandidateVerificationDisposition` has exactly `VERIFIED`, `RETRY_VERIFICATION`, and
`REMEDIATE_CANDIDATE`.

### 3. Contracts

- Codex Coder and QA processes use `workspace-write`; Reviewer uses `read-only`. QA still has an
  empty role `write_paths` policy and cannot merge or change Task state.
- QA may create disposable ignored cache/build files. After every run, candidate HEAD must equal
  `AgentRequest.source_revision` and `git status --porcelain` must be empty. Any Git-visible write or
  HEAD change is `POLICY_VIOLATION`, regardless of report content.
- A completion is `RETRY_VERIFICATION` only when Review did not run, no criterion/test is `FAIL`,
  and at least one criterion is `NOT_TESTED` or test is `ERROR`. It creates a fresh plan/Run for the
  same candidate and requires a new exact human approval. It never starts Coder.
- Any criterion/test `FAIL`, Reviewer result, or malformed ambiguous combination remains
  `REMEDIATE_CANDIDATE`; `PASS + APPROVE` remains `VERIFIED`.
- For a legacy failed continuation with no Candidate V2, retained Candidate V1 may be reused only
  when the exact current `ContinuationDispatchRecord` points to a sealed source plan/completion whose
  disposition is `RETRY_VERIFICATION`. Scope, Task, dispatch, source candidate, plan, completion,
  invocation, run additions, approved checkpoint ancestry, and current terminal runtime must all
  match. A genuine remediation failure stays on failed-Coder recovery.
- `resolve_planner_dispatch` and retained-candidate lookup must use the same source-cursor predicate
  at every continuation generation. A historic source cursor may omit `candidate_revision` only when
  it is a terminal `BLOCKED/FAILED` checkpoint with `failed_stage=DELIVERING` and a terminal
  `BLOCKED/FAILED` Task. That cursor only locates allocation ancestry and cannot itself be returned as
  candidate proof. Whenever resume actually reuses a candidate, the selected current/source Task's
  validated `candidate_ready`/`candidate_recovered` event and sealed implementation lineage remain
  authoritative. This rule must work recursively across multiple continuation allocations.
- Historical Delivery, Task, Artifact, invocation, completion, and dispatch records are read and
  validated; none are rewritten. The next successful `resume` only publishes a fresh verification
  plan.

### 4. Validation & Error Matrix

| Facts | Route | Coder calls |
|---|---|---:|
| QA PASS, Review APPROVE | `VERIFIED` / Delivery DONE | 0 |
| Criterion/test FAIL | `REMEDIATE_CANDIDATE` | 1+ |
| Review REJECT | `REMEDIATE_CANDIDATE` | 1+ |
| Only NOT_TESTED/ERROR | Fresh verification plan + approval | 0 |
| QA Git-visible mutation or HEAD drift | `POLICY_VIOLATION` | 0 |
| Failed legacy continuation from exact inconclusive completion | Reverify retained source Candidate | 0 |
| Multi-generation continuation has nullable terminal source cursor | Follow dispatch ancestry, then prove the candidate actually selected for reuse from Task events/artifacts | 0 |
| Nullable source cursor lacks terminal DELIVERING/Task marker | Reject ancestry as incomplete | 0 |
| Failed continuation from genuine code failure or broken lineage | Reject candidate fallback; use normal failed-Coder recovery | 0 before approval |

### 5. Good / Base / Bad Cases

- Good: pytest writes ignored cache in a detached QA worktree, tests pass, Git remains clean, then
  Reviewer inspects the same commit.
- Base: pytest cannot execute and QA seals only `NOT_TESTED`/`ERROR`; `resume` emits a new plan for
  the same commit without calling Coder.
- Good legacy recovery: an older version wrongly created a Candidate-empty continuation from that
  inconclusive completion; current `resume` follows the exact dispatch back to Candidate V1.
- Good recursive recovery: Candidate V3 is retained by the current Task while an older continuation
  source checkpoint projects `candidate_revision=null`; planner ancestry resolves through the typed
  terminal cursor, then V3 is independently proven from current Task events and artifacts.
- Bad: QA edits a tracked test and hides it in a PASS report, or the platform sends an environment
  failure to Coder so `CandidateCommitSkill` is asked to commit an empty worktree.

### 6. Tests Required

- `tests/agents/test_codex_cli.py`: QA gets `workspace-write`; clean ignored scratch is accepted;
  Git-visible mutation fails with unchanged HEAD.
- `tests/recovery/test_verification_disposition.py`: environment-only result retries verification;
  criterion/test failures remediate.
- `tests/recovery/test_delivery_continuation.py`: inconclusive result makes a successor plan with
  zero Coder calls; retained Candidate may be accepted through the exact successor cursor; recursive
  allocation ancestry accepts only a nullable terminal DELIVERING source cursor and rejects a
  nullable non-terminal cursor.
- `tests/recovery/test_resume.py`: real Git/MySQL recreates the legacy failed continuation and proves
  public `resume` emits a different verification plan without another Agent call.
- Targeted pytest, Ruff, strict Mypy and `git diff --check` must pass locally. The full dedicated-MySQL
  regression remains the human release gate.

### 7. Wrong vs Correct

```python
# Wrong: top-level FAIL is assumed to prove a code defect.
if not completion.verified:
    run_coder_remediation(completion)

# Correct: route from criterion/test evidence, not the summary label alone.
if completion.disposition is CandidateVerificationDisposition.RETRY_VERIFICATION:
    return propose_fresh_verification(completion.qa.source_revision)
run_coder_remediation(completion)
```

```python
# Wrong: read-only process sandbox prevents pytest/ruff from creating necessary scratch.
sandbox = "read-only"

# Correct: disposable QA filesystem plus immutable Git postconditions.
sandbox = "workspace-write"
assert git_head == request.source_revision
assert git_status_porcelain == ""
```

```python
# Wrong: every historic Delivery cursor is treated as candidate authority.
if checkpoint.candidate_revision != continuation.source_revision:
    reject_ancestry()

# Correct: a strict nullable terminal cursor locates ancestry; selected runtime facts prove reuse.
source = continuation_source_checkpoints(history, continuation)[-1]
candidate = terminal_candidate_event(selected_task, selected_events)
assert source.dispatch_commit_id == continuation.source_dispatch_id
assert candidate.source_revision == verification_plan.inputs.candidate_revision
```
