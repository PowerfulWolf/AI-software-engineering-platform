# Design

## Standalone QA checkpoint reuse (2026-09-28)

Red production-entry fixture reproduces fresh proposal invoking QA again after standalone QA
PASS and Reviewer provider failure. Native accepted_qa intentionally requires a Task event;
standalone verification never changes that terminal Task, and completion requires Review.
Introduce a distinct optional retained_qa proof in the freshly approved plan, not an invented
native accepted event or partial completion. Bind the sealed QA artifact to its original exact
plan, QA admission and the Reviewer admission that consumed it when one exists. If context setup
failed before Reviewer admission, require exactly one sealed report from the precise QA invocation
and still no Reviewer admission; do not require a fabricated role call. Validate scope, Task snapshot,
candidate/artifacts/stage chain, artifact integrity, producer/context/criterion coverage, successful
controlled QA receipt where applicable, and no completed/rejected Review. Only the latest admitted
attempt may offer reuse; newer failures/changed inputs invalidate older PASS selection. Flatten
successive Reviewer interruptions to the original QA proof; old plans retain absent-field hashes.
Keep the original UI/evidence plan for the new independent Reviewer; do not rerun QA commands or
capture, inherit a Review verdict, expand authority or mutate historical records. New policy-bound
approval and fresh Reviewer identity remain required. Admission, completion, native adoption,
Console labels and schema must all understand the explicit proof. Test production propose/approve/
execute/restart, repeated Reviewer failure, tamper/drift/newer rejection and unchanged Task history.

## Exact predecessor visual evidence (2026-09-28 evening)

QA37d83241 returned3 PASS/1 NOT_TESTED for missing clear/restore/signed-out pixels; Manager's
supplementary plan1ef633 assumes prior AB/A/AC pictures remain visible, but execution attaches
only current images. Preserve max6 captures per scenario. Add optional exact predecessor QA
receipt reference to a newly approved verification plan, constrained to its prerequisite incident's
sealed completion, same scope/Task/implementation/candidate, completed nonblocked QA receipt and
matching admitted invocation. No arbitrary historical search, paths, orphan QA or transitive images.
New proposal and Manager context advertise precisely those available inherited steps/hashes.
Both QA/Reviewer receive prior6 plus current6 as actual PNG attachments (max12), with historical
QA labels/receipt metadata, not claimed current-role executions or acceptance. Existing plans omit
the field and retain hashes/no automatic inheritance. Validate at store read/write and before model
execution; bad references fail closed without new actions. Normal fresh plan approval is required.
Tests must demonstrate real two-receipt image delivery/reopen without re-execution, full provider
forwarding/private cleanup, no text base64, and foreign/hash/candidate/blocked/legacy refusal.

## Reviewer context composition repair (2026-09-28)

Operation8542fadf sealed QA PASS (four criteria) but Reviewer context exceeded the independent
entry's implicit12k default. Use the existing64k production budget, unchanged4k reserve. Keep all
required context and low-level defaults. Test the actual production execute path, not only the
builder: QA fits12k, its detailed report pushes Reviewer beyond12k; both run after the fix.
Also reject actual64k overflow before a model call, release the reservation and preserve history.
Expose a safe actionable Console context code. No partial completion is fabricated: this older
independent QA has no native accepted event, so supported recovery uses a fresh approved QA/Review
plan and no Coder. Per-role resumable verification is a remaining improvement, not silently added
authority. Load together with the validated read-graph fix only while Operations are idle.

## Linear verification history validation (2026-09-28)

A bounded read-only live snapshot profile timed out after35s with3201 get_verification_plan
calls/10131 raw record reads: shared prerequisite plan/incident/completion/authorization/invocation
edges repeatedly revalidate the same DAG. More recovery attempts amplify pre-approval latency.
Add synchronous call-scoped, store-identity-scoped validation memoization to public verification
read nodes, never process-lifetime cache. Only a completed successful node can be reused within
that call; active reentry fails as cyclic, depth/size are bounded, and finally resets the context.
New reads must reread disk and reject tampering; exceptions cannot poison later reads. Thread
contexts cannot share it. Preserve all role/scope/hash/lineage checks and immutable historical data.
Regression must count actual prerequisite validation in completion/incident diamonds, and exercise
cross-read tamper/restoration/cycle refusal; profile the same real read path without production writes.
Do not restart/interrupt the current admitted business verification to load a performance fix.

