# T036 Live team read side

Long-lived read lifetime and native validation-error retention follow
[`read-memory-lifecycle.md`](read-memory-lifecycle.md). Team GET admission stays with the actual
worker through serialization; cancellation does not prove that read stopped. Complete verified
history remains available and must release after a finished read.

## 面向产品负责人的执行状态与工程处理（2026-10-04）

### Scope / Signatures

用户是产品负责人，业务决定与工程操作必须分开。新增只读 `DeliveryExecutionView`，
由 `TaskView.execution` 与 `RequestView.execution` 共同使用，字段为 `state`、
`responsibility(product/team/engineering)`、`reason_code`、`reason`、`next_action`、
`action_required`、真实 `available_at` 和可选工程 policy/receipt 引用。
`_with_execution_state(TaskView) -> TaskView` 与
`_request_with_current_work(RequestView, list[TaskView]) -> RequestView` 只投影事实。
`_continuation_history(sidecar, task, expected_scope)` 只读已有 `FileContinuationStore`，
缺失时不创建目录。

### Contracts

- Task 的交付阶段与当前执行状态分开。角色排队、重试、等待均不把 `IMPLEMENTING` 等 checkpoint
  改成另一阶段；Requirement 交付期间的角色等待保留 `DELIVERING/INTEGRATING`，单独投影 execution。
- 当前阶段对应的 typed queue item `RUNNING + LEASE_VALID` 才显示角色执行；`READY/LEASED` 显示
  已排队。缺少执行事实保持 `UNKNOWN`。租约过期只能证明 claim 失效，不能证明进程停止；
  展示“状态无法确认，由工程团队核验”，不得宣称已中断或默认请产品审批。
- `RETRY_SCHEDULED` 的时间只来自实际 WorkItem `available_at`，不猜倒计时或承诺已经启动。
  重试、排队和未确认阶段使用静态暂停样式，不能出现执行动画。
- 只有明确的产品回复/产品批准阶段，或已校验 `KnowledgeGapRouting` 的 `USER/ACCEPT_RISK`
  路由请求产品操作。PRODUCT/DESIGNER/RESEARCH 是团队工作；未知 legacy route 和工程等待进入
  工程核验。责任不能从 question、Manager 自由文本、英文诊断或“人工等待”字样猜测。
  gap-routes 必须与当前 gap ID 精确绑定并验证 canonical digest。
- `action_required` 指产品是否需要作业务决定。工程管理员沿用可信本机操作入口，技术审批与
  知识处理放“工程管理”折叠区，明确这只是职责分流，并未引入独立账户 RBAC。
- 产品摘要回答当前阶段、实际执行、原因、责任方和下一步。Task/Run/lease/hash/source URI/
  policy/receipt 位于工程详情，不能成为正常产品推进的输入。
- receipt/admission 只作为完整历史。读取必须绑定同 Team/Project/Repository/native delivery ID、
  dispatch SHA、Task intent SHA、source revision 与冻结 policy；admission 保持原 source/permissions。
  receipt 不是模型 progress、候选或 verdict；policy admission 不能记成真实人工批准。
  新 QA/Reviewer claim 优先于旧 Coder receipt，旧记录不重新形成当前阻塞。
- 独立候选验证的 `VERIFIED` 只投影本次候选验证已通过（`COMPLETED/team`），不能宣称整个需求
  已交付。`VERIFICATION_SUPERSEDED` 投影 `SUPERSEDED/team` 和历史已替代说明，不能作为新的
  工程故障或建议恢复旧计划；`VERIFICATION_INTERRUPTED` 与否定 verdict 仍保留停止/返工事实。
- 保留所有 QA/Review findings、每轮 Coder 输入 lineage 与每次中断/准入记录，不截断为八条。
  “收到反馈”仍不能显示“已修复”。轮询使需求从等待转为重试/执行时，保留当前选择并跟随分组；
  只有用户主动切换分组才重新选择，不能丢失正在查看的需求详情。

### Validation / Good, Base, Bad

| 输入 | 展示与禁止行为 |
|---|---|
| 当前 Coder 有效运行 claim | 实现阶段 + 执行中，不把它称为已完成模型调用 |
| 工程 WAITING_HUMAN 或未知 legacy 等待 | 等待工程处理，不要求产品批准技术 hash |
| 已批准知识/typed团队检索 route | 团队接续/处理，原业务批准保留 |
| 已安排 retry + available_at | 真实重试时间，静态阶段，不冒充角色运行 |
| expired claim、无停机 receipt | 执行状态待确认，不从失效租约推断停机 |
| 合法旧 receipt + 当前 QA claim | 中断在历史，当前显示 QA 执行 |
| receipt scope/intent/policy drift | fail closed，不写库或修补 sealed 事实 |
| 等待转活跃、12+返工记录 | 详情选择保持，全部历史保留 |

Good：产品只看到工程团队处理前提，管理员展开工程管理后操作精确计划；已保存故障与准入均可审计。
Base：旧 payload 没有 execution 时保留兼容渲染；read-side 不追溯授权旧 Task。
Bad：隐藏 hash 但仍要求产品逐次批准技术故障；把已失效 lease 当作进程停止证明；
用旧中断 receipt 掩盖已开始的 QA；切换状态后清空已选择的需求。

### Tests / Operations

增量测试：`test_product_execution.py`、`test_continuation_history.py`、相关 `test_live.py` 投影与
Schema 用例、`product-execution.test.cjs`、现有完整历史/知识/控制门禁 DOM，以及真实 Chrome 的
`browser/product-execution.test.cjs`、`execution-history.test.cjs`、`polling-state.test.cjs`。
读侧与 API 不构造 mutation Host；测试需证明读取前后文件 bytes 不变、缺失 sidecar 不创建、
scope/intent/policy 变化拒绝。MySQL fixture 必须串行，避免共享测试库重置互相污染。

存量无需改库或重写 journal；新服务只增加兼容投影并读取已验证历史。
空闲加载前端后刷新可见；回滚此读侧提交并刷新不删除 receipt、Task 或历史批准。
本节替代历史章节中把 lease 过期直接称为“执行已中断”、把通用工程等待要求用户继续审批的文案。

## 完整 QA/Review 返工执行记录（2026-10-03）

### 封存时间与可验证的轮次顺序（2026-10-05）

Scope：修改 artifact 接纳历史、最新候选/结论或 Console 合并顺序时适用。
签名：`_read_accepted_artifact_history(cursor, *, task_id, sidecar, state_artifact_ids)
-> ArtifactHistoryFacts`、`RunProjectionBuilder.build(ProjectionFacts) -> ProjectionSnapshot`、
`timeline_sort_key(TimelineEntry) -> tuple[datetime, str, str, int, str]`。

`ProjectionFacts.artifact_positions` 接受 typed `ArtifactStreamPosition`，包含 Task、Artifact ID、
sealed SHA-256、stream、sequence、ordinal。读侧先在同一 SQL snapshot 校验 accepted receipt，
再读取唯一原 CLAIMED event，以严格 typed QueuedWorkItem 核验 Task/work item/lease/role、
checkpoint 和 dispatch generation，才允许把 SQL sequence 送入 pure projection。
旧库缺少 acceptance table 时仅使用已验证 StateEvent 的 artifact references，按 SQL revision
与原 references 次序构成独立 stream；不扫描目录来填补未接纳的产物。

`TimelineEntry.occurred_at` 使用 ArtifactStore 封存的 `integrity.validated_at`，原 provider
`created_at` 保留为 `details.provider_created_at`。同 timestamp 在同一 durable stream 内按
sequence/ordinal排序；不同 stream 只能依靠已验证 parent/supersedes lineage，不能把两类序号
当作同一个全局时钟。`latest_accepted_artifact` 同时用于写侧和 candidate/QA/Review摘要，
没有唯一可证明的最新结果时 fail closed，不使用随机 Artifact ID 或 provider 时间补序。
Task/Run timeline 与 Console 历史合并都保留派生 artifact_history_position，禁止第二次 merge
又按 ID 打乱已验证轮次。QA 的完整 environment、finding、criteria、命令、evidence 与父链
均可读；environment 用安全文本在“QA 验证环境与未完成原因”折叠区展示。

Good：超过八条的多轮 QA FAIL/Review REJECT → Coder修改 → PASS/APPROVE，模型时间重复或
倒退、随机 ID 与轮次相反时，仍完整按真实接纳历史展示最新结论。
Base：无 acceptance table 的 legacy StateEvent artifacts 正常显示；不改旧 artifact bytes/hash。
Bad：缺失/重复原 CLAIMED event、generation/role/Task漂移、非整数序号、position SHA漂移，
均拒绝投影，读前后零文件变更、零数据库写入。

| 输入问题 | 检测点 | 结果 |
|---|---|---|
| accepted receipt 缺唯一原 CLAIMED event | SQL只读 adapter | 拒绝 position，保留原事实 |
| Task/role/dispatch/checkpoint/lease漂移 | typed claimed WorkItem对照 | ValueError，不以新claim补历史 |
| position Artifact/task/digest漂移 | pure projector facts校验 | ProjectionConflict，不选latest |
| unsealed artifact或无validated_at | pure projector facts校验 | ProjectionConflict，不回退provider时间 |
| 同时钟、同kind且无stream/lineage区分 | shared latest helper | ArtifactOrderingError，不按ID猜测 |

