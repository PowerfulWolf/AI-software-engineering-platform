# Console incremental polling

## 恢复准备使用独立只读刷新通道（2026-10-10）

Scope：当前选中 Requirement（含其 Task 详情的父 Requirement）的精确恢复操作。
GET `/api/v1/operations/{operation_id}/preparation-progress` 返回已完成准备观察；
wire/存储/真实发布边界见 `web-console.md` 的恢复准备明细契约。

- 每五秒仅读取当前选中的一个精确恢复操作；独立 single flight、短 read deadline 与
  AbortController，不能排在 `refreshFlight` 等待慢 Team GET 的尾部。重复 tick合并，
  不并发重读全部历史 Operation，不因准备明细失败重试审批或执行。
- 冻结并在每次返回时重新核对 Team/Project/Requirement/Operation、发起checkpoint、
  approved plan 和 `selectionIntentRevision`；项目切换、需求切换、操作变化或终结后，
  旧回调不得污染新的当前页面。读取明细不能清除 Team/Operations freshness故障或恢复controls。
- 正文直接呈现已记录的准备明细与观察时间，重要内容不藏在排障折叠区。概览与当前操作行
  复用同源最后观察；保留真实当前角色节点，历史领取不能覆盖新的QA/Review或当前阻塞。
- seed `input_mode=coder_reapply` 显示“恢复输入已核验，旧进度交由开发继续适配”；
  `preserve_draft` 才可显示“保留改动已载入并核验”。无记录明确“本次操作未记录准备明细”。
  不渲染服务器自由文本、哈希、进程、lease或百分比作为产品下一步。
- 读取失败/旧服务404/非法view给固定中文说明，不冒充执行失败；同scope以前成功明细可保留，
  明示上次读取/观察时间，不推断仍在执行。不接受缺证据、重复kind、scope漂移或未知enum；
  合法缺中间记录只展示实际已有项，不补齐未观察阶段。
- 明细进入 keyed content/detail/block signatures，以增量协调保持原文档DOM、展开、阅读
  位置、选择与业务草稿。明细每次读取相同内容不替换正文，不重复弹出ACTIVE通知。

| 场景 | 用户展示与验证 |
| --- | --- |
| Team GET被hold或返回busy，新准备记录可读 | 独立读取明细并展示，原Team控制仍暂停 |
| Project/Requirement/plan切换后旧response返回 | 不采纳旧response，零审批POST |
| 旧Operation空记录/旧服务404 | 未记录/暂不能读取，不能说恢复失败或建议重建 |
| 明细暂不可读，先前同scope记录存在 | 保留时间标记的旧明细，原正文DOM/草稿不变 |
| seed以coder_reapply适配 | 明示开发继续适配，不声称旧补丁已合入 |
| 已领取观察之后新QA/Review或失败 | 当前节点以原已核验事实为准，观察仅描述过去时刻 |

Good：用户无需技术标识即可理解平台已完成什么，当前角色状态仍有独立事实来源。
Base：普通交付无新观察轮询。Bad：为了取得“进度”重复提交Continue、重置页面或放宽审批门禁。
增量用例：`preparation-progress.test.cjs` 与 `browser/preparation-progress.test.cjs`；
真实390/1024/1440布局、无横溢出、正文DOM/草稿与旧callback测试。存量无需改库；
加载兼容资产后刷新原需求，旧操作仍按实际无观察降级；回滚资产保留所有后台事实。

## Retained Team data cannot authorize current decisions (2026-10-10)

```javascript
deliveryControlUnavailableReason()      // Team freshness is independent from Console/Operations
pollingControlFacts()                   // includes teamReadIssue for page and detail signatures
refreshSnapshot(target, includeRuntimeStatus)
knowledgeApprovalUnavailableReason(bound)
knowledgeGapKey(item)                   // includes immutable current gap_id
knowledgeGapCard(view, index, base, item)
syncDeliveryControls()                  // also validates registered exact knowledge decisions
```

