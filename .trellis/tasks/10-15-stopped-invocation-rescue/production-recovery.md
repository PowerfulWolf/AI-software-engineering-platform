# K1 stopped execution production recovery — 2026-10-15

Maintenance fix: `8adfe68a578c14a2d424f109709c9cd0977a0618`, independently reviewed,
fast-forwarded and pushed to main. Controlled restart persisted/drained the old process,
started PID 65358, and public Console confirmed normal mode, delivery_ready and contract 9.

## Exact existing-data target

- Project: `project_ai-project_034252eb3595`
- Requirement: `delivery_multi_bb78e2316afca47d005384542f685174535b69db`
- Task: `task_c833c3235d0bb73adba67937d16ea66c`, revision 5, frozen intent
  `60bdc26c709fb2e5bc927a11f82a9809d855b471ff50d5d03d03777046fb0747`
- Original stopped Run: `run_b238cf79f6f8407cad4b946947bc9b0e`, attempt 4.
- Original owned-session-empty stop SHA:
  `006d5fba2ca2bd01edc7df4b79e611c8278bb6dc419fdfc035af1ba25a6fe935`.

Original UNKNOWN/missing result and PROVIDER_ERROR/cause=null stop bytes remain unchanged.
All 15 original immutable invocation/capture/history files were individually SHA-256 checked
before deployment and again after the paused rescue. No direct SQL repair or recreated Task.

## Public paused recovery

- Proposal operation `operation_97308eb20369067a6ed2d4ab9c0a6d1a`: SUCCEEDED.
- Exact stopped rescue plan `deaea91573dde5da653d85c9c3b1b6b8e3354d4d6074f055db1ebbca0492fc3b`.
- Complete inventory: 2792 files; 15 draft mutations including ignored `artifacts/accepted.py`.
- PAUSE operation `operation_5fc901567403eb93f7b1364234f8f5b5`: SUCCEEDED.
- Binding `e57e34d0c69cd55133d4c85c0a61abf6533354b0a05fd00eae295010d653bf87`.
- Engineering authority `c1b575d0bd101057dcf4f278a2ed5092430fd0b7a94840bf4cf9fbaf1ce1b359`.
- One ordinary next work reservation, attempt 5:
  `work_e57e34d0c69cd55133d4c85c0a61abf6533354b0a05fd00eae295010d653bf87`.

## Latest main update while paused

Registered repository main was clean, fetched and fast-forwarded to exact maintenance main
`8adfe68a578c14a2d424f109709c9cd0977a0618`. Active Coder checkout changed only through public baseline.

- SOURCE_REBIND proposal `operation_d2d849d1849d3499a43ddf2b397673a2`: SUCCEEDED.
- Plan `c59a0ecc274179f07a9c3b3f37fb398b41ce1d06ae7d62d27eb43f2eb06f2cd9`:
  preserve_draft, no conflict, all 15 original draft mutations identical.
- Native-rule change `c071be8a55ac156814451a89a7b9bd08d191137a2582a11e84abfb466278585e`:
  core/index, new core/stopped-invocation-rescue, guides/recovery-thinking. Each exact complete
  diff was inspected in Console and approved under the user's delegated maintenance approval.
- Execution `operation_d3658d77aa05ffa96cf8efeb3346ff08`: SUCCEEDED.
- Latest binding `f0cb134a5b1a32d7361f698cf8a2c3a16043e78db379565dc4f98b946b80cb62`.
- Authority `2dbc2050ee98b7a1b02806e9636c98480ef0662bcc76f5fe3360c87e441bb6ae`.
- Same attempt 5/WorkItem; uninvoked reservation reused, no second work debit.
- Latest source/base and actual HEAD: `8adfe68a578c14a2d424f109709c9cd0977a0618`.
- All 15 original draft byte SHA-256 hashes independently unchanged after rebind.

## Separate resume (Coder active; native verdict pending)

Operation `operation_7a01b55c6384178fc98e614c3e21d361` submitted to the public API with exact latest
binding, Task intent/revision, WorkItem/source and paused disposition
`890f8e235117cbd7abc6516e190b361dbc6e7b166d2ec805b8d2c59733097beb`.
Public summary at 2026-10-15T10:19:53Z confirmed attempt 5 RUNNING, Coder knowledge preparation,
valid live lease and heartbeat. The durable invocation store then confirmed a real new main Coder
start at 2026-10-15T10:20:19.897928Z:

- Run `run_7396707cd0d34f7090547e0a4791429f`
- Claim `lease_c62b1890c8434a380ec15e63`
- Context `ctx_2095bd48f116b7a7a4f3e7cecea3951d1c32785f420a4efcd17cd32d69435723`
- Attempt 5; exact source `8adfe68a578c14a2d424f109709c9cd0977a0618`
- Trusted native capture-start exists; no outcome at the latest read.