错误示例：`max(reports, key=lambda a: (a.created_at, a.artifact_id))`。
正确示例：`latest_accepted_artifact(reports, QaReportArtifact, trusted_order=verified_positions)`，
timeline使用 sealed timestamp，并在每次合并中保留已验证的 artifact_history_position。

增量验证：`tests/team_view/test_accepted_artifact_history.py`、`tests/projection/`、
`tests/team_view/test_execution_history.py`、`tests/team_view/engineering-wait.test.cjs`。
存量数据无需迁移或重写：读取旧sealed timestamp与durable references即可；没有证明的记录不
获追溯新排序权威。回滚读侧实现并刷新界面不会删除历史或改变任何角色结论。

### Scope / Trigger

任务经过 `Coder → QA FAIL → Coder → QA PASS → Reviewer REJECT → Coder` 等多轮返工，或 QA/Review 通过后进入新的 remediation/continuation Task 时适用。执行记录是只读审计投影，不能替代 Task 状态机、Artifact verdict 或 Manager Operation。

### Contracts

- `TimelineEntry.details` 对 typed `implementation-report`、`coder-progress`、`qa-report` 和 `review-report` 只投影有界摘要：Artifact SHA、source/candidate revision、parent IDs、supersedes、changed files、测试命令/状态/evidence ID，以及 QA/Review finding 的 code、message、文件/行、recommendation 和 evidence IDs。
- `ProductionTeamReader` 使用已验证 native checkpoint history 为同一 delivery 读取每个历史 Task；当前 Task 仍是唯一状态/调度事实，历史 Task 的 timeline、runs、documents 只合并到 `TaskView.execution_history`，并以 `history_task_ids` 标识轮次。不得固定截断为八条或删除旧 Task。
- `TaskView.timeline` 保持当前 Task 兼容语义；`execution_history` 按时间完整排序并包含 `task_id`，前端必须区分“当前轮”和“历史轮”。跨 successor 的历史不改变当前 `status`、`blocker`、`candidate_revision` 或任何 verdict。
- Coder Artifact 的 `parent_artifact_ids`/`supersedes` 是“是否接收上轮反馈”的可验证 lineage；UI 可以显示已接收输入，但不得宣称 finding 已修复或替 QA/Review 作判断。
- 读侧递归执行已有 redaction，URI、Run/Task/Artifact/Evidence ID 与 SHA 以文本展示。旧报告缺少 findings 或旧 Task 缺少 `execution_history` 时以空数组兼容。

### Good / Base / Bad

Good：QA FAIL 的 finding 和 evidence 出现在完整历史中，下一轮 Coder 的父 Artifact 与新 candidate 可追溯；Review REJECT 后再次返工仍保留全部轮次。Base：单轮 DONE 和没有 finding 的旧报告正常显示。Bad：页面只显示最新八条、只写“QA 失败”而隐藏 finding，或用当前 Operation/最新 verdict 覆盖历史。

### Validation

增量契约覆盖 projection details、跨 successor Task 合并、空 finding 兼容、超过八条记录和浏览器详情；不要求全量测试。读侧故障 fail closed，不能为缺失历史猜测 verdict。

## Blocker wording localization (2026-10-03)

### Scope / Trigger

The read-side Team snapshot and browser detail views expose durable `blocker`, `next_action`,
Manager coordination summaries, verification failures and recovery results. Historical records
may contain English from older platform versions and must remain byte-for-byte immutable.

### Signatures and contracts

`localize_blocking_text(value: str | None) -> str | None` is a pure presentation adapter. The
reader applies it before exposing checkpoint/event reasons through `TaskView` and `RequestView`;
the browser applies the same mapping to operation summaries and old fixture payloads. It may
translate stable platform sentences and prefixes, while preserving opaque Task/Run IDs, SHA-256
digests, repository paths and machine error codes. Status enum values such as `BLOCKED` remain
machine facts and are rendered with existing Chinese labels.

No state event, Task, Operation, Artifact, verdict, approval or digest is rewritten. Newly
generated user-facing recovery and integration actions should be Chinese at their producer so
that non-browser consumers see the same language.

When a blocked Requirement has a newer terminal child Task, its read-side `blocker` and
`next_action` prefer that child observation over stale generic Manager advice. Role execution
failures are rendered as Chinese while retaining any `run_*` identity and SHA-256 evidence
tokens. Manager coordination remains a separate flow status and does not replace the child
failure reason.

### Validation & Error Matrix

| Input | Read-side result |
|---|---|
| Known English blocker or recovery action | Stable Chinese wording |
| Repository blocker with an opaque unit/path | Chinese prefix; unit/path and error code retained |
| Unknown diagnostic text | Preserve text safely; never invent a reason |
| Historical English durable record | Display translated only; immutable record/digest unchanged |

### Good / Base / Bad

Good: a blocked child with `Repository unit_a is BLOCKED` is shown in Chinese while `unit_a` and
the original event remain unchanged. Base: already Chinese text passes through unchanged. Bad:
mutating a journal checkpoint to localize it, or removing a provider error code needed for audit.

Provider preparation, assessment, and intent failures use the same read-side adapter. For
example, `qa knowledge preparation failed: RATE_LIMITED` is shown as `QA 知识准备失败（原因代码：RATE_LIMITED），请检查模型服务后再继续。`.
The role, phase, and machine error code are retained in a bounded Chinese sentence; the durable
Task and Operation records remain unchanged.

Manager recovery advice is localized as well, including the exact recovery approval digest. The
digest remains visible so a human can approve the right immutable record; English coordination
summaries and route instructions never leak into the Team snapshot or browser detail view.

### Tests Required

Cover exact stable messages, repository prefixes, unknown text pass-through and preservation of
IDs/digests in the Python localization helper; cover Request/Task details, recent recovery,
Manager summaries and operation notices in `tests/team_view/ui.test.cjs` and the live reader tests.

## Scope / Trigger

### 活动角色的下一步提示

`_with_execution_state(TaskView) -> TaskView` 是纯读投影：非终态、无 blocker 的 Task，只有当前
阶段对应的 role queue item 为 `RUNNING` 且 `lease_liveness=LEASE_VALID` 时，提示
`Coder/QA/Reviewer 正在执行，请等待当前执行完成。执行租约有效，细分进度暂未上报。`。
`IMPLEMENTING/QA/REVIEW` 分别匹配 Coder/QA/Reviewer。`_request_with_current_work` 将同一提示
带到需求头部，避免活动恢复 Task 仍提示“请继续交付”。租约有效不证明模型调用、在线执行器或
进度百分比；不得改变 `execution_liveness`、run 结果、Task 或 durable next_action。

Good：当前角色有效租约显示等待完成。Base：仅 LEASED/UNKNOWN 保留原提示。Bad：用旧角色的
有效租约、过期租约或历史模型分配冒充执行。知识等待和过期租约中断保持优先级，终态 blocker
保持原事实。`test_live.py::test_valid_current_role_lease_presents_wait_instead_of_continue` 覆盖三角色
及未知/仅领取分支；现有 waiting/interrupted/current child fixtures 验证优先级。存量只读展示，
无需改库；空闲加载与回滚均不改历史。

Changes to team_view, read-only store opening, ase team serve, MySQL aggregation or browser payloads.
Existing DashboardRenderer stays pure; socket lives in separate server composition.

## Signatures

`ProductionTeamReader(config: ProductionConfig, environment: Mapping[str,str]).snapshot(project_id: str | None = None) -> TeamSnapshot`
`create_team_server(reader: TeamReader, *, port: int = 8765) -> ThreadingHTTPServer`
`ase team serve --port 8765`; `GET /api/v1/team?project_id=<project_id>` reads one Project through
the configured singleton Team. The response is `team-snapshot.schema.json`, including the safe
Project-tab catalog and the common Agent roster.
Existing ASE_CONFIG/database.dsn_env applies. No model credentials needed by reads.

## Contracts

- Team initialize(read_only=True) verifies existing state without creating a missing team.
- macOS/Linux 的默认 `platform_root=~/.ase` 只在配置层纯解析；缺失 workspace 的 snapshot 读取必须
  返回 `TeamReadError`，不得因默认值而创建 Team、Project 或 Repository 目录。
- Journal/checkpoint/artifact/evaluation/route-attempt read_only opens never mkdir; writes reject.
- Never construct TeamHost/MySqlTaskRepository/dispatch authority to read: constructors
  initialize schema/workspaces. Use REPEATABLE READ + WITH CONSISTENT SNAPSHOT, READ ONLY;
  rollback/close every connection on success and failure.
- Discover the single prepared Team only from direct `platform_root/team`, then discover Projects
  from sibling `platform_root/projects/project_*`. Validate every included manifest and Team lineage.
  A requested Project ID must satisfy `ProjectId` and match the discovered catalog before facts are read.