## Bounded viewport scrolling (2026-09-28)

Independent QA of plan 5339eab5 has 3 PASS/1 NOT_TESTED: screenshots stop at the top of the chart.
Manager operation_b1e65eb684c6c47213ab74dac9394794 requests a platform-only bounded scroll/resize
capability, no source repair or manual acceptance observations. The receipt has exactly one vertical
AXScrollBar at value 0 inside the target window. Add a `scroll` action with finite normalized
`scroll_position` in [0,1], no selector/index/coordinates, targeting exactly one enabled, settable
vertical scrollbar discovered beneath the exact child window. Reject ambiguity and unsupported
scrollbars; read back the achieved value. Never retry a scroll after uncertainty; capture remains
a separate approved snapshot, max six. No global events, arbitrary text, menu or other app access.
Absent fields preserve old nested hashes. Real platform SwiftUI fixture must show scrollbar 0->1,
changed pixels/positions, and refuse two vertical scrollbars. Update Manager facts/schema, require
fresh exact approval, preserve all verdicts. Original criterion is selected-account trend display;
do not promote a verifier's extra point-by-point comparison into a new product requirement.

## Bounded window pixels for independent verification (2026-09-28)

Manager operation_fad2299464faccd7f6e50f528778cb92 completed after 31 successful UI steps and
independent QA 2 PASS/2 NOT_TESTED. Its concrete request is rendered text/chart evidence, not a
candidate fix. Add an optional exact-plan snapshot capture flag (absent in historical hashes).
At most six snapshots capture the unique ScreenCaptureKit window matching the isolated child
PID/title, excluding cursor, shadow and all other windows. Never capture a display or arbitrary
rectangle. Preflight existing permission without prompting/changing TCC; locked/denied/ambiguous
capture fails closed. Limit PNG dimensions/bytes, sequence and store sizes; seal pixels/hash/window
identity in the existing per-role receipt. Existing source/home/network/process isolation remains.

Supply typed verified PNG attachments to independent Responses/CLI verifiers; do not serialize
base64 into text, drop images on fallback, or infer a verdict from capture success. CLI materializes
only validated sealed bytes into private temporary files and attaches them with --image. Context,
candidate/role and evidence lineage remain exact. Manager sees actual capture limits/new driver
hash/schema and proposes a fresh plan. Test schema denial, historical hash parity, tamper/size,
receipt replay without recapture, both provider encodings and a real platform-only window capture
before enabling any business attempt. No business source changes, global desktop access, model
tool expansion or hidden policy/TCC changes. Existing read-only screen permission probe is true.

## Manager QA recency uses durable delivery order (2026-09-28)

Live Manager advice selected the native four-NOT_TESTED QA over the newer verification QA
(one PASS/three NOT_TESTED) because model-authored created_at values were out of order. Read native
reports in validated event order, then prefer the matching sealed verification completion; never
let report timestamps override that execution lineage. Reproduce both native-event and completion
cases through coordinate/store/reopen. Keep old reports, advice and consumed approvals immutable;
the changed selected report already changes the exact advice input identity. Load only while idle.

## Failed UI action feedback, including existing receipts (2026-09-28)

Live e7065d77 reached the real Mock window but stopped at TARGET_UNAVAILABLE: the plan selected
AXTitle=全选 while the observed button exposes AXDescription=全选. Executor's partial error-code
allowlist incorrectly recorded COMPLETED; this did not establish acceptance. Treat every non-null
driver error as a typed execution block. Keep old receipt bytes/digests, derive their effective UI
failure for coordination/replay refusal, and pass bounded/redacted observed controls to Manager
so it can repair selectors through a new exact proposal, not an operator-authored scenario.
Preserve no-replay/independent-verdict gates and pre-model-only source-repair restrictions.