- `teamReadIssue=busy/unavailable/timeout` with a saved snapshot pauses current delivery and
  Requirement knowledge-approval commands. Successful independent Console/Operations reads
  cannot restore Team authority. Keep the snapshot, full history, open saved documents and
  composer/knowledge answer drafts. Chinese guidance distinguishes reading from executing,
  says current commands are paused, and explains automatic reread/revalidation. Do not ask
  users to rebuild a Requirement or infer an Agent stop from a browser read failure.
- Publish a current Team branch failure immediately, independently of slower auxiliary reads.
  Ignore superseded Project responses. After Team has published successfully, a later Knowledge
  or other auxiliary failure cannot temporarily revoke Team freshness. The serial owner still
  waits for all branches; this does not introduce concurrent polling or cancel live operations.
- Include freshness in nested page/detail source signatures, rerender failure and recovery
  incrementally, and retain open composer nodes. Successful current Team reread clears the issue
  and restores the current controls even when the content bytes are otherwise unchanged or a
  composer is open. Existing Project-switch, runtime, identity, capability, exact approval and
  active-operation gates remain independent. Callbacks and direct Operation submission recheck
  the same gate; disabling a button alone is insufficient.
- Current unresolved knowledge details adopt the verified GET view only for the frozen
  Project/Requirement/checkpoint, current Project and matching section/gap. Use the exact gap ID
  in the cached section key so a new gap cannot reuse an old actionable form; approved and
  historical cards remain read-only. Freeze the card's Project, Requirement, checkpoint and
  full gap signature when rendering. Before hashing the answer and again immediately before
  POST, verify current Team control, exact selected Project, WAITING_HUMAN Requirement and
  the same unresolved current gap. An in-place checkpoint/question edit or an approval arriving
  during `crypto.subtle.digest` cannot authorize the old callback.
- Register only Requirement knowledge submit buttons in the delivery-control WeakMap; show
  inline Chinese unavailability, preserve editable answer/source drafts, and restore the same
  form when its exact facts are current again. Preserve an in-flight submit's busy state across
  connectivity changes, and keep the gate effective after a failed POST. Independent Team/Project
  knowledge uploads, selections and settings retain their own administration contracts.

| Facts / ordering | Required result and regression |
| --- | --- |
| Busy/unavailable/timeout Team with valid old snapshot and successful auxiliary reads | Same snapshot/draft, current commands paused, zero old-callback/direct POST |
| Team fails while independent Operations is held | Immediate freshness gate and disabled existing submit before auxiliary settles |
| Same Team content reread succeeds with open composer | Clear issue and restore detail/form controls without losing draft |
| Team published, later Knowledge auxiliary rejects | No Team stale issue; explicit auxiliary-failure message |
| Engineering detail freshness changes | Old continue removed, saved source/open artifact nodes identical; no implicit approval |
| Pending knowledge answer during Team outage/recovery | Same form/answer/source; submit paused then explicitly usable, reading toggle remains usable |
| Changed Project/checkpoint/gap/current flag or already resolved | Old knowledge form cannot POST, including unchanged checkpoint with a newly approved gap |
| Team/checkpoint/resolution changes during answer hashing | Second exact guard yields zero POST and preserved draft |

Good: a user keeps reading the saved plan while ASE retries a busy Team projection; current
actions resume only after the same Project and Requirement are read again. Base: Settings and
independent knowledge administration remain accessible. Bad: a green Console readiness flag or
retained DOM is treated as authority for a stale Requirement, or a disabled knowledge button
is the only protection against a saved submit callback.

Root cause: `teamReadIssue` was only a banner fact and absent from the central control gate and
render signatures. Publication also waited for unrelated reads. Knowledge approval bypassed
that gate via an administration POST and captured mutable Requirement facts across an await.
Executable contracts must test branch completion order, unchanged-content recovery, retained
callbacks and knowledge-hash races rather than only the presence of an old-data banner.