- Read one selected Project per snapshot; never aggregate its Requirements/Tasks into another Project.
  Validate chain, intake, dispatch digest and typed immutable Task identity. The identity comparison
  includes every Task field except execution status, attempt count, update timestamp and appended
  transient retry failures. A dispatch retry policy, when present, is frozen and must match exactly;
  a legacy dispatch that predates persisted retry policies may omit that one field and remains readable
  against the current Task policy. Any other drift is corruption and rejects the snapshot. Reuse
  RunProjectionBuilder event validation.
- A joint parent's child checkpoint is a committed observation, not a mutable latest pointer. When
  the native child has advanced, accept the parent reference only when it is the exact record at its
  sequence in the same fully validated native hash chain. Missing, replaced, future or cross-delivery
  references reject the whole snapshot; the Task view uses the latest native checkpoint.
- Match an attached child using its committed native delivery ID, exact unit/root and validated
  history prefix. A replacement integration plan must not regenerate an existing child identity;
  `PLANNING + plan=null + DONE children` is valid. Use DerivedStageInputs only for unattached
  in-flight children when a plan exists. Reject unknown/reference-only child units and ambiguous
  ownership. Never match by titles/prose or construct a Host to repair reads.
- Requirement membership persists through every validated joint checkpoint, including when an
  upstream correction clears the current children and plan. Historical native children remain
  audit work of the same parent and cannot fall back to independent Requirements. Current scope,
  execution, blockers and Agent queues use only the latest checkpoint's children/plan; historical
  membership must not make a superseded native source current again.
- Capture file prefixes before SQL snapshot; event-linked artifacts support gate evidence. Completed
  model-route records can precede state transitions but cannot become verdict authority.
- A single snapshot may project one sidecar's model-route ledger for several current, historical,
  and verification Tasks. Decode and integrity-check each immutable `run_*` ledger at most once per
  snapshot, then filter the cached typed attempts by Task/run identity. Never cache these facts across
  snapshots: a new snapshot must observe newly published attempts and re-run symlink, file and digest
  checks. This keeps five-second browser polling bounded as execution history grows without weakening
  read-side fail-closed behavior.
- Open the MySQL read snapshot only when at least one native delivery has a current dispatch commit or
  a historical Task source. A pre-dispatch terminal checkpoint with no `dispatch_commit_id` and no
  historical `task_id` is fully projected from its validated filesystem checkpoint: it remains a
  blocked work card with no Assignment, and does not require MySQL merely because a native delivery
  directory exists. Once any current or historical Task lineage exists, SQL remains mandatory and
  unavailable/corrupt SQL facts fail the selected Project closed.
- Current role is Task stage + committed assignment; terminal tasks are history, not active work.
- For T046-adopted delivery, a current-stage assignment additionally requires the matching role queue
  item to be RUNNING with LEASE_VALID. Queued, waiting or expired work does not make the Agent executing.
  Legacy non-adopted delivery and independent verification keep their existing projection contracts.
- Requirement 状态是联合 checkpoint 与其子 Task 的只读组合投影。若联合 checkpoint 仍是旧的
  `BLOCKED`/waiting 观察，但同一 Requirement 已有更新的、无 blocker 的非终态子 Task，列表和详情
  必须优先展示子 Task 正在交付（delivery/remediation 为 `DELIVERING`，candidate verification 为
  `INTEGRATING`），清除旧 blocker，并使用子 Task 的 `next_action`。子 Task 再次终止或阻塞后才恢复
  展示联合 checkpoint 的阻塞事实；不得把旧父记录覆盖回存储。

  该优先级也适用于更早的终态 QA/Review 或 remediation 子 Task：它们仍保留在任务历史中，
  但不能在新的非终态 Coder successor 已运行时把需求顶部钉在旧的验证阻塞上。只有没有活动
  successor 时，最新终态子 Task 的具体 blocker 才能覆盖父级泛化建议。
- `RequestView.failed_stages` 是从当前 native child checkpoint 的 `failed_stage` 只读投影的失败阶段集合；
  不得从 blocker 文本猜测阶段，也不得使用已被 successor Task 取代的历史 child checkpoint。浏览器的
  交付流程在有失败阶段时必须把失败阶段之前的节点显示为已完成、失败节点显示为阻塞警告、后续节点
  保持待处理，从而在 `BLOCKED`/`FAILED` 且没有活动 Task 时仍能看出卡点。活动 successor Task 重新出现时，
  Reader 清除旧的 `failed_stages`，流程恢复显示当前 Task 阶段。
- `DELIVERING` is an aggregate checkpoint for the serial Coder/QA/Reviewer run. When a terminal
  blocked child includes a validated `role_queue`, the browser maps its latest durable delivery role
  to the matching flow gate (`coder → 实现`, `qa → 测试`, `reviewer → 评审`) before rendering the
  failed warning. If no role evidence exists, it keeps the aggregate `DELIVERING → 实现` fallback;
  it must never label an earlier retained Coder candidate as blocked when QA or Review is the failed role.
- Manager 是跨阶段的协调角色，不作为第八个交付门槛插入流程；详情在流程上方显示只读的
  `Manager 协调 · 等待执行/处理中/等待恢复/已阻塞` 状态。该提示只能来自当前 Operation 与 durable
  Requirement 状态，不能把 Manager Operation 当成 Coder、QA 或 Reviewer 的执行事实。
- 例外：当前 `WAITING_HUMAN + knowledge_gap_id` 是显式知识等待，子 Task 刻意保留原 checkpoint，
  不能因其仍是 IMPLEMENTING/QA 而宣称恢复执行。通过只读 `KnowledgeGapView` 关联批准事实，
  `RequestView.knowledge_gap` 在批准后即变化（checkpoint SHA 不变），提示已批准、等待用户继续。
  详见 [`product-failure-diagnostics.md`](product-failure-diagnostics.md) 的 approved knowledge 契约。
- Design 预算因知识门误计而耗尽时，Reader 只有在当前 `DESIGNING` 无 Design/Plan、历史存在
  Design `WAITING_HUMAN` 且 resolution 完整性和 lineage 均通过时才设置
  `RequestView.design_recovery_available=true`。该字段由 journal/resolution 只读事实推导；网页
  显示独立“恢复设计”，不会把进行中的 Design 渲染成普通“继续交付”。恢复 Operation 的
  `expected_checkpoint_sha256` 必须与页面精确一致，Reader 不推进状态、不改预算、不创建 gate。
- Agent cards must render assignment-stage state, not copy the Task's global delivery status onto every
  planned assignment. Only `AssignmentView.current_stage=true` may display the Task's active-stage label.
  Earlier serial roles display `本轮已完成`, later roles display `等待<角色>阶段`, and a Task with no
  current-stage assignment displays `已分配 · 等待调度`. Task detail keeps the complete assignment plan.
- `AgentRole.ORCHESTRATOR` 是 legacy planning/control Run，可保留在 Task/Run timeline，但不是
  `TeamRole`。`RunProjectionBuilder` 只能把 Coder/QA/Reviewer delivery roles 映射成组织角色；
  没有 AgentProfile 且只含 orchestrator Run 的 synthetic identity 不得生成 Agent card。
- execution_liveness stays UNKNOWN without heartbeat. Enabled/capacity configuration and team counts
  are not online, utilization or organization-global workload.
- Member display state is assignment-derived: current-stage assignment = `执行中`; non-current active
  assignment = `等待当前阶段`; no non-terminal assignment in the selected Project = `空闲中`.
  `空闲中` is a team workload statement, never a process-online statement.
- 浏览器已确认同一 Requirement 存在 `QUEUED`/`RUNNING` 的 `CONTINUE_DELIVERY` Operation 时，
  Operation 只负责把 Requirement 列表呈现为恢复执行中；成员队列始终以 Team snapshot 的
  `assigned_delivery_ids` / `current_stage_delivery_ids` 为唯一事实。Manager 准备、Coder、QA、
  Reviewer 的串行切换必须随每次 snapshot 原样展示，浏览器不得把整个 Operation 生命周期硬编码
  为 Coder 执行中，也不得为了修正展示而写回 Team/Project/MySQL 状态。
- `team_view/app.js::terminalBlockedRequestTask(request)` 只从同一需求、每个 native delivery 的
  最新 TaskView 选择有真实 blocker 的终态工作。它只适用于 BLOCKED/FAILED/DELIVERING/INTEGRATING
  需求；当前知识门、活动 successor、等待最终确认和已完成/关闭阶段保留既有优先级。没有当前执行时，
  具体 child blocker/next_action 优先于泛化 Manager advice；原 advice 留在 durable journal 中。
- `operationChildBlocker(request, operation)` 只在 RUNNING 且
  `Date.parse(child.last_activity) > Date.parse(operation.requested_at)` 时认定为本轮的新终态阻塞。
  顶部必须继续显示阻塞及实际原因，Manager 文本可显示“处理中 · 当前角色已阻塞”。QUEUED、
  时间缺失/无效或旧失败均不能据此压住正在准备的新恢复。Operation 是协调事实，不是角色 verdict。
  知识等待、租约中断、未消费的精确审批仍使用自己的事实边界，不因时间比较获批或重放。