Manager operation_6aeeed2e6c7abaa7ccc07b6ea4ec555b now correctly requests a platform capability,
not source changes or another unlock: candidate's icon is an AXLink but scenario only supports
buttons/checkboxes. Add exact-AXIdentifier, index-zero, unique-match AXLink press at both typed
scenario and driver boundaries. Preserve exact child/window, sandbox/network restrictions and
no replay. Regenerate scenario-containing wire schemas and require new driver/policy hashes in
a fresh Manager plan. Real platform SwiftUI fixture must observe a link-styled Button and its
counter 0 -> 1; schema rejects title/description/index-based link targeting. This is not business QA.

## Desktop-session prerequisite semantics and recovery (2026-09-28)

Live verification 97184e05 stopped before GUI launch with NATIVE_UI_SESSION_LOCKED. Manager
mistook the desktop lock for an executor mutex. Its input had only the code and no current
session probe, so cached WAITING_HUMAN could persist even after physical unlock. Reproduce
through the real sealed receipt -> coordination seam before implementation.

Add a typed, optional Manager prerequisite fact: OS desktop-session meaning, logged-in-user
ownership, immutable original observation and current candidate-free session probe. Reuse the
trusted driver's session-check under bounded scratch/build isolation; do not launch a business
binary, inspect windows, unlock, read credentials or change executor permissions. Unknown probes
fail closed. Include semantic/current facts in the advice input digest; unchanged state reuses
advice, READY changes its identity and permits only a fresh separately approved proposal.
Persist the optional fact with advice, omit it from old digests, and render the authoritative
human remedy rather than model-invented mutex cleanup. No Task/verdict/history rewrites.

## Prerequisite successor knowledge wait (2026-09-27)

Operation 77e79237 produced ASE candidate 9ac7c9ee but its QA knowledge gap escaped as
MANAGER_FAILURE. Fresh remediation omitted approved parent context, and native-to-joint wait
handoff omitted the latest child checkpoint. Fix fresh context composition, typed checkpoint-plus-gap
handoff and normal Manager coordination. Historical task-scoped gaps require exact native ownership
and unchanged knowledge snapshot; never rename/migrate them. Resolution resumes the same QA after
restart with zero duplicate Coder. No new verdict, UI authority or consumed approval replay.

## Executor failure feedback (2026-09-27)

Follow-up: real executor diagnostics prove READY/trusted/live with zero native/AX windows, while
the platform SwiftUI WindowGroup fixture passes. Do not have Codex fix the business entry.
Manager needs a proposal-only source prerequisite repair option. Add a distinct sealed executor
prerequisite observation as an alternative repair source; it is NOT a QA completion or verdict.
Bind the exact receipt/plan/Task/candidate and preserve the same separate repair approval,
ordinary serial Coder/QA/Reviewer dispatch, restart context and original criteria. Existing QA-
completion-based repairs remain compatible. Test both evidence kinds through real Git/MySQL,
including restart before Coder and rejection of a missing/wrong repair grant.

After physical unlock, operation_8f7e89aae05b85fc1000fdb036df9c84 built/tested successfully but
the initial AX snapshot returned WINDOW_UNAVAILABLE/count=0. The controller returned generic
environment prose and later skipped Manager for admitted plans; coordination also lacked the
executor receipt. Fix only this ASE feedback boundary. Route immediate and resumed failures to
Manager with a validated exact Task/candidate receipt and bounded diagnostic; permit no-QA source
only with that receipt. Preserve old digests and approvals. Do not diagnose by operating the
business app or make an unobserved window cause into a business defect.

## Manager coordination closure (2026-09-27)

The live QA after recovery still returned four NOT_TESTED UI criteria; the next proposal only
repeated Swift build/test. Add a proposal-only Manager call with exact criteria, candidate blobs,
sealed QA and available capability schemas. Persist the decision by input digest; bind any UI
scenario and criterion mapping to a new exact plan. Normal Continue must consult it before old
build-only approval. WAITING_HUMAN must name the concrete remedy/resume condition. No operator
business patch/scenario, install, verdict or direct database change.