Coverage: focused `readiness.test.cjs`, `engineering-wait.test.cjs` and `knowledge-gap.test.cjs`,
plus syntax/diff checks. Actual browser visual acceptance remains separate from Node DOM tests.
存量数据处置：read-side only, no SQL/Requirement/Task/Operation/approval-history migration.
Load the repaired compatible frontend assets and refresh the original Requirement. Existing
blocked waits and saved approvals/progress remain subject to their exact current facts; the UI
does not itself approve or restart them. Roll back assets/spec/tests and refresh without
rewriting history or stopping a role.

## Team busy, deadline and unavailable messages (2026-10-09)

Scope: `app.js::refreshSnapshot`, `TeamReadFailure(kind)`, `teamReadIssue`,
`unavailableTeamName()` and `unavailableTeamMessage()`. The Team wire, 40-second GET deadline,
serial five-second polling and server worker-owned admission remain unchanged.

- Non-2xx Team JSON recognizes only fixed `error.code=TEAM_READ_IN_PROGRESS`. Render read-in-progress
  guidance and automatic retry, not a red database-failure diagnosis. Never display server message,
  validation inputs, paths or credentials. Other errors use fixed Chinese unavailable guidance.
- An aborted observation has deadline precedence, including a non-2xx body that stalled and then
  failed JSON parsing. Explain that backend reading may still be running; never infer execution
  stop, quota reset or lost evidence. Release the UI lane/timer and allow the next serial read.
- Keep the last snapshot and mark it as old data with its successful read time. Initial busy has
  a reading placeholder, while Settings/Status can still load independently. A later success clears
  the issue. Include the issue in control/content/detail signatures so failure revokes current
  command authority and recovery changes the placeholder and restores exact controls.
- If Team already published before an auxiliary branch failed, say Team updated but auxiliary
  records failed; do not label the successful Team read as a database outage. Existing system-fact
  rendering must still revoke unavailable command controls without erasing editor drafts.
- Use existing incremental reconciliation on failure/recovery. Readable old documents stay open
  with the same DOM and input/selection; retained history does not grant new approval authority.

| Case | Required assertion |
| --- | --- |
| Initial busy / busy with a previous snapshot | Reading placeholder / same snapshot, old-data marker, no MySQL guess |
| Fetch or error-body deadline | Explicit timeout and backend-may-still-read text; refresh button/lane released |
| Unavailable with credential-like server text | Fixed Chinese text, no raw message or secret in any rendered surface |
| Busy while a document is open, then successful change | Same open document node; new next action visible |
| Concurrent system/control failure | Existing readiness and exact callback guards remain effective |

Good: show read-in-progress and preserve the paragraph being read. Base: unavailable uses safe
retry/status/log guidance. Bad: report every non-2xx as MySQL failure or rebuild the entire view.
Correct: classify fixed read outcomes and patch only changed source facts.

Regression: focused readiness tests and `browser/polling-state.test.cjs`, alongside engineering-wait,
operation-capabilities and UI contracts. No database or journal migration; controlled asset reload
and browser refresh activate the display change. Revert assets and reload to roll back.

## Independent read publication and outage history (2026-10-09)

```javascript
refreshSnapshot(target, includeRuntimeStatus) // one serial owner, parallel Team/system reads
withReadDeadline(signal, read)               // bounded GET lifecycle, inherited abort and cleanup
loadKnowledge(signal)
loadAdministration(signal, {refreshConsole = true} = {})
loadRuntimeStatus(signal)                    // standalone Status navigation owns a deadline too
```

- Validate Team JSON and exact Project intent, then publish/render it without waiting for the
  independent Console/Operations branch. Keep the owner/deadline until both branches settle;
  periodic ticks remain coalesced. Each branch can update its own facts independently when the
  other fails, retaining keyed DOM, drafts, reading pause and exact approval gates.
- Team publication and a later UPDATE_REQUIREMENT result can arrive in either order. Resolve
  only the exact successful edit from the same Project, matching the old Requirement identity
  and a replacement present in the validated current Team. Recheck after Operations settles;
  do not overwrite later user navigation or a different explicit selection. Save and match the
  explicit selection-intent revision; detail open/close, page navigation, Requirement filter
  and accepted explicit Project selection advance it. Automatic missing/default selection does
  not. A nullable selection alone cannot distinguish a user close from a derived missing record.