- `deliveryFlow` 在 Task 状态 fallback 之后定位当前有效失败 gate：durable role_queue 的
  Coder/QA/Reviewer 分别映射实现/测试/评审，前序已完成、失败节点阻塞、后序待处理；整个已阻塞
  流程不得留下 current 动画。缺少可验证角色事实时保留需求聚合阶段 fallback，不能从错误文本猜角色。
  `tests/team_view/delivery-status.test.cjs` 覆盖三角色的新失败窗口、空队列、旧失败与新恢复；
  knowledge-gap/ui 定向回归覆盖知识门、精确审批、活动 successor 与等待交付确认。
- The Team page may project the selected member into a four-column queue without adding new state:
  current-stage assignments are `进行中`, other non-terminal assignments are `待完成`, blocker or
  waiting/failed work is `已阻塞`, and terminal audit history is `已完成`. The queue is explicitly
  scoped to the selected Project snapshot; it is not an organization-global capacity claim.
- 四列队列必须为任务卡保留可读的最小宽度，空间不足时由队列横向滚动，不能把路径和操作压成逐字
  断行。列标题已经表达任务状态，因此队列卡只展示需求名、当前角色和紧凑代码目录，并作为整卡可
  点击/键盘操作的概览入口；
  模型、最近活动、完整目录、阻塞原因和审计记录统一进入任务详情弹窗。代码目录在卡片中可单行省略，
  但必须保留完整值供悬停查看。
- QA/Reviewer may create several immutable verification attempts for one Requirement. Their member
  queue is a current-work overview, not an audit ledger: show at most one card per Requirement,
  preferring the current-stage assignment, then another active assignment, then the newest historical
  attempt. Keep every older attempt in durable records and task detail evidence, but do not repeat the
  same Requirement across blocked/completed queue columns.
- Requirement blocker summaries similarly select the newest observation per native Delivery
  (`source_delivery_id` for verification/remediation, otherwise `id`) before collecting reasons and
  next actions. An older failed verification cannot remain a current blocker after newer recovery or
  verification work. Keep distinct repository blockers and all historical evidence; do not deduplicate
  by title or delete audit records. The DOM regression covers old/new verification reasons sharing a
  source Delivery while a second repository's current blocker remains visible.
- The Requirement's repository-detail shortcut resolves the same current observation, including an
  independent candidate verification, instead of linking to an obsolete blocked native Task.
  `VERIFY_QA`/`VERIFY_REVIEW` have explicit localized labels. An active Console Operation describes
  workflow execution, not Manager model execution; Agent ownership still comes only from assignments.
- The task page renders every selected-Project Task in exactly one UI group: `DONE` is `已完成`;
  blocker/`WAITING_*`/`BLOCKED`/`FAILED` is `阻塞中`; other non-terminal work is `执行中`;
  any remaining audit-terminal status is `已完成`.
- Planned models come from dispatch; actual completed calls from validated ModelRouteAttempt.
- Delivery writer and reader must use `agents.fallback.model_route_root(repository_workspace_root)`:
  `<project-sidecar>/runs/model-routes/<run-id>/<route-index:02d>.json`. Do not reconstruct ledger
  paths from prose. A scripted successful Coder/QA/Reviewer delivery must expose all three completed
  model calls; asserting only an empty-compatible list misses broken read/write wiring.
- HTTP only 127.0.0.1, exact Host and optional same-origin Origin, no CORS/downloads/write APIs or models.
- Redact displayed text. Render with textContent; URI/digests are text, not arbitrary navigation URLs.
- Requirement read model 必须从 exact current `JointCheckpoint.dialogue` 投影有序
  `DialogueTurnView`；只暴露已清洗的双方文本和截图 ID/名称/类型/大小/hash，不暴露 sidecar
  相对路径、绝对路径或图片字节。空对话保持空数组，不能用 `next_action` 猜测 Product Agent 消息。
- Failed polls preserve explicitly stale data; unchanged polls preserve DOM, changed ones preserve open
  reports/history. UI never infers percentage, success or process liveness.

## Validation & Error Matrix

| Case | Result |
|---|---|
| Missing config / occupied port | safe CLI exit 2 |
| Missing team / bad digest / path / unavailable DB | TeamReadError / HTTP 503, no init |
| Prepared empty team | honest empty data; no DB/model needed without native deliveries |
| Pre-dispatch `BLOCKED` native delivery, no current/historical Task | show the blocked work card with zero assignments; do not open MySQL |
| `BLOCKED`/`FAILED` checkpoint with `failed_stage=PLANNING` | Requirement flow shows 产品/设计已完成、计划为阻塞、实现及后续待处理 |
| Terminal `DELIVERING` child with latest closed QA role | Requirement flow marks 测试为阻塞；实现已完成，评审待处理 |
| Terminal `DELIVERING` child without role evidence | Keep the aggregate delivery fallback; do not infer QA/Review from blocker prose |
| Blocked checkpoint with an active successor Task | Requirement flow follows the successor's current stage and does not retain the old failed marker |
| Blocked Requirement with a queued or running Manager Operation | show the Manager coordination pill while keeping the seven delivery gates unchanged |
| Any current/historical Task or dispatch lineage | require one read-only MySQL snapshot; unavailable or inconsistent facts reject the snapshot |
| Running child before parent publication | visible via deterministic identity |
| Joint parent remains `BLOCKED`, current child is `IMPLEMENTING` | Requirement is active/`DELIVERING`; stale parent blocker is hidden |
| Parent references an exact historical child; native child advanced | latest child remains visible |
| Integration replanning has no plan, or replaces plan with retained DONE children | same native IDs and parent ownership; read-only snapshot succeeds |
| Parent child record is absent/replaced or ahead of native history | reject snapshot |
| Task/dispatch/event binding drift | reject snapshot, never hide corrupted records |
| Task runtime facts differ from dispatch | accept after typed immutable identity validation; a dispatch policy, when present, must still match |
| Legacy dispatch omits `retry_policy` while the materialized Task has a legal policy | accept for compatibility; do not rewrite dispatch or Task |
| Terminal Task | history, no current-stage assignment |
| IMPLEMENTING with Coder current, QA/Reviewer planned | Coder `实现中`; QA `等待测试阶段`; Reviewer `等待评审阶段` |
| QA with QA current | Coder `本轮已完成`; QA `测试中`; Reviewer `等待评审阶段` |
| Non-terminal Task with no current assignment | every planned role `已分配 · 等待调度`; none shown as executing |
| Orchestrator plan artifact/run | Run/timeline 保留；不创建虚假组织成员，不抛角色转换异常 |
| Foreign Host/Origin | 403 before reader invocation |
| Valid prepared Project tab | one isolated snapshot for that Project plus the common Team roster |
| Invalid/path-like/unknown Project ID | safe 404 or unavailable response; no path traversal |
| Enabled member without selected-Project assignment | `空闲中`; no online claim |
| Recovery Operation runs while Team snapshot says QA current | QA `执行中`; Coder/Reviewer use their snapshot assignments; no Coder override |
| Recovery Operation reaches a terminal status | continue using the latest durable Agent projection |
| Recovery Operation is terminal but an admitted QA/Reviewer projection remains active | keep the projection visible and show `继续交付`; the next Manager call creates the successor plan instead of stranding the Requirement |
| Active, blocked and done Tasks | exactly one matching task section each |
| Narrow Team queue with a long Repository path | readable overview card; compact single-line path; full metadata in the task-detail modal |
| Non-GET / unknown path or query | 405 / 404 |
| Malicious HTML / secret in title or Product dialogue | redacted text, no executable markup |
| Product clarification with screenshot | preserve user/Product order and safe attachment metadata |
| Failed poll then recovery | stale banner then clear banner after valid read |

## Good / Base / Bad

Good: current QA visible with exact modules before joint child writeback. Base: empty team has no
fake members; a dispatch failure before Task creation is visible without inventing SQL state or Agent
work. Bad: initialize Host on GET, open MySQL solely because a pre-dispatch checkpoint directory
exists, or label old IMPLEMENTING checkpoint as Agent online.

## Tests Required