The CLI path did not machine-enforce command allowlists. For verifiers, disable native execution
surfaces and retain read-only OS isolation, supply bounded policy-readable exact candidate text,
and consume controlled execution receipts. Real local mock-provider tests must inspect the actual
tool catalog and attempt a write; shell-off alone still exposes apply_patch. No need to authorize
remote model traffic for these platform fixture tests. This is a fail-closed verification slice,
not proof every CLI role has a complete typed tool bridge.

## Recovery verifier knowledge wait (2026-09-26)

Live ASE Coder sealed candidate `a58f0e1a…`, then QA consultation raised a durable knowledge gap.
Recovery attached its Task only after the entire serial delivery returned, so the gap escaped as
MANAGER_FAILURE and the parent still referenced the old Task. Preserve the QA checkpoint and gap;
validate the exact recovery grant/allocation/Task/role/candidate before attaching that authorized
Task through `begin_recovery`. Ordinary joint reconciliation then owns WAITING_HUMAN and resolution.
Resume after approval with the original recovery context and route scope, never rerun the Coder.
Test the real Git/MySQL recovery → QA gap → visible current approval → fresh Host → QA/Reviewer →
parent DONE path, plus existing terminal recovery. Do not classify missing future QA observations
as required preexisting project knowledge; actual environment/authority gaps still block.

## Native UI capability investigation (2026-09-26)

Read-only host probe confirms AXIsProcessTrusted is true for a platform Swift helper. A platform
AppKit checkbox fixture can launch inside the existing Codex sandbox, but its AX tree is empty
because GUI Mach/XPC services are denied. This is a platform executor capability gap, not a business
defect. Do not silently drop the sandbox or treat process launch as UI evidence.

A separate native GUI capability is being investigated on platform fixtures only: retain existing
Codex sandbox for builds; a versioned native Seatbelt GUI profile restricts the launched mock process
to no network, no source writes, private scratch and no user-home/keychain data. Trusted AX driver
targets only the exact child PID's windows, never system-wide roots/menu bars, and performs only an
exact approved bounded sequence. Candidate, launch mode, actions, driver/profile hashes and role
must enter a fresh verification plan before business execution. Persist execution receipts and
actual accessibility snapshots for independent QA/Reviewer; no driver-produced business verdict.
No production GUI capability is enabled yet. Fixture code/results are not business acceptance.


## ASE-owned prerequisite repair path (2026-09-26)

User delegates review of Manager human gates to Codex within the approved repair scope. Codex
changes platform code only; the abandoned business draft is not an input to any ASE run.

Introduce an explicit optional prerequisite repair proposal on normal Continue. Bind objective,
write scope, source inconclusive QA/incident/candidate, current checkpoint, target preparation and
clean base. Publish immutable proposal, then require a separate exact repair digest approval.
Verification/scope approval must not be interchangeable. Preserve old QA disposition and history.
An approved repair uses the ordinary three-role continuation allocation with a distinct
`prerequisite_repair` kind and hash-bound required context. Expand only its explicitly approved
source paths; preserve denied paths, original criteria, commands and independent role policy.
No implicit installer, credential, merge, deployment or general shell capability is added.

Validation: red test at Console intent boundary (confirmed extra_forbidden before change),
scope/path rejection, proposal/store restart/tamper, stale target/checkpoint, missing/wrong approval,
no agents on proposal, explicit Coder admission and ordinary CandidateCommit, parent attachment,
context reconstruction on restart, legacy digest parity, Console approval routing and schemas.

## Role correction — user clarification (2026-09-26, authoritative)

The user clarified that Codex controls and repairs ASE; ASE itself must deliver the business
requirement. Authorization for a Mock UI solution is NOT authorization for Codex to substitute
for the ASE Coder. This overrides the operator-authored implementation approach below.

- Stop editing/running the business repair draft. Preserve it uncommitted in
  `ai-workspace/codex-quota-mock-ui`; do not import it into an ASE run, commit it as an ASE candidate,
  or treat its local test result as independent QA. Main and old candidate remain unchanged.
- Codex may implement and test ASE platform capabilities in the current platform checkout.
  ASE Manager owns prerequisite handling; its admitted Coder owns business changes; independent
  QA and Reviewer own acceptance on the exact resulting candidate.
