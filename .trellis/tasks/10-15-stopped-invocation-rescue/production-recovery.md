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