tests/team_view: real MySQL/Git scripted providers, in-flight Coder/QA/Review, multi-request history,
no file writes, Project isolation, tamper rejection; actual HTTP GET/assets/Host/Origin/write/errors;
exact Schema model equality; Node DOM harness for multi-assignment/views/HTML safety/refresh/stale/
expanded documents, Project tabs, member workload state and three task groups. No real models. Full
regression, Ruff, strict Mypy and offline build required.
`tests/team_view/test_dispatch_identity.py` must cover runtime retry-failure append, legacy dispatch
policy omission, exact policy matching when present and immutable-field drift rejection.
The reader suite must also create a real repository sidecar containing a pre-dispatch terminal native
checkpoint and assert that `snapshot()` succeeds without a DSN, returns the blocked card, and exposes
no Task ID or Assignment.
`test_joint_reader_preserves_child_ownership_through_integration_replanning` covers PLANNING,
INTEGRATING and DONE before/after replacement plan publication and one approved extra attempt. Assert
no filesystem writes on snapshot, no child Agent rerun, candidate-bound Planner roots, one parent
and unchanged Task ownership. Unknown units, swapped roots and uncommitted future children reject.
The DOM harness must include one serial Task assigned to Coder/QA/Reviewer and assert that exactly the
current assignment receives the active Task-stage label before and after a Coder-to-QA transition.
`tests/projection/test_projector.py` 必须覆盖 orchestrator Run 可见但 `snapshot.agents` 不含虚假成员。
The DOM harness must also hold a stale blocked Requirement projection while a matching
`CONTINUE_DELIVERY` Operation is RUNNING, then provide a QA-current Team snapshot and assert that QA,
not Coder, owns the current work while Manager remains idle.
The DOM harness must cover a terminal `DELIVERING` Task whose role queue ends in QA and assert that
the flow marks 测试 as blocked while the retained Coder candidate is not marked blocked.

## Wrong vs Correct

Wrong: `TeamHost.from_environment().project_entry().status(id)` on every refresh.
Correct: `ProductionTeamReader(config, environment).snapshot()` with read-only opens and a read-only
MySQL transaction. Refresh observes, never advances delivery.

Wrong: `TeamRole(run.role.value)` 对所有 delivery/control Run 强转。
Correct: 仅显式映射 Coder/QA/Reviewer；Manager/Product/Designer/Planner 由 AgentProfile 提供，
orchestrator 只作为控制 Run 留在时间线。

Wrong: every Agent card renders `badge(task.status)`, so all three planned roles appear `实现中`.
Correct: render the badge from `assignment.current_stage` plus serial role order; preserve
`task.status` as the Task-level delivery state and never infer concurrent execution from a plan.

Wrong: label every enabled profile `已启用 · 运行状态未确认`, or call it online/idle without scope.
Correct: derive `执行中 / 等待当前阶段 / 空闲中` from selected-Project assignments and separately
state that process liveness remains unknown.

Wrong: treat every queued/running recovery Operation as Coder execution even after Team snapshot has
advanced to QA or Reviewer.
Correct: use Operation state only for Requirement-level progress and render every Agent queue directly
from the latest Team snapshot's assigned/current-stage IDs.

Wrong: render Project tabs while every tab still fetches the same default Project snapshot.
Correct: each tab calls `GET /api/v1/team?project_id=<project_id>` and the reader validates that
Project against the configured Team's catalog before reading isolated Requirement facts.

Wrong: `if natives: open_mysql_connection(...)`; a filesystem delivery may have failed before a
Task or dispatch commit existed.
Correct: build validated filesystem base views first, derive current/historical Task lineage, and open
the read-only SQL snapshot only when that lineage requires enrichment or verification projection.

## Scenario: Requirement-stage work in upstream Agent queues

### 1. Scope / Trigger

Applies when Manager, Product, Designer, or Planner queue projection changes. These roles execute
before native Repository Tasks exist, so their work identity is the Project Requirement rather than a
synthetic Coder/QA/Reviewer Task.

### 2. Signatures

```python
_agent_views(
    profiles: tuple[AgentProfile, ...],
    requests: list[RequestView],
    tasks: list[TaskView],
) -> tuple[AgentView, ...]
_upstream_request_state(request: RequestView, role: TeamRole) -> str | None
```

`AgentView.assigned_delivery_ids`, `current_stage_delivery_ids`, and
`history_delivery_ids` may reference either a `TaskView.id` or `RequestView.id`; the browser must
resolve both typed inventories and never invent a second work record.

### 3. Contracts

- `PREPARING` is current Manager work; `PRODUCT_DISCOVERY` is current Product work; `DESIGNING` is
  current Designer work; `PLANNING` is current Planner work. Earlier stages become role history and
  later stages are absent from that role's queue.
- `READY_FOR_DISCUSSION`, `WAITING_PRODUCT_REPLY`, and `WAITING_PRODUCT_APPROVAL` remain assigned to
  Product but are not execution liveness. They render in the waiting queue until Product work resumes
  or approval advances the Requirement.
- A joint `BLOCKED`/`WAITING_HUMAN` Requirement is assigned to Manager as blocked coordination work.
  `DONE` and `CLOSED` are history for all four upstream roles.
- Repository Task assignments continue to come only from committed dispatch facts. Upstream
  Requirement projection cannot create SQL assignments, leases, model selections, or process-online
  claims.
- Queue IDs are deduplicated in stable snapshot order. A queue card renders the Requirement title,
  owning role and compact scope; clicking or keyboard activation opens that exact Requirement detail.

### 4. Validation & Error Matrix

| Requirement stage | Queue result |
|---|---|
| PREPARING | Manager current |
| PRODUCT_DISCOVERY | Manager history; Product current |
| READY / WAITING_PRODUCT_* | Product assigned/waiting |
| DESIGNING | Manager/Product history; Designer current |
| PLANNING | Manager/Product/Designer history; Planner current |
| DELIVERING / INTEGRATING | four upstream roles in history; native Task roles own current work |
| BLOCKED / WAITING_HUMAN | Manager blocked; no invented upstream executor |
| DONE / CLOSED | four upstream roles in history |

### 5. Good / Base / Bad Cases

- Good: while Designer is running, Designer shows one current Requirement and Product shows the same
  Requirement under completed history.
- Base: Product is waiting for a user reply; the Requirement is queued, not labelled as actively
  executing.
- Bad: show all four roles as idle until Coder Task creation, or synthesize four SQL Task records for
  one Requirement.

### 6. Tests Required

- `tests/team_view/test_live.py` covers stage-to-role current/assigned/history projection, including
  DONE/CLOSED and Manager-owned blocker states.
- `tests/team_view/ui.test.cjs` includes an upstream Requirement ID in a member queue, asserts its
  group/count, and opens exact Requirement detail from the overview card.

### 7. Wrong vs Correct

Wrong: resolve every Agent queue ID only through `taskById`, silently dropping all pre-Coder work.

Correct: resolve through the Task inventory first, then the Requirement inventory, and render each
using its authoritative detail view.

## Bug analysis: pre-dispatch failure made the selected Project unreadable

1. **Root cause (D/E)**: the Reader used “at least one native delivery directory exists” as a proxy
   for “SQL Task facts exist”. A `CHECKPOINT_DRIFT` during dispatch persisted a valid terminal native
   checkpoint before any Task, Assignment or dispatch commit, so the proxy was false and an unrelated
   SQL read failure replaced the useful blocked checkpoint with a generic HTTP 503.
2. **Why earlier tests missed it**: the empty-Team test proved no database was needed before any native
   delivery, while in-flight tests always created a real dispatched Task and configured MySQL. No test
   covered the boundary state between those cases: native delivery present, Task lineage absent.
3. **Prevention mechanisms**:

   | Priority | Mechanism | Concrete action | Status |
   |---|---|---|---|
   | P0 | Architecture | Separate filesystem base projection from optional SQL enrichment; derive the SQL requirement from dispatch/Task lineage | DONE |
   | P0 | Regression | Persist a real pre-dispatch `BLOCKED` checkpoint and assert snapshot success without a DSN or assignments | DONE |
   | P0 | Integrity | Keep SQL fail-closed behavior unchanged whenever current or historical Task lineage exists | DONE |
   | P1 | Operations | Preserve a safe server-side root-cause code for future TeamReadError diagnosis without exposing DSN or record content | TODO |

4. **Systematic expansion**: storage existence is not proof that facts owned by another storage plane
   exist. Read models that join filesystem and SQL must make each cross-plane join conditional on a
   typed lineage reference, never on a directory count or broad lifecycle stage.
5. **Knowledge capture**: the contracts, matrix, regression point and wrong/correct pair above are the
   executable guard. This repository has no `src/templates/markdown/spec/` mirror to synchronize.

## Scenario: candidate verification and remediation visibility

### 1. Scope / Trigger

Apply when verification reservations or continuation dispatches change. These are real organization
work and must not disappear merely because their source Task is terminal.

### 2. Signatures

```python
_read_verifications(
    cursor: DictCursor,
    native_by_task: Mapping[str, tuple[_Native, str, ScopeView]],
    *,
    team_id: str,
) -> tuple[TaskView, ...]
_native_task_sources(native: _Native) -> dict[str, _Native]
_active_successor_dispatch(native: _Native, cursor: DictCursor) -> DeliveryAllocation | None
_read_task_details(
    native: _Native,
    cursor: DictCursor,
    base: TaskView,
    *,
    dispatch_override: DeliveryAllocation | None = None,
) -> TaskView
```

`TaskView` exposes `work_kind = delivery | candidate_verification | remediation`, optional
`source_delivery_id`, `source_task_id`, and `plan_sha256`. The JSON contract is
`schemas/team-snapshot.schema.json`.

### 3. Contracts

- Read `dispatch_commits`, `verification_reservations`, Tasks, events and route attempts inside the
  same repeatable-read transaction.