Public summary at 2026-10-15T10:33:20Z confirmed IMPLEMENTING / ROLE_EXECUTION with a valid
renewed lease. A fresh read-only SHA-256 check of all 15 original immutable history files
also found every byte unchanged. The current native request has a 1800-second limit and
capture-start at 10:20:38.896813Z; absence of an outcome before that limit is not failure.

Record native delivery result once persisted. A main invocation establishes execution, not a
candidate or business completion; independent QA/Review remain required.

## Newly observed Console race

Automatic operation detail refresh revoked readiness transiently and silently swallowed an enabled
button click; whole Task JSON recheck confused read-side timestamp/locator changes with an approval
change. The two UI submissions created no durable operation. Exact public API was used without
bypassing checkpoint/binding/disposition validation. The frontend fix passed an independent read-only
review, 77 focused JavaScript checks and a real Chrome approval/poll-overlap regression. The browser
regression reads all three native-rule changes and confirms exactly one unchanged PAUSE intent.

The fix preserves only already-verified same-scope cached facts during an unchanged poll, joins
in-flight reads before the fresh write recheck, and excludes only explicit read-side fields for the
three baseline actions. Checkpoint, intent, source, binding, disposition, leases, full operation digests
and unknown future fields remain exact. It does not change stored approvals or producer policy.
Production asset deployment is deferred until the active native role reaches a safe maintenance
boundary: transport caches app.js at construction, so a browser refresh alone cannot deploy it.

## Rollback

Use controlled pause/drain. Keep all new proofs, plans, authorities, bindings and audit events.
Only deploy readers compatible with stopped_execution_rescue and current observations; never
reset old state or delete draft/history to make an old runtime accept it.

## Native attempt 5 result (2026-10-15 10:52Z)

The native process reached its 1800-second local execution limit and stopped at
10:50:39.156318Z with returncode -15, no structured output and complete
`owned_session_empty` proof. Exact stop observation:
`4810aea246c245c056d04a3731950766238aaafc6a7e4408dd4da5ddab6a8571`.
The durable outcome is FAILED / POLICY_VIOLATION, nontransient, without an artifact;
`48ff51bdb73c845ffe6f2a2514b64c82c2eefa5a8348807585d1bb2dbb53ae57`.
The interrupted draft capture rejected `src/ai_software_engineer/learning_collection/__init__.py`,
which is absent from the frozen eight-file package write allowlist. This is a new,
explicit recorded failure, distinct from the original unknown-result gap. No QA or
Review has started and there is no candidate.

The RESUME command itself ended SUCCEEDED at 10:51:01.355712Z with delivery stage
BLOCKED and checkpoint `5719dc0f8ba2de24a8d642ce5c15055059f1741bde9ad07e945d45f0cdbf25e7`.
The original Task and queue are BLOCKED/CLOSED. Follow-up investigation compares the
actual frozen policy, original plan, changed inventory and supported public recovery;
no permission or Task state has been modified to bypass this refusal.

## Deployment and terminal recovery inspection

After the real stop, queue closure and terminal Operation were persisted, controlled restart
drained the original service and started PID 77590 with the frontend fix from `7750a63`.
Public Console returned normal mode, delivery-ready and contract 9. The registered repository's
clean main was fast-forwarded to `7750a63d1ddc5b10d27c569b6dd61090f0da7454`; the retained Coder
checkout was not edited by maintenance.

Public `CONTINUE_DELIVERY` without any approval was used to inspect terminal recovery:
`operation_7d437fe7dda06c268f46d5689d41c2b2` completed at 10:57:56.447440Z with BLOCKED and
`recoverable Coder identity is missing, unsafe or ambiguous`. A separate read-only typed
source inspection traced its cause to `ValueError("empty model route directory")` in
`NativeRecoverySourceReader.discover_failed_coder`, before current Coder inspection. This
exposes a discovery defect in how route containers without sealed records are handled.
A separate read-only full scan found 172 valid Run directories: 83 nonempty directories with
readable typed routes and 89 physically empty containers. Those 89 have no corresponding
invocation-start/outcome, so their role, Task and creation cause remain unknown; they must not
be attributed to the two historical UNKNOWN Coder Runs (those have no route directory at all).
The latest attempt 5 has one genuine sealed route and outcome. No container or data was
deleted or repaired. Regression and correction are in progress.


## Empty-route discovery deployed (2026-10-16)

Maintenance `774e0a6` was independently reviewed, passed the 17-case real-file discovery
regression and expanded offline validation, and was fast-forwarded/pushed to main. The public
latest-main scope-to-plan/full-success fixture also passed using real owned native stop facts.
Three older interrupted/knowledge-wait fixture variants remain under separate fixture repair;
no production checks were relaxed to accept their missing facts or discarded adapter config.