- Confirmed platform gap: `ManagerRepairTaskSubmitter` is a Protocol with test fakes, but the
  production verification incident uses empty capabilities plus `_NoAutomaticRepairTasks`.
  `RETRY_VERIFICATION` only creates a same-candidate verification plan. A source-changing
  prerequisite repair therefore needs a real policy-bound submission/approval/continuation
  path, not an operator patch or a forged business FAIL.
- Next platform work must cover exact incident/candidate/scope authority, ordinary Coder
  dispatch and candidate commit, independent verification, and safe return to the parent
  delivery. Preserve all existing immutable verdicts and approvals.

## 2026-09-26 authorized Mock UI repair

The user explicitly allowed adding an isolated Mock UI acceptance entry to the business project.
Author the patch in `ai-workspace/codex-quota-mock-ui`, based on exact candidate `fb769427…`;
do not alter business main, existing ASE role worktrees, immutable candidates or QA history.
This is an operator-authored repair draft, not an admitted ASE Coder run or a new candidate yet.

- Make HistoryView a live-data wrapper over one shared HistoryContentView. The mock uses that same
  view and HistoryMemberSelection; it must not duplicate the selection logic or chart rendering.
- Resolve an explicit `--mock-ui-acceptance` launch mode before constructing MonitorController.
  Mock is memory-only, with fixed account IDs/dates and reserved example.invalid addresses. It
  must never construct AppPaths, member sessions, NotificationService, configuration/history
  stores or CLIProxy clients. Hide live menu/settings scenes entirely in mock mode.
- Provide two signed-in fixture identities, samples for both windows, simulated refresh, a third
  newly signed-in member, signed-out/no-history scenarios and a deterministic fixture reset.
  Clearly label all simulated data and actions; mock login is not OAuth/login acceptance.
- Verify argument/factory isolation and fixture/selection behavior with XCTest, then exercise
  rendered grid/chart/actions and accessibility. Record operator evidence separately from QA.
- New source requires a fresh candidate and exact approval through a supported repair/scope
  flow. Existing RETRY_VERIFICATION only retries the old candidate and cannot adopt this patch.
  Do not forge a FAIL, broaden old Task write paths, create a commit using old role authority,
  or directly change delivery facts to overcome that missing transition.

## 2026-09-26 Manager prerequisite and controlled verification repair

User confirmed implementation in this existing task after learning that the Manager recovery
seam was not wired and the SwiftPM compatibility executor did not exist. This is authority to
implement/test the framework, not to replay an old approval or globally disable a sandbox.

1. Persist an exact Manager prerequisite incident for inconclusive QA, binding scope, candidate,
   source plan, completion and QA report. Invoke `ManagerLeaderRecovery` in the production
   continuation path. With no pre-approved repair it returns WAITING_HUMAN; no automatic model
   retry, Coder correction or successful repair is inferred.
2. A successor plan may propose a versioned `codex_sandbox_swiftpm_v1` executor capability when
   the exact candidate has a Swift package. Seal the incident reference and capability in the
   existing exact-plan human approval. Legacy plans omit optional fields and retain their hashes.
3. The capability is a trusted deterministic verification service, NOT an expanded model command
   allowlist. After per-role admission, run the approved build/test commands under an explicit Codex
   read-only outer sandbox with one private writable scratch root and network disabled. Only this
   service adds SwiftPM's inner `--disable-sandbox` and trusted cache/scratch paths. No ordinary
   Subprocess/Responses tool or native model shell gains those options. QA and Reviewer run
   separately, retain readonly candidate source and receive their own durable command receipts.
4. Receipts bind plan, authorization, role invocation, candidate and bounded/redacted real results.
   Supply them as explicit execution evidence to the independent model, not as a PASS or acceptance
   override. No direct Task/verdict rewrite. Failed setup/unknown sandbox behavior fails closed.
5. Console approval facts show the Manager incident, proposed capability and remaining human/UI
   prerequisites. Original UI criteria remain mandatory; command success alone cannot finish delivery.