- One Delivery may move from its original Task to recovery/remediation Tasks while historical
  verification reservations continue to reference the original Task. Build the verification source
  index from the complete validated native checkpoint history, keeping the latest committed
  checkpoint for each Task. Render only the Delivery's current Task as ordinary work; historical Task
  entries exist only to validate and project their associated verification records.
- Every historical Task source must keep the same Delivery/project/root binding, have unambiguous
  ownership, and still pass the normal dispatch, SQL Task, event and Artifact validation. History is
  not permission to accept an orphaned or corrupted verification row.
- An incomplete verification reservation is a first-class QA/Reviewer work item. Current role is QA
  until its invocation/report exists, then Reviewer; a sealed completion makes it terminal.
  A released reservation with `abandonment_sha256` instead displays terminal
  `VERIFICATION_INTERRUPTED`, with no current assignments. A later successor does not erase this
  recorded interruption; `VERIFICATION_SUPERSEDED` applies to incomplete, non-abandoned predecessors.
- The Requirement delivery-flow widget must treat the projected Requirement stage as authoritative
  during verification: `VERIFY_QA` highlights 测试 and `VERIFY_REVIEW` highlights 评审. A historical
  repository Task may already carry `QA`/`REVIEW`, but that child status is only a fallback before an
  explicit verification stage exists and must never advance the parent flow ahead of its current role.
- When a newer reservation for the same project and source Task has been committed, an older
  completion-less reservation is a consumed, superseded plan rather than active Agent work. Keep its
  runs and approval evidence visible with terminal `VERIFICATION_SUPERSEDED`; no assignment on that
  card is current. Equal commit times for distinct plans are ambiguous and reject the snapshot.
- Verification scope is the source repository directory and candidate. Assignment cards come from
  the reservation, not from the terminal source Task status.
- The reservation's distinct `task_id` scopes Assignment/Lease/worktrees. QA/Reviewer provider
  requests and route attempts intentionally retain `source_task_id`; the immutable invocation Run ID
  is the exact join key used to prevent unrelated source-Task retries from appearing on the card.
- A `continuation_dispatch` is rendered as remediation and retains its source Delivery/Task lineage.
- Recovery/continuation execution may commit a new dispatch and advance its SQL Task before the
  native checkpoint is attached. Discover the one non-terminal successor committed after the captured
  checkpoint, scoped to the same Repository and Delivery and a validated historical source Task.
  A recovery additionally binds `recovery_of_task_id` to the current checkpoint Task and
  `recovery_source_checkpoint_sha256` to that exact checkpoint digest. Missing Task materialization
  means no active work yet; multiple live successors or mismatched recovery lineage reject the read.
- Reuse the ordinary dispatch digest, normalized immutable Task, contiguous event, artifact and
  projection checks for the successor. Only the old checkpoint's Task revision/status constraints
  are inapplicable to a different Task. Its `status`, candidate, assignments, current role and blocker
  come from the successor, never from the predecessor's terminal checkpoint or old implementation
  report. Keep the stable native Delivery ID and parent Requirement ID for browser selection.
- A successor view is `work_kind=remediation` with exact source Delivery/Task and plan digest. During
  Coder/QA/Reviewer execution the parent becomes `DELIVERING` and the old blocker is hidden. Snapshot
  never publishes a checkpoint, edits a Task or repairs the database. Once native attachment is
  published, the normal checkpoint-bound read resumes.
- Agent cards count these active assignments exactly as ordinary delivery work. The projection remains
  read-only and never creates a Host, schema, workspace, or state transition.

### 4. Validation & Error Matrix

| Fact | Projection |
|---|---|
| Active reservation, no QA invocation | QA current; source directory visible |
| QA invocation/report, no completion | QA run visible; Reviewer current only after QA PASS |
| Requirement `VERIFY_QA`, historical source Task `REVIEW` | 测试 remains current; 评审 is not highlighted |
| Older incomplete reservation plus newer committed reservation for the same source | older is terminal `VERIFICATION_SUPERSEDED`; newer owns liveness |
| Sealed QA FAIL | terminal verification with blocker; Reviewer not active |
| Continuation dispatch | remediation work with fresh Task plus source lineage |
| Checkpoint is BLOCKED; later bound recovery Task is IMPLEMENTING/QA/REVIEW | current recovery Task/role visible immediately; parent DELIVERING; no stale blocker |
| Recovery dispatch committed but SQL Task not materialized | preserve checkpoint view; no invented assignment |
| Recovery source checkpoint digest/Task differs or multiple live successors exist | reject snapshot |
| Current remediation Task plus reservation for its original Task | show both current remediation and historical verification |
| Historical Task appears in the native chain and still matches SQL/dispatch/artifacts | valid verification source |
| Historical checkpoint changes Delivery/project/root or one Task belongs to two deliveries | reject snapshot |
| Reservation references missing/wrong source Task/project | reject snapshot; do not hide row |
| Missing optional file record before reservation publication | reservation remains SQL-derived; no invented verdict |

### 5. Good / Base / Bad Cases

- Good: during candidate verification the long-lived QA member shows the exact work item, route and
  repository directory; after QA FAIL the successor Coder remediation appears.
- Base: a completed reservation remains auditable but no longer counts as active capacity.
- Base: an at-most-once provider failure remains auditable on its superseded plan, while only the
  successor plan can show a current QA/Reviewer assignment.
- Bad: index only the latest Delivery checkpoint Task. Once remediation changes `checkpoint.task_id`,
  the still-valid original QA record becomes an apparent orphan and turns the whole API into 503.

### 6. Tests Required

`tests/team_view/test_live.py` must insert a real MySQL verification reservation and assert its QA
assignment, source identity, work kind and exact repository scope. The real resume suite must also
interrupt an admitted QA verification and assert the card contains that exact QA Run. It must then
produce QA FAIL, begin the linked remediation Coder, call `ProductionTeamReader.snapshot()` before
that Coder completes, and assert the remediation card retains the original `source_task_id`; the
consumed predecessor plan must be terminal with no current assignment. Existing
schema equality, no-write, Project isolation, HTTP and browser tests remain required.
`test_resume_discovers_approves_and_attaches_pre_candidate_coder_recovery` observes a real resumed
recovery before each Coder/QA/Reviewer invocation: assert the successor Task ID and stage, exactly one
current role, no old blocker, and parent `DELIVERING`, even though the native checkpoint still points
at the failed predecessor. This is an incremental regression, not a replacement for full validation.

### 7. Wrong vs Correct

```python
# Wrong: terminal source Tasks suppress independent verification work.
active = source_task.status not in TERMINAL

# Correct: the reservation/completion lifecycle owns verification liveness.
active = reservation.completion_sha256 is None

# Wrong: only the Delivery's current Task can own verification history.
native_by_task[native.checkpoint.task_id] = native

# Correct: index the latest trusted checkpoint for every Task in the Delivery chain, then validate
# the selected historical Task through the same SQL/dispatch/artifact path as the current Task.
native_by_task.update(_native_task_sources(native))

# Wrong: keep showing the failed checkpoint Task until recovery.execute() returns.
view = read_only_the_checkpoint_task(native)

# Correct: validate the checkpoint Task, then project its exact committed live successor.
successor = _active_successor_dispatch(native, cursor)
if successor is not None:
    view = _read_task_details(native, cursor, base, dispatch_override=successor)
```

### Existing-data disposition

This is a read-model repair; valid checkpoints, dispatches and events require no SQL rewrite or
deletion. Reload the service after active operations finish, then read the existing Project again.
The same in-flight/finished Task remains the source of truth. Do not set Task status to DONE or clear
historical blockers in storage to make the page look correct.

### Bug analysis: recovery runs while the page still shows the failed predecessor

1. **Root cause (B/D/E)**: dispatch/SQL advancement precedes native checkpoint publication. The
   reader implicitly treated the checkpoint Task ID as the only possible current work identity.
2. **Why partial fixes missed it**: clearing an old parent blocker works only when the child view
   already contains the new Task. Browser Operation overrides can change a list label but cannot
   identify whether Coder, QA or Reviewer actually owns the current work.
3. **Prevention**: bind a successor to trusted dispatch/source facts, reuse Task/event validation,
   and observe every role in the real recovery regression before checkpoint attachment. Reject
   ambiguous successors rather than guessing from timestamps or titles.
4. **Systematic expansion**: the same boundary applies to Coder remediation and candidate
   verification. Verification keeps its reservation-owned lifecycle; recovery/remediation uses
   dispatch-owned Task state. Neither may replace historical records or infer process liveness.
5. **Knowledge capture**: the signatures, lineage matrix, incremental regression and existing-data
   disposition above are the maintenance contract. This repository has no generic thinking-guide or
   `src/templates/markdown/spec/` mirror; keep this rule in the owning core spec.

## Scenario: retired Requirement visibility

### 1. Scope / Trigger

Applies when Project Requirement inventory/counts consume `requirements/retirement.json`.

### 2. Signatures

```python
_retired_requirement_ids(ProjectWorkspace, JointJournal) -> frozenset[str]
RequirementRetirementStore(..., read_only=True).retired_delivery_ids(journal)
```