Controlled service restart reported all operations/writes saved and executors/index finished,
then replaced the service with PID 96526. Public Console is normal, delivery-ready, contract 9.
The registered clean repository main was fetched and fast-forwarded to the same maintenance
revision. The retained Coder worktree was not modified. All 120 pre-deployment immutable
invocation, continuation and route file SHA-256 values remained identical after deployment.

Public inspection `operation_f41269b02b9bc430cc01c59cf968baa5` was submitted without scope or
plan approval against parent checkpoint `5719dc0f8ba2de24a8d642ce5c15055059f1741bde9ad07e945d45f0cdbf25e7`.
It must return actual exact scope facts before any delegated approval is submitted. No empty
historical container was deleted, no stop/outcome was fabricated and no terminal Task reset.


The deployed discovery passed through the original full source checks and public inspection
returned `coder_scope` for exactly `src/ai_software_engineer/learning_collection/__init__.py`.
Scope digest `60166e92b269e1467d9e367062750897afad97502f3d8f7929df21fca75aafd8`
was approved under the user's delegated engineering approval via
`operation_7bc592e9d9e853359dc1ee8934fbf438`; the original failure remains unchanged.
The operation completed at 2026-10-16T02:04:56.985227Z, preparing (without executing)
recovery plan `622f711324450abfffedc2a8d696e2dea70d2794a870452926d7267b8e6e553d`.

Plan inspection independently validated the typed digest and all 16 complete file bodies against
current retained worktree SHA-256 values. It binds source Task revision 6, original Product
approval/base `5f38922cd5cb9f236170f7edbd0ccb6f0ba6194b`, effective execution base `8adfe68`,
real run739 native stop/outcome and complete 2810-entry workspace snapshot
`8eb22c889c812f68a125b2f5784bff2b898f69f574303e34075fe2811849feef`.
Target is clean registered main `774e0a6fcc920d9a6ce3738e80b9cc43045be7eb`, branch
`ai/feature/project-delivery-learning-loop-recovery`; no main-update path overlaps any retained
file. Source/target permissions include only the approved exact supplement; no protected rule
writes, merge or state capability. Target authorization copies the source frozen retry budget;
QA and Review remain independent. The plan is awaiting its separate exact approval.


The independent read-only plan audit reconstructed every patch hunk from effective base8adfe68,
matched all 16 body bytes and all 2810 current inventory entries, checked the original upstream
checkpoint/artifact SHAs and source frozen permissions/budget, and verified target clean main
and native-rule diffs. No issue prevented exact approval. The audit did not independently query
SQL claim/event digests; the public approval continues to enforce the full current native gate.

Separate plan approval/execution `operation_fe9537edf2d6a5a5fb185326c4f870f3` was submitted through
public CONTINUE against the unchanged parent checkpoint under the user's delegated approval.
It was RUNNING at 2026-10-16T02:10:23.971804Z. Successful operation submission does not establish
Coder invocation, candidate or DONE. Record actual claim/Run and delivery results when sealed.

## Approved terminal recovery preparation progress (2026-10-16)

The exact authorization was persisted at 02:14:09Z and the sealed NEW recovery Task input at
02:16:05Z. A read-only consistent SQL observation at 02:25Z found neither dispatch nor SQL Task.
The next observation confirmed committed dispatch
`dispatch_commit_622f711324450abfffedc2a8d696e2dea70d2794a870452926d7267b8e6e553d`,
SHA `4daf9dfa45e0527e14ee73c64c77a769c618f1dddae074205afe91b9ebf74b3a`, with
`committed_at=2026-10-16T02:25:43.501204Z`; its observer marker was published at 02:27:46Z.
Recovery Task identity is `task_recovery_622f711324450abfffedc2a8d696e2de`, exact source
`774e0a6fcc920d9a6ce3738e80b9cc43045be7eb`. The SQL Task was not yet materialized at this
observation; seed verification and actual claimed/native execution remain to be established.

During this preparation the service remained active (observed CPU 81.1%, later 49.9%) without
new error logs. Independent static tracing found repeated full current-fact validation: five
facts inspections before authorization and twelve more from sealed Task to dispatch. Each
inspection still performs complete source/target/terminal and workspace checks. This explains
a costly path, but is not a measured per-stage timing allocation or permission to cache mutable
current/READY facts. No service restart, target main update or gate change was made while this
exact operation was running. All 120 pre-deployment immutable history file hashes were checked
again at 02:23Z and remained identical. Record later seed/claim/native results below.

## Recovery Task claimed and native capture started (2026-10-16)

Public preparation recorded SEED_VERIFIED at 02:29:53.964872Z and EXECUTION_CLAIMED at
02:29:59.374186Z. The source Task remains BLOCKED; the distinct recovery Task was materialized
as IMPLEMENTING revision 2, attempt 1. Public summary at 02:32:27Z showed a valid renewed
Coder lease in knowledge preparation, with the requirement projected as DELIVERING.

