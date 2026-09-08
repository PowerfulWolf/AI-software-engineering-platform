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
Coder permissions and deny list. This version does not infer glob narrowing or permit policy changes.
Resolve the exact persisted target preparation using versioned native stores; company/project and
organization roots/IDs cannot move. Load bounded regular profile/binding records, establish scope
before following embedded paths, and use native binding environment validation. Recompile current
company knowledge and project source baseline using `production_rules(company, knowledge)`, shared
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
| Wrong source/company/permissions/denies/preparation/binding/profile/base | Safe `RecoveryRejected` |
| Project code dirty, untracked file, rule/company knowledge drift | Reject current execution even after approval |
| Missing environment | Reject without initializing directories or DB |
| No approved recovery decision | Task draft rejected |
| Authorized exact replay | Equal NEW Task draft and request; no writes or models |

Good: offline interrupted Coder, normal preparation at newer commit, trusted fake recovery decision,
then deterministic new Task draft while all old source files/index/records remain unchanged. Base:
same-base check, or missing environment with zero effects. Bad: persisting the rebound request over
old history or feeding a draft directly to runtime without sealed fresh dispatch/seed admission.

Tests: `tests/recovery/test_current.py` uses real temporary Git/MySQL, fake Agents and human verifier;
assert missing approval, same/new base, stale base, narrowed permissions/denies, target dirt/untracked,
company knowledge selection, corrupted profile, unchanged source, deterministic draft and zero-write
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

`OrganizationTeamHost.recovery_entry() -> NativeRecoveryEntry` in `recovery/entry.py`:

```python
propose(*, project_root, delivery_id, failed_run_id, failed_context_id) -> tuple[RecoveryPlan, Path]
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

Records live at `company/projects/<project>/state/recovery-<old-delivery>/` with plan/authorization/
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