- Failed Operations reads keep the last complete validated array for history. Mark it stale in
  the connection status and complete-history disclosure; `operationsAvailable=false` revokes
  all commands. `activeOperation`, `latestApproval` and baseline proposal lookup cannot use it
  as current execution, approval or plan authority. Existing investigation/handling descriptions
  can still be copied for diagnosis, with the explicit unavailable-control guidance first.
- Knowledge GETs and initialization GETs inherit the refresh abort or own a 40-second deadline;
  release listeners/timers in finally. Thread the same signal into config-apply observation reads,
  including JSON bodies. Abort is a browser observation failure, never proof an ASE operation
  stopped. Mutation POSTs retain their existing behavior and are not given this read deadline.
  Standalone Status navigation wraps its status GET/body in the same bounded lifecycle; timeout
  clears its loading state, shows Chinese retry guidance, and a later navigation can read again.
- An already initialized Knowledge poll reads only its current scoped documents/index; it does
  not reload Settings and Project catalogs each five seconds. Initialization can recover missing
  administration facts but does not duplicate the refresh owner's Console metadata read.

| Scenario | Required behavior and regression |
| --- | --- |
| Team succeeds while Operations is held | New title appears immediately, existing document node remains open; owner still busy |
| Temporary Operations outage | All 12 history rows remain, stale warning appears, current commands/approval/plan unavailable |
| Knowledge GET hangs | Explicit signal aborts at the deadline, serial lane and refresh button release, next read recovers |
| Standalone Status GET/header or body hangs | Own deadline aborts, navigation loading releases, later navigation succeeds |
| Team replacement identity precedes edit Operation | Exact replacement becomes selected after result arrives; no lost detail |
| User closes detail before delayed edit results | Preserve explicit closed state; late result cannot reopen it |
| Late Project response / current approval changes | Existing latest-intent and disconnected-callback tests remain green |

Coverage: focused additions in `tests/team_view/readiness.test.cjs` and
`browser/polling-state.test.cjs`, plus existing async-boundaries, UI, engineering-wait and
operation-capability contracts. No persistent facts, journal history or authorization change.
Existing data: load the new frontend through a browser refresh after the service's frozen assets
are updated. No migration or repeated demand is needed. Roll back assets and refresh to revert.

Root cause: rendering was joined to an unrelated slower list, and transient read failure cleared
the complete history. The replacement-selection assumption also depended on Operations arriving
before Team. Test both independent completion orders and keep freshness separate from retained
readable history; do not widen authority to compensate for a missing request.

## Scope and signatures

Applies to the five-second Console read loop in `src/ai_software_engineer/team_view/app.js`.
No API, schema, storage, Task state or authorization contract changes.

```javascript
render({preserveComposer = false, incremental = false} = {})
renderDetail({incremental = false} = {})
renderView(container, key, facts, build, incremental)
viewBlock(node, key, facts)  // source facts invalidate callbacks and rendered data together
viewGroup(node, key)        // only containers without event handlers
reconcileViewChildren(current, next)
pollingContentFacts()
pollingDetailFacts()
pollingKnowledgeFacts()
```

## Contracts

- Polling publishes validated facts via the existing serial Project refresh pipeline. Rendering is
  a read-side operation; DOM preservation cannot retain an obsolete approval or bypass readiness.
- `renderView` skips identical scoped facts. Matching page/Project/entity containers reconcile in
  place. Changed scope keys rebuild that surface, so identical local IDs in different scopes cannot
  share an editor or command closure. Settings/Status belong to Team, not Project.
- `viewBlock` retains a node only if its key and source signature match. Signatures live in WeakMaps;
  do not store configuration or secret values in HTML/data attributes. Mark only event-free layout
  containers as `viewGroup`. Replacing a changed action block installs fresh, validated callbacks;
  HTML equality alone cannot prove that its checkpoint/target/selected inventory is still current.
- Request and Team list entries use their stable identities. Immutable artifact bodies use URI and
  full document facts; Spec bodies use scope/version identity. Same-scope read-state remains open;
  changed documents are revalidated before replacing their body.