- Seed record: `9a6ae099cbb3d292856743f504f3cdbea07e0508bf627405d6de0a53c8eac16e`.
- Exact target capture: `478767143d263fd7377576bab18caf5d8a77bd281af4d130c667b797f9516c6d`.
- WorkItem: `work_cfae997d04a77d9ed7903da084538c99720a5ccf365a21cf009035c0d327637a`.
- Lease: `lease_53e1542fb4fa0fcab02d4cce`.
- Run: `run_ee31bf7c305c4ae6a26cf0774e1ef21c`.
- Context: `ctx_876df8c3e22a6ace9d813f0418295a4638db97b7eee3d8290e35aaefdf2f7b51`.
- Durable invocation start: 02:33:08.411148Z,
  `c810034c4cc12b3b20a0b8857efc8c4cc04f73e8f25e0efb7136b17f4b270775`.
- Recovery invocation admission:
  `6883e500a3e64b188614f9cd41b76266daa3f0836b119c0a7b63d5232ae346bd`.
- Verified native capture start: 02:34:47.216471Z,
  `f2ff50178717b4dd4bda7d166bb406ad4ba47cf7bc8792eaf4905185e6749147`.

No result, candidate, QA or Review verdict had been sealed at this observation. Native start
is execution lineage, not business completion. Main `7b32798` contains the final verified fixture
and earlier preparation records; this section records subsequent execution observations.
The registered target remains at its exact approved
`774e0a6` while this operation executes. No restart or target baseline update was performed.

Independent read-only audit used native store getters and integrity validators for the plan,
authorization, Task, seed and invocation. The seed's 16 paths/file hashes and complete 107,474-byte
patch match the approved plan exactly; reconstructing each file from immutable Git objects and
patch hunks reproduced every body SHA without reading the active worktree. All 112 Context
segments have correct hashes and are untruncated; required origin inputs equal the plan-derived
sources. Direct seed mode (`input_mode=None`) keeps the complete patch in its sealed seed,
rather than requiring a coder-reapply patch segment. All 120 old history hashes remained equal.

## Bounded offline plan decoding measurement

An independent read-only three-round sample used only the saved plan copy, Python 3.12.13,
and a temporary private store with the same valid scope/envelope. Raw JSON was 841,630 bytes
(SHA `d128d9fb53b6e7bcbe1a6401d8e5ec7f03f7e31b6ed6a6f901470d4a2fa403ad`),
canonical envelope 619,533 bytes, with 2810 inventory entries and 16 captured files. No DB,
Git, inventory scan or active worktree was accessed. The temporary store was removed afterward.

| Operation | Median CPU | Median wall |
| --- | --- | --- |
| `RecoveryPlan.model_validate_json` | 43.676 ms | 43.712 ms |
| `plan.validate_integrity()` | 43.770 ms | 43.928 ms |
| `plan.model_copy(deep=True)` | 8.377 ms | 8.394 ms |
| Existing `FileRecoveryStore.get_plan` | 90.954 ms | 92.155 ms |

These measurements overlap and must not be summed. Decode reuse can save tens of milliseconds
per call, but this sample does not establish it as the main cause of the 24-minute preparation.
Actual call counts and lower-perturbation stage timings are needed before prioritizing an
optimization. Any future reuse must preserve fresh full bytes, original duplicate-key/envelope/
Schema/scope validation and every mutable SQL/process/approval/HEAD/capture/inventory/lock check.
No performance code or running production operation was changed on the basis of this sample.

## First recovery checkpoint accepted and continued

Run `run_ee31bf7c305c4ae6a26cf0774e1ef21c` sealed SUCCEEDED with outcome
`a1ece2b37e4bc125836c78c4020b198c67bf0bb7b36d079bd5e5d4230231af32` and
`coder-progress` artifact `art_coder_9ba1d839cca8e89500601668f03c3368`.
It declares only `design_step_step_01_contract_compatibility` complete and all seven later
steps remaining. The artifact retains all 16 changed files, records focused contract checks,
and explicitly defers source binding and later implementation/independent verification.
This is not a candidate or QA/Review conclusion.

Public summary at 02:47:45.534379Z confirmed native acceptance and automatic checkpoint
continuation: the Task is IMPLEMENTING revision 5, attempt-1 WorkItem CLOSED, and a separate
Coder attempt-2 WorkItem `work_60848576ad1b9a8663fea3ccd816cb9556aea7b5a8317afc9338818fcac7dd53`
is RUNNING with a valid renewed lease in KNOWLEDGE_PREPARATION. The failed read request at
02:46Z was not executed because automatic approval review had no model capacity; its later
normal reviewed retry succeeded. Neither the running delivery nor its state was modified
to work around that tool approval failure.