### 3. Contracts

- Snapshot reads and Project summaries exclude retired `delivery_multi_*` identities from current
  Requirement lists and counts, while leaving immutable journal files untouched.
- The reader derives every owned native Delivery from the retired joint checkpoint's committed
  children and execution plan across its entire validated journal history, then excludes those native
  Tasks before standalone fallback and Agent queue projection. The same historical membership
  verifier used for active parents checks exact unit/root/checkpoint ancestry and rejects ambiguous
  active/retired owners. Audit sidecars remain on disk but cannot reappear as unrelated current work.
- The reader validates the retirement digest, Team/Project lineage, exact retired checkpoint and any
  replacement journal before filtering. A malformed exclusion list is corruption, not permission to
  hide arbitrary work.
- The read path remains read-only and must not create, repair or restore a retirement record.

### 4. Validation & Error Matrix

| Record | Projection |
|---|---|
| absent or valid empty record | existing Requirements unchanged |
| valid deleted/replaced entry | exclude exact original from list and count |
| retired parent with child/native delivery | exclude parent, native Task and Agent queue entry |
| valid replacement | replacement remains visible; original excluded |
| digest/owner/checkpoint/replacement drift | snapshot fails closed |

### 5. Good / Base / Bad Cases

Good: an edited draft appears once under its new identity. Base: a deleted draft disappears while its
journal remains inspectable. Bad: subtract a raw JSON ID without verifying its journal binding.

### 6. Tests Required

`tests/team_view/test_live.py` must assert a retired Requirement is absent, its native child Task is
absent and the owning Project count is reduced, using a real read-only journal, Repository sidecar and
retirement record.

### 7. Wrong vs Correct

Wrong: hide only the parent Requirement and let its child sidecars reappear as standalone Agent work.
Correct: validate the Project-owned retirement index, derive its owned native Delivery identities,
then filter parent and children before Request/Task/Agent projection.

## Scenario: retained single-repository candidate awaiting finalization

- When a one-repository parent has one exact native DONE child but no
  `single_repository_acceptance`, project `WAITING_DELIVERY_FINALIZATION` instead of claiming that
  Planner is running.
- The delivery flow highlights step 7 (交付). The view explains that “继续交付” performs a read-only
  evidence recheck followed by the parent journal append; it must not show joint-integration
  approval or assign Planner/Coder/QA/Reviewer.
- After the proof is appended, project ordinary DONE. If evidence validation fails, retain the prior
  checkpoint and surface the exact safe failure through the operation result.
- Existing `PLANNING` remains meaningful for actual multi-repository planning; the read projection
  must not relabel all PLANNING states globally.

## Scenario: T046 role queue visibility

### Interrupted execution and historical Manager advice

`_with_execution_state(TaskView)` derives a blocker from a nonterminal RUNNING/LEASED queue entry
with `LEASE_EXPIRED`; it preserves Task.status and the immutable delivery checkpoint. Requirement
projection uses the current successor's blocker and clears superseded coordination. A known expired
lease outranks a still-running Console Operation in Requirement presentation. The Manager line can
show its Operation separately, with the explicit interruption. Only the affected role is interrupted;
future QA/Reviewer assignments remain waiting. CLOSED historical claims do not interrupt DONE.

After native reaping, `RETRY_SCHEDULED` still represents this interruption when the latest claim is
`EXPIRED`, its expiry is at or before snapshot time, and `wait_reason` equals
`lease_expired:<that exact lease id>`. The read side retains `LEASE_EXPIRED` in this case. Both Python
and browser keep the interruption and any exact approval visible until a new valid claim replaces it.
Provider retries, CLOSED history and unrelated wait reasons do not satisfy this rule.

`managerFlowStatus` only shows a pending approval when `latestApproval(id, checkpoint)` returns an
unconsumed exact approval. PROPOSE_RECOVERY is advice and means waiting for recovery, not proof that
an approval exists. Active successors, DONE and CLOSED suppress old blocking advice. Current knowledge
waits retain their own gate. Journal bytes and SQL are never rewritten to repair this projection.

Incremental regressions: `delivery-status.test.cjs`, `ui.test.cjs` and
`test_live.py::test_active_child_task_supersedes_stale_blocked_requirement_projection`.
Existing data requires only a service reload and page refresh; retained invocation/worktree recovery
uses its separate approved execution contract.

### Scope and signatures

`read_role_queue(cursor, *, task_id, repository_id, allocation_sha256, now) -> tuple[RoleQueueView, ...]`
reads inside the existing READ ONLY SQL snapshot. `TaskView.role_queue` defaults to `()` for legacy
Tasks. `RoleQueueView` carries work_item_id, role, attempt, status, agent_id, heartbeat_at,
lease_expires_at, lease_liveness, wait_reason, wait_disposition and wait_disposition_sha256;
`TaskView` also projects task_revision and task_intent_sha256. Schema parity is required.

The static `schemas/team-snapshot.schema.json` is the complete `TeamSnapshot.model_json_schema()`
plus its existing `$id` and JSON Schema dialect. Synchronize all reachable `$defs`, including typed
`DeliveryDisposition` and its facts/action/responsibility contracts; do not patch only the top-level
properties or drop valid read fields to satisfy an old schema. Keep every model's existing
`additionalProperties=false`, required fields and nullable/default semantics. These four optional
read fields accept legacy omission or explicit null without granting engineering authority.
`to_wire()` continues to omit absent optional values. Exact digest/facts binding remains enforced
by the typed domain validators and verified reader, rather than inferred from schema shape alone.

Incremental schema gates: `test_live.py::test_wire_schema_and_extra_fields` and
`test_snapshot_schema.py` require complete exact parity, a populated task/wait-disposition roundtrip,
omitted/null legacy values, nested unknown-field rejection and wrong optional types. Regenerate only
the owning schema and retain both `$id`/`$schema`; no SQL/journal migration is needed for a static
declaration that lagged already-existing typed output. Reverting this declaration-only repair
restores the former parity failure; preserve all durable facts and do not remove runtime fields
to accommodate the old declaration. Running a multi-schema generator for this repair would touch
unrelated contracts and is unnecessary.

### Contract and validation matrix

| Facts | Projection |
|---|---|
| No admission table/record | legacy empty queue; do not initialize tables |
| Valid admission with exact dispatch digest | read ordered role queue items and their latest claim |
| RUNNING + ACTIVE lease with expiry in future | LEASE_VALID; may own current_stage if Task role also matches |
| Expired/released claim or READY/WAITING item | no current-stage assignment; no claim of execution |
| Queue CLOSED | 本次执行已结束, not Task DONE or role verdict |
| Queue WAITING_HUMAN/WAITING_DEPENDENCY | taskGroup is blocked; raw gap ID/hash is not shown as user guidance |
| Current nonterminal successor has a WAITING queue item before parent attachment | Requirement shows the queue wait, clears superseded Manager advice, keeps exact parent checkpoint hash |
| Current knowledge gap / approved resolution | Manager shows waiting for knowledge / approved and waiting to continue; Task badge shows scheduling wait, with delivery checkpoint separately retained |
| CLOSED historical knowledge queue item | Does not override current delivery or DONE |
| Admission/Task/repository/assignment/lease binding drift or multiple open roles | reject read; never repair facts on GET |

Good: Task is at QA checkpoint but the expired QA lease is not shown as QA executing.
Base: legacy Task without admission remains readable. Bad: infer online execution from dispatch alone.
Wrong: label all CLOSED entries “交付完成”. Correct: render queue lifecycle separately from Task verdict.

`tests/team_view/test_live.py::test_real_inflight_joint_and_terminal_reads` checks actual RUNNING claims,
heartbeat and all-CLOSED terminal history with no writes. `ui.test.cjs` verifies localized status,
heartbeats and waiting task-group placement. Existing schema, read-only, stale-poll and isolation gates
still apply; existing production data needs no SQL rewrite.

`test_live.py::test_current_queue_wait_overrides_stale_parent_and_active_delivery` and
`delivery-status.test.cjs` cover the pre-attachment wait and current knowledge gate. Existing
recovery waits are attached through Continue after service reload; GET only projects facts.

A RUNNING/QUEUED Console Continue operation is not evidence that the paused role has resumed.
`requestPresentation` keeps a durable current role WAITING state ahead of that operation;
`managerFlowStatus` may show coordination in progress alongside the role wait. `deliveryFlow`
marks the corresponding Coder/QA/Reviewer step blocked, never current/animated. The delivery
checkpoint stays unchanged. Only new queue facts can remove the waiting presentation.
### Blocker detail localization (2026-10-03)

`team_view/blocker_text.py::_role_failure` checks the exact Codex diagnostic
`Codex CLI left changes after an interrupted execution; cause=TIMEOUT` before generic
TIMEOUT wording. The Chinese read-side reason states the local execution timeout, retained
changes, missing admissible report and exact recovery approval. Keep Run and bounded evidence
SHA references; do not claim provider outage, deliberate permission abuse or exhausted retries.
Generic clean timeout retains its existing wording. Recompute from old durable reasons on GET;
never rewrite sealed Task/checkpoint/Run facts. Regression:
`tests/team_view/test_blocker_text.py::test_localizes_interrupted_codex_timeout_with_retained_changes`.