- Model-call bodies use Operation identity/facts, retain their loaded state on unrelated changes,
  and have a disclosure key for changed-record reopen. Task activity has its own facts/region and
  updates heartbeats without destroying diagnostic text or refetching completed calls.
- Settings refresh saved/process metadata while preserving the form by draft baseline, Section and
  contract version. Unsaved inputs, secret drafts, focus, selection and native help popovers survive.
  Explicit saves, navigation and version changes retain their existing validation behavior.
- Knowledge polling compares inventory, Spec, learning, index and error facts, not only index status.
  Asset-only changes must become visible even if Team/Operations and the index are unchanged.
- Preserve scroll offsets for surviving containers and text selections whose endpoints survive.
  Do not restore selection/focus over a new notification or editor. Changed checkpoint/scope may
  invalidate an old control and must take priority over preserving that control.

## Validation matrix and examples

| Change | Behavior | Executable assertion |
|---|---|---|
| Another Requirement changes while Settings is being edited | Keep input/form/help nodes and draft | Browser input identity, focus and selection |
| Saved restart flag changes | Update metadata and retain current draft | Badge text changes; input identity/value stable |
| Another Requirement or current next action changes | Patch list/overview, retain open artifact and diagnostic | Same nodes/open/body; only one model-call GET |
| Snapshot timestamp changes alone | No content/detail mutations | MutationObserver reports zero child-list mutations |
| Current Task phase changes | Update modal facts, retain its artifact | Same dialog/document; latest phase visible |
| Spec inventory changes without index/Team change | Show new asset, preserve existing body | New title visible; old details/body same node/open |
| Exact approval checkpoint changes | Remove old action | Old approval disconnected; no stale POST |
| Current Requirement title/status changes with operation history expanded | Retain outer fold and unchanged sealed row DOM | Same fold/row nodes; open state remains true |
| Non-Product baseline action and older Product discussion both exist | Current action stays outside historical disclosure | Visible current engineering summary; old discussion remains closed |

`buildDetail()` positions current Requirement facts and controls ahead of reference/history.
`productExecutionSummary(item, {guidance = true} = {})` may suppress duplicated guidance only
when the same current blocker/next action is visibly rendered in `requestBlockerSection`.
`requestOperation()` still owns every existing readiness/checkpoint/role gate and event callback;
`appendDiscussionContent` routes controls into discussion only for `productDiscussionStages`.
An event-free `current-actions` group may relocate those controls, never synthesize authorization.
Current product knowledge has exactly one placement, including legacy facts without execution.

Requirement historical discussion/operations/repository deliveries default to closed disclosures
keyed by Project/Requirement. Group outer history containers and their lists so unchanged rows and
loaded inner disclosures survive reconciliation. Full record count/data remains present in DOM;
do not truncate to improve layout. Sealed record next actions are explicitly historical.

Good: a new Task heartbeat updates its activity while a user continues selecting an artifact paragraph.
Base: repeated identical polling changes only the connection/read timestamp.
Bad: restore every old button by matching its label, or preserve old action handlers using HTML equality.

## Verification and operations

`tests/team_view/browser/polling-state.test.cjs` exercises real Chrome with intercepted API facts.
`tests/team_view/browser/requirement-detail.test.cjs` checks current/historical hierarchy, complete
history and node preservation, current action visibility, Product drafts, legacy knowledge placement,
no rendering-triggered POST and no detail/page overflow at 1440px/1024px/390px. Browser history tests must
open the outer disclosure before reading `innerText` or clicking nested engineering summaries.
Also run affected interactions, async-boundaries, settings-layout, notification and lightweight
readiness/UI contracts. Use `node --check` and `git diff --check`. No full repository suite required.

Existing data: no migration or journal rewrite. Refresh the browser once to load the compatible
frontend; normal polling then preserves in-tab state. A full browser reload still starts a new view.
Rollback the frontend change and refresh; original polling behavior returns, persistent facts remain.

## Task reading and Requirement chapters (2026-10-06)