Tests: plan legacy hash parity; incident restart/idempotency/tamper; stale/cross-role/cross-plan
authority denial; model allowlist remains restrictive; isolated role scratch, minimal environment,
timeout/output bounds; real sandbox source-write and network denials plus Swift fixture XCTest;
continuation and Console integration. Rollback removes only this task's code; retain immutable facts.

保持 native recovery/verification 的 exact parent digest guard。修复 Host 的调用顺序，不放宽 provenance。

`Console exact approval → Host → inspect current native child → synchronize only changed observations → native resume/proposal → stable joint approval result`。

- 在提出或消费审批前比较父已记录的子 checkpoint 与经过 backend reconciliation 的当前 native checkpoint；有变化才经原 joint resume 同步，不携带旧子审批去触发联合审批。
- pending gate 返回已同步的父 checkpoint，不再调用会改变父 hash 的 joint resume。typed wrapper 继续校验子 checkpoint 精确属于父 children。
- 真正执行后继续调用 joint resume，以读取新子结果并正常进入其他仓库/最终验收。
- 不改 wire Schema；所有历史计划保留。旧已过期计划经正常重新提案恢复，不能原地重写批准。

## Verification and rollback

先更正窄 Host seam 测试使其在旧实现变红；再跑真实 Git/MySQL 测试证明 exact approval 进入执行。通过后用 main 服务加载代码，检查没有活动操作才重启。回滚仅撤销本任务代码并重启，不回滚 append-only 生产事实。

## Provider boundary corrections discovered during live verification

- 2026-09-26 live CLI fallback returned invalid QA output, but only root/type/hash were retained.
  Add a fixed allowlisted `validation_rule` diagnostic (unknown evidence, duplicate evidence,
  inconsistent verdict, wrong producer, self-reference; otherwise UNCLASSIFIED). Never print
  Pydantic messages/inputs/unknown IDs, retain raw provider text, or repair verdicts. This fixes
  diagnosability, not the unobserved underlying report error. Use a fresh approved run afterward;
  the consumed admission cannot be replayed.

- Responses strict 工具参数复用同一个 Schema normalizer，保证所有属性 required；输出统一为闭合 artifact object，Coder union 不位于根节点，QA 任意环境字典仅在 wire 上编码为 JSON string，解码后仍走原领域校验。
- 工具循环使用 `store=false` 和本次 bounded run 内完整 assistant output/receipt，不依赖网关保存 previous_response_id。历史工具结果只进入上下文，只有新 response 的新 calls 执行。
- Provider JSON error.message 先脱敏再限长；Console 显示 typed `MODEL_*` 错误，不输出 raw body，也不再把已知 AgentRunFailed 隐藏成通用 Manager 错误。
- 失败的 admission 不可重放；修复后重新提出和批准 exact plan，保留 prior_run_ids 和所有失败事实。

## Restricted Swift verification after explicit authorization

- 新 profile 支持 Swift；历史 profile/Task 不变。仅从精确候选 Git tree 的常规 Package.swift 文件
  派生 QA/Reviewer 命令；Coder/Orchestrator 不扩权。
- 共享 allowlist 限定版本、禁止自动解析/更新的 build/test；只允许配置、product、filter 选项。
  候选打包脚本包含关闭沙箱及签名，故不授权整个脚本，不加入 bash/xcodebuild/open/swift run。
- 计划绑定新 commands/policy digest，required context 解释本次批准与旧 Task 文本的差异；Console
  展示精确命令。未启动旧计划的权限不再匹配时必须重提，不能等到执行时才报分配不一致。
  已入场/完成记录仍按其封存权限验证，不改写历史结果。
- 本机缺少 XCTest/xctest；此前 swift test 和 CoreVerification 环境探针运行在业务 main
  `6d05fef…`，不是批准候选 `fb769427…`。它们只证明环境情况，不构成候选 QA 证据。
- 构建通过不能替代两个登录账号/趋势样本/辅助功能的 UI 验收。当前工具实现只增加受限 Swift
  命令，没有增加平台通用 GUI 驱动。环境或 UI 前提仍缺失时，停止盲目重复审批并请求具体前提。