The read-side presentation must preserve the stable cause of a blocked role. Candidate
context-budget refusals, authentication/limit/timeout failures, invalid evidence
references, artifact validation failures and interrupted dirty worktrees each have a
specific Chinese explanation and an actionable next step. The projection may retain
opaque Run IDs, evidence digests and candidate SHAs, but must not echo provider bodies,
secrets or model-authored arbitrary prose. Unknown safe summaries remain visible rather
than being relabeled as PASS or collapsed into a misleading stage.

An active child Delivery or current Task queue fact takes precedence over stale Manager
coordination advice. A terminal BLOCKED/FAILED Task remains blocked in the UI; a Continue
operation or a planned assignment does not make it executing without a current lease and
heartbeat. These are read-side rules only and never repair a journal or SQL fact.


### Deleted Requirement verification history

Read-side retirement filtering must use every validated JointJournal checkpoint and the
full native delivery history, including previously replaced/derived child identities.
VerificationReservation is still durable audit data after deletion; before projecting or
reporting a missing source Task, exclude only the exact `(repository_id, source_task_id)`
pairs owned by a validated retired parent. Do not hide arbitrary missing sources: active
reservations in a visible repository still fail closed on missing/cross-repository sources.
Retired and visible native sources cannot share a global Task ID, including across different
repositories; reject this ambiguity before SQL projection.

`ProductionTeamReader.snapshot(project_id)` and `GET /api/v1/team` must continue to return
visible requirements, other DONE work and correct project counts after a deleted source
has old verification reservations. The reader remains read-only: no cancellation, Task
update, verification completion or record deletion can occur during projection.

Regression cases must combine a deleted requirement's historical child/reservation with
another visible delivery in the same repository, then assert successful public GET, no
retired parent/native/verification in requests/tasks/agent references, and unchanged visible
DONE work. A missing active source must remain a TeamReadError/503 rather than disappearing.

## Historical child membership after same-Requirement upstream correction

### 1. Scope / trigger

An exact authorized upstream correction can clear current `children` and `plan` while retaining old
native failure facts in the joint journal. The original Requirement remains the product identity.
Its historical native child must remain subordinate audit work, even before a new plan/child exists.

### 2. Signatures

```python
_joint_scopes(JointCheckpoint, Mapping[str, _Native]) -> tuple[ScopeView, ...]
_native_requirement_ownership(
    Mapping[str, tuple[JointCheckpoint, ...]], Mapping[str, _Native]
) -> dict[str, _NativeRequirementOwner]
_current_requirement_work(
    list[TaskView], *, historical_native_ids: frozenset[str]
) -> list[TaskView]
_agent_views(
    tuple[AgentProfile, ...], list[RequestView], list[TaskView], *,
    historical_work_ids: frozenset[str] = frozenset()
) -> tuple[AgentView, ...]
```

### 3. Contracts

- Read and validate every joint/native journal prefix before folding membership. Check Team/Project
  binding on every retained parent checkpoint. Attached children require their exact native ID,
  known unit, code scope/root and exact checkpoint in the stored native history. A current native
  advancement may preserve that old exact prefix; a replacement/future reference may not.
- Derive native IDs only for an unattached planned code unit using `DerivedStageInputs`. An attached
  child always keeps its committed native identity, even when a plan changes or disappears.
- The permanent membership key is native ID; the typed owner binds parent ID, unit ID and ScopeView.
  Repeated observations must have the same owner/scope. Cross-parent, cross-unit/root/repository or
  active/retired conflicts fail closed. Never infer ownership from title, prose or timestamps.
- Permanent membership controls standalone fallback and historical `TaskView.request_id`; current
  `RequestView.scopes[].delivery_id` still comes exclusively from the latest checkpoint. Empty
  current plan/children leaves the scope ID empty; it does not recover an old child pointer.
- Keep historical Task status, blocker, assignments, queue, timestamps and evidence unchanged.
  Exclude noncurrent native sources from live parent composition and Agent assigned/current lists;
  verification/remediation descendants use `source_delivery_id` for that comparison. Member history
  remains available, including historical work whose checkpoint itself is not terminal.
- Frontend current-work helpers, phase/blocker projection, member blocked queues and current work
  counts must use the same latest-scope identity distinction. The full Requirement audit query
  retains every owned Task. A genuine independent same-title native Requirement remains visible.
  `app.js::currentRequestTasks(request)` first accepts only `(task.source_delivery_id || task.id)`
  in `request.scopes[].delivery_id`, then chooses the latest observation per source.
  `activeRequestTask` uses that same current set. Empty current scope IDs produce no current Task.
  `isHistoricalRequestTask(task)` requires exact parent/project and excludes Tasks outside that
  current set. `renderTeam` excludes those records from unfinished counts and blocked queues,
  and `taskRow` labels them `历史记录` without changing their saved terminal/status facts.
  `requestHistoricalDeliveryRecords(panel, request)` keeps a folded, keyed history section and
  original `showDetail("task", task.id)` links; original failures remain readable there and in the
  engineering disclosure. History has no delivery command or verdict controls.
  `pollingDetailFacts()` signs the full owned `requestTasks(item)` inventory for Requirement detail,
  because that surface consumes current and historical work. Updating only an old record must
  refresh its reason/time without changing current state or collapsing the history disclosure.
- Retired parent filtering reuses the same full-history ownership checks. Snapshot reads cannot
  delete a child, rewrite a journal, synthesize verdicts or construct mutation-capable Host services.

### 4. Validation and error matrix

| Facts | Expected read projection |
|---|---|
| Old BLOCKED child; current DESIGNING/PLANNING has empty children/plan | One parent Requirement; old child audit Task still references parent |
| Old child and later current child | Both audit Tasks belong to parent; scope/header/blocker/current queue use later child |
| Exact old native checkpoint, native has subsequently advanced | Accept stored history prefix; Task facts use latest native checkpoint |
| Same title on an independently submitted native delivery | Keep separate Requirement by exact ID |
| Unknown unit, wrong root/repository, absent or replaced/future checkpoint | Whole selected snapshot rejects with TeamReadError |
| One native claimed by multiple parents, including a retired owner | Reject ambiguity before retired/current filtering |
| Historical candidate verification/remediation source | Remains audit data; does not override current parent or member queue |
| Current child replaced/cleared during browser polling | Header, flow, queue/count and repository links update together; historical record remains accessible |
| Historical nonterminal Task with retained assignment | Grey historical label, no current unfinished count or executing member state; saved Task remains nonterminal |

### 5. Good / base / bad

Good: K1 corrects design in the same Requirement and the old failed native observation remains in
its audit history. Base: a normal attached child retains identity during integration replanning.
Bad: because current children are empty, label the old native as another same-title Requirement or
reinsert it as the current blocker. Deleting that apparent duplicate would discard the distinction
instead of repairing the read model.

### 6. Required incremental tests

`tests/team_view/test_live.py` covers cleared children in DESIGNING/PLANNING, later-child isolation,
same-title standalone preservation, old-prefix advancement, all retained-reference corruption
cases, active/retired parent ambiguity, historical member assignments and verifier/remediation
source filtering. Assert before/after file inventories are identical. Retain the existing
`test_joint_reader_*`, real in-flight role and retirement regressions; use the isolated test database
serially for selected MySQL cases. UI regressions must render the actual Requirement list/header
and member queue from the same snapshot shape. No full test suite is required for this repair.
`tests/team_view/historical-child.test.cjs` covers empty current IDs, newer source-bound verifier,
old active/waiting/expired role exclusion and independent same-title native scope. Real Chrome
`browser/historical-child.test.cjs` checks original history navigation, no current red node or
blocked member queue, grey history label and unchanged nonterminal inventory. Retain affected
delivery-status, engineering-wait, operation-progress, UI and browser polling/history contracts;
fixtures must provide truthful current scope bindings rather than bypassing this filter.

### 7. Existing-data disposition, rollback and failure analysis

No SQL/journal migration or deletion is needed. K1's verified historical child already establishes
its parent membership; deploy/reload the fixed reader while execution is idle, then refresh the same
Project. Continue against that original Requirement's current exact checkpoint if it needs an
authorized action. Roll back code while idle and preserve all old/current immutable records.

1. **Root cause (cross-layer state projection):** identity membership was reconstructed only from
   the latest checkpoint; current-execution reset incorrectly became loss of historical ownership.
2. **Why previous fixes missed it:** integration replanning tests kept DONE children, while retirement
   alone scanned full history. Neither covered upstream correction clearing both current pointers.
3. **Prevention:** centralize exact historical membership and current scope projection; regress the
   empty-current window before a later child exists, with no production writes.
4. **Systematic expansion:** apply the same source distinction to parent live blockers, candidate
   verification/remediation descendants, member queues and counters, not only list deduplication.
5. **Knowledge capture:** this contract and the new Trellis task document the historical/current
   boundary. No generated specification/template mirror exists for this read-side module.