```javascript
taskDetailScopeKey()                  // Team + page + Project + selected Task
syncTaskReadingToolbar(panel)         // only toolbar text/pressed state, only when changed
taskReadingFold(title, key, open = false)
taskFeedbackSection(history, taskId)   // latest saved QA/Review artifact per kind
requestChapter(key)                   // current / outputs / history / reference
taskChapter(key)                      // same grouping with Task-specific names and facts
detailChapter(chapters, prefix, key)   // shared read-only chapter structure
requestChapterNavigation(request)     // read-only scroll controls
```

### Contracts and presentation

- Requirement detail has exactly four primary `h2` chapters: 当前进展、产物与交付、完整交付记录、
  工程参考. Each `.request-chapter` owns an independent card and `.request-chapter-heading`;
  existing modules become `h3` subsections. Stage documents are peer `.artifact-document` items.
  Historical discussion/operations/repository records belong to history, not the document chapter.
  Current business/engineering decisions and Product reply stay visible in current; navigation only
  scrolls. Reparenting must retain the original action gates, exact signatures and fresh callbacks.
  Any `knowledge_gap.is_current` belongs to current, including team/engineering responsibility;
  only historical gaps belong to reference. Never move an actionable current knowledge decision
  into engineering reference merely because it is not assigned to Product.
  The masthead title and current status share a keyed `.request-title-row`: the title may wrap,
  while the status remains visible on its right without shrinking or horizontal overflow.
  The status block signature includes both `deliveryPhase(item)` and `requestNodeExecution(item)`;
  unchanged RUNNING facts cannot retain an old phase label after the Requirement advances.
  Requirement masthead groups its context label/management controls and title/status inside one
  card. Context label and controls share compact typography; title/status remain adjacent rather
  than filling opposing ends. Scoped close styling must not override primary/danger action colors.
- The chapter, fold and list ancestors must all be `viewGroup` for descendant keys to preserve DOM.
  `appendExecutionEntry` binds `{entry, currentTaskId}`; Task model rows bind full `run` facts and
  `run_id/source_uri`. A heartbeat or added history row cannot rebuild unchanged sealed text.
- Task modal is read-only and may pause its displayed facts. `pausedTaskDetailKey` belongs only to
  its exact Team/page/Project/Task. Backend snapshot polling remains live; new facts show a pending
  progress notice. Both incremental and default `renderDetail()` respect pause: delayed unrelated
  command completion cannot silently replace paused text. Explicit resume renders latest facts;
  entity/scope change, navigation or missing Task clears pause. Requirement approval never pauses.
- Task overview preserves a known typed engineering `WAITING.reason/next_action`; `UNKNOWN` still
  requires execution verification. Latest saved QA/Review feedback names current/historical Task
  and is not a verdict for a later candidate. No role success is inferred from document presence.
- Task dialog and Requirement detail each have one main vertical reading surface. History/report
  bodies have no inner max-height clipping; long text wraps. Document source URI/hash is accessible
  after the body in a collapsed identity disclosure. Empty activity regions render no blank card.
- Task uses four `.task-chapter` cards: 当前进展、产物与报告、完整执行记录、工程参考.
  Current status/feedback precedes source reports and complete history. Model calls belong to
  history, identity/queues/assignments to reference. Chapter titles are `h2`, internal titles `h3`,
  peer disclosures share summary size/padding/borders; only nested source metadata is smaller.
  Task documents live under keyed `.task-artifact-list`; style this actual parent, not only
  chapter-direct `details`. Grid gaps prevent adjacent fold margins from collapsing together.
  Sticky header keeps close/reading controls; nonsticky title/status may wrap fully without
  filling the viewport. Overview signature includes raw `item.status` as well as presentation,
  since a changed delivery phase can have an unchanged WAITING/RUNNING presentation.
- Requirement chapter navigation uses the actual scroll-container padding. Above 1180px, the
  internally scrolling `#detail.request-detail-panel` and its nav share `--detail-panel-padding`:
  sticky top and inline margins negate that value, while inline padding preserves button alignment.
  The opaque nav background reaches the container's inner top/side borders without exposing old
  content. At 1180px and below, the detail follows page scroll and nav stays `top:0`; never apply
  the negative top in that mode. Check 1440/1024/390 geometry and real screenshots using the existing
  requirement-detail browser fixture. Task dialog already has a zero-padding sticky header.
- Current engineering wait uses keyed `.engineering-wait-panel` section, never an outer disclosure.
  Investigation, missing facts and permitted decisions remain visible in current; only exact identity
  reference is folded. Optional baseline discovery stays in `details.engineering-baseline-panel`;
  a current unexecuted plan becomes a visible section of the same keyed group, replacing stale inputs.
  `.engineering-baseline-form` is a `viewBlock` signed by `[bound, plan, canControlCurrentTeam()]`.
  Unrelated title/activity changes retain input DOM/value/focus; exact bound/plan/readiness changes or
  active/executed operations replace/remove controls. Draft values are not persisted as attributes.

### Validation and error matrix

| Trigger | Required behavior / assertion |
| --- | --- |
| Task heartbeat or appended history | Same history/text/report/model nodes, selection/open/scroll retained; all rows present |
| Pause then fresh snapshot or default render callback | Snapshot current, Task text frozen; pending progress notice remains |
| Resume, scope change or Task disappears | Latest same-scope facts or missing-record view; pause cannot survive |
| Product checkpoint changes | Requirement remains live; old approval control removed and cannot submit |
| Requirement title updates with document selected | Same document/text nodes and selection through keyed chapter ancestry |
| Stage docs mixed names / history exists | Four main chapters; all documents peer style; history only inside history card |
| 390 / 1024 / 1440 px | No horizontal overflow; chapter borders/spacing visible; navigation targets visible |
| Engineering wait / proof missing or permitted | Visible current action/result, folded identity, exact proof-only decisions |
| SHA draft then unrelated title/activity | Same input/form/value/focus and optional disclosure state; no write requests |
| New baseline plan / checkpoint or role changes | Current plan visible; old input and callback replaced or removed |

Good: pause a Task report while the team snapshot progresses; resume explicitly to review new facts.
Base: real-time heartbeat only patches changed activity, leaving selected evidence untouched.
Bad: freeze approval callbacks, replace paused text on an async completion, or key rows under an
unkeyed list/chapter. Correct: pause only Task read facts and group every ancestor, not just the row.

Required coverage: `browser/task-detail-reading.test.cjs`, `browser/requirement-detail.test.cjs`,
`browser/polling-state.test.cjs` and affected interaction/state contracts. Fixtures intercept all API
traffic; no production action or migration is needed. Existing facts remain usable after loading the
new frontend. Roll back assets and refresh without changing Task, Operation or approval history.

## Live progress inside an immutable Operation row (2026-10-05)

`currentOperationProgress(operation, request)` is a pure read-side derivation shared by the
active operation history and its visible notification. Its `title`, `reason`, `responsibility`
and `nextAction` use `deliveryPhase(request)` and `requestNodeExecution(request)`. A live
projection requires the exact Requirement/Project and current RUNNING delivery operation;
`activeOperation(deliveryId, projectId)` performs the scoped match. Input checkpoint digests
identify the version at command submission, not the latest phase after that command advances.

The original history renderer contained no current-phase display; its list also lacked a
`viewGroup`, so the row keys alone did not enable child reconciliation. The reported fixed
action label must not be attributed to an already-running row cache. Once the list is a
keyed group, nested blocks have their own dependencies: invalidating `pollingDetailFacts()`
is insufficient if a retained child only includes immutable command facts. The new row
must include `{record, progress}`. Do not change Operation bytes, timestamps or hashes to
trigger rendering. Native role phase changes must also participate even when the command
remains RUNNING throughout.

| Input change | Required result | Regression assertion |
| --- | --- | --- |
| Same Operation object, DESIGNING → PLANNING | Current row changes from technical design to planning | Original serialized Operation identical; row title and signature change |
| Same command, Coder → QA → Reviewer | Current phase follows the actual current Task | Implementation, testing and review titles update without invented verdicts |
| Current wait while command is RUNNING | Show real blocked phase, responsibility and next action | Product decision is not replaced by a generic request to wait |
| Sealed history, queued command or unrelated scope/action | No current-phase overlay | Historical outcomes unchanged; foreign Project cannot steal active match |
| Visible ACTIVE notice changes stage | Update its content; preserve acknowledgment key | Closed notice does not reopen during later phase changes |
| Opaque ID and command-input digest | Default collapsed engineering troubleshooting details | Product text describes progress; disclosure identifies the submission version |

Good: a single Continue advances from Designer to Planner; the product user sees the current
planning phase and next step, while the initiating action and input version remain auditable.
Base: completed, failed or interrupted records keep their own command outcome without borrowing
today's Requirement stage. Bad: label a new stage only during a full reload, stamp the current
checkpoint onto old input facts, infer model liveness from the Operation, or replay notifications
under a new per-stage acknowledgment key.

### Bug analysis and prevention

- **Root cause (C/D/E):** the Operation-history renderer treated the command label and status
  as complete progress, leaving the product user with only an action and opaque IDs. It omitted
  the shared Requirement phase. Row signatures also omitted derived facts, but the ungrouped
  list meant this was a latent incremental-rendering defect, not proof of the observed old label.
- **Earlier scope:** node/card fixes introduced shared execution facts, but did not update the
  separate Operation-history renderer or test one unchanged command across multiple phases.
- **Prevention:** shared live progress, complete nested signatures, and real Chrome polling
  tests with unchanged Operation bytes. Review every `viewBlock` that renders derived cross-entity
  values for dependencies on those entities; keep immutable history distinct from live overlays.
- **Related surface:** the active notification consumes the same progress and retains the
  original ACTIVE key. This does not introduce durable stage events, backend execution authority,
  invented completion time, or a model heartbeat.

Executable coverage: `tests/team_view/operation-progress.test.cjs` and
`tests/team_view/browser/execution-history.test.cjs`, plus affected polling and product-state
regressions. No template mirror exists in this repository; the maintained spec and tests are
the prevention boundary. Existing data needs no migration: update frontend assets and refresh;
rollback assets without modifying history or restarting an active role.


## 同一需求的通知必须服从当前流程（2026-10-10）

Scope/trigger：`team_view/app.js::renderOperationStatus()` 的 FAILED/INTERRUPTED 弹窗筛选。
旧 ProductApproval 中断不能在同一Project/Requirement后续Continue成功且待恢复审批时再次
盖住当前页面。通知是当前交互提示，完整Operation历史仍不可丢弃。

- 对同一 `intent.project_id + operationTarget(operation)`，较新的工作流操作无论action
  是否相同，都使旧失败/中断失去自动弹窗资格。不能仅以相同action判断supersedes。
- 保持当前最新精确approval、当前ACTIVE、当前新失败的原有展示与acknowledgement语义。
  关闭当前提示后，轮询不能退回弹旧失败；恢复准备明细、需求详情和完整操作历史保持可读。
- latest attention 与 supersede查询均限定同Project/target；外Project恰好同target文本不能
  隐藏本Project当前待处理。不改变持久化Operation状态/hash/审批，不为了隐藏错误清历史。
  本规则只影响过期弹窗，当前阻塞/处理方/下一步继续由当前已核验事实决定。

Good：旧PRODUCT_APPROVAL中断→新CONTINUE_DELIVERY成功含恢复approval，只提示当前待确认。
Base：只有最新失败，仍显示失败原因和详情入口。Bad：关闭当前提示后轮番冒出更早各action
的失败/中断，用户要逐项关闭才能查看需求。

增量：`tests/team_view/stale-operation-notice.test.cjs`、
`tests/team_view/browser/notifications.test.cjs`。断言跨action旧失败失效、关闭不复活、当前
精确审批仍可读、新失败能提示、跨Project/target隔离；真实浏览器点击页面与完整历史可读。
存量无需改库，兼容资产加载后按原历史重算通知资格。回滚筛选会恢复旧弹窗问题，历史不变。
