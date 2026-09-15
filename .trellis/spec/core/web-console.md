# Local Web Console Contract

## 1. Scope / Trigger

修改 `web_console/`、浏览器交付操作、Team View 中的写入口、后台 Manager 执行、
Operation 持久化或 `ase-console` 生产装配时必须遵守本规范。只读投影仍同时遵守
[`live-team-view.md`](live-team-view.md)，Delivery 恢复仍同时遵守
[`delivery-recovery.md`](delivery-recovery.md)。

v0.1 是可信本机、单用户、loopback 控制台，不是远程多租户控制面。

## 2. Signatures

```python
ProjectConsole.submit(
    intent: ConsoleIntent,
    *,
    idempotency_key: str,
) -> ConsoleOperation
ProjectConsole.get(operation_id: str) -> ConsoleOperation
ProjectConsole.list_operations() -> tuple[ConsoleOperation, ...]
ProjectConsole.run_once() -> ConsoleOperation | None

ConsoleOperationStore.submit(...) -> ConsoleOperation
ConsoleOperationStore.claim_next(*, at: datetime) -> ConsoleOperation | None
ConsoleOperationStore.succeed(...) -> ConsoleOperation
ConsoleOperationStore.fail(...) -> ConsoleOperation
ConsoleOperationStore.interrupt_running(...) -> tuple[ConsoleOperation, ...]

ManagerConsoleAdapter.execute(intent: ConsoleIntent) -> ConsoleCommandResult
RequirementSourceRevisionDrift -> ConsoleCommandRejected(
    code="SOURCE_REVISION_DRIFT",
    safe_summary=<stable source-drift message>,
)
create_console_app(
    console: ConsoleApplication,
    reader: TeamReader,
    *,
    team_id: str,
    port: int = 8765,
    administration: ConsoleAdministration | None = None,
    directory_chooser: DirectoryChooser | None = None,
    delivery_ready: bool = True,
) -> FastAPI
NativeDirectoryChooser.choose() -> tuple[str, ...]
ConsoleAdministration.upload_requirement_screenshot(
    project_id: str,
    delivery_id: DeliveryId | str,
    expected_checkpoint_sha256: CheckpointDigest | str,
    *, filename: str, content: bytes,
) -> RequirementScreenshot
production_console_app(
    environment: Mapping[str, str] | None = None,
    *,
    port: int | None = None,
) -> FastAPI
```

`ConsoleIntent` 当前只允许：

- `CREATE_PROJECT(name, project_id?)`；
- `CREATE_REQUIREMENT(project_id, name, repository_roots)`；
- `UPDATE_REQUIREMENT(project_id, delivery_id, expected_checkpoint_sha256, name, repository_roots)`；
- `CLOSE_REQUIREMENT(project_id, delivery_id, expected_checkpoint_sha256)`；
- `RESTART_REQUIREMENT(project_id, delivery_id, expected_checkpoint_sha256)`；
- `DELETE_REQUIREMENT(project_id, delivery_id, expected_checkpoint_sha256)`；
- `PRODUCT_REPLY(project_id, delivery_id, expected_checkpoint_sha256, message, screenshot_ids)`；
- `PRODUCT_APPROVAL(project_id, delivery_id, expected_checkpoint_sha256)`；
- `CONTINUE_DELIVERY(project_id, delivery_id, expected_checkpoint_sha256,
  approved_scope_sha256?, approved_plan_sha256?)`；一次只能提交一个 approval digest。

公开持久化契约是 `schemas/console-operation.schema.json`。

## 3. Contracts

### 3.1 Command/query separation

- `ProductionTeamReader` 和 Team View projection 永远只读；不得为了方便在 snapshot/GET 中装配
  `TeamHost`、初始化数据库、创建 workspace 或推进 Delivery。
- 浏览器命令只能进入 `ProjectConsole`；它不重新实现 Product、Designer、Planner、Delivery、QA、
  Reviewer 或 recovery 规则，只委托现有 Manager application interfaces。
- Operation 是“浏览器操作执行状态”，不是 Task、Delivery、Artifact 或 verdict 的替代权威。
  成功、失败或重启后继续都必须重新读取 durable Delivery facts。

### 3.2 Persist before execution

- HTTP 先校验 typed intent，再将 `QUEUED` Operation 追加到
  `team/work-items/console-operations/operation_<id>/000001.json`，最后返回 `202`。
- HTTP request handler 不执行 provider；后台 dispatcher 领取后追加 `RUNNING`，完成后追加一个终态。
- Operation 状态只允许：
  `QUEUED → RUNNING → SUCCEEDED | FAILED | INTERRUPTED`。
- 每个 record 包含 previous digest、immutable intent digest 和自身 digest；文件名必须等于六位 sequence。
  生产写使用进程锁、exclusive append 和 fsync，不覆盖历史。
- operation ID 由 team + browser idempotency key 稳定派生。同一个 key + exact intent 返回同一
  Operation；同 key 不同 intent 拒绝。同一 Delivery 同时只允许一个非终态 Operation。

### 3.3 Recovery and at-most-once boundary

- Host 启动时把遗留 `RUNNING` 标记为 `INTERRUPTED`，不得自动再次调用 provider。
- 用户在 UI 点击统一“继续交付”时，新的 Operation 根据当前 Delivery checkpoint 决定下一动作；
  已完成阶段不重跑，不确定模型调用遵守既有 recovery/verification approval 规则。
- Coder 现场存在原 Task 权限遗漏路径时，Manager 必须先返回 `coder_scope` 审批请求，列出 exact
  relative paths 并绑定 scope digest。UI 的“批准文件范围”只提交 `approved_scope_sha256`，这一步
  不能启动 Agent；平台获准捕获后必须再返回独立的 `coder_recovery` plan 审批。
- UI 只能批准 Manager 返回并验证过的 exact scope/recovery/verification SHA。SHA 可以隐藏在
  控件中，但批准前必须显示精确遗漏路径、候选提交、Agent/模型或保留修改/目标基线等可理解事实。
- checkpoint、retained paths、原 permissions/deny-list、scope 或 plan 已变化时必须拒绝；刷新最新
  投影后重新提交，不得自动替换用户批准对象。

### 3.4 Security and process boundary

- Uvicorn 只监听 `127.0.0.1`；transport 要求 exact `Host=127.0.0.1:<port>`，Origin 缺省或同源。
- POST 只接受 `application/json`，body 最大 64,000 bytes；输入错误返回稳定小型 error envelope，
  不回显完整 payload、traceback、secret 或未经边界验证的模型文本。
- Repository 源码目录必须是唯一、无控制字符、无 lexical `..` 的绝对路径；真正的 Git/规范约束仍由
  Manager prepare 校验。
- Requirement 页面不得接受自由文本目录。`POST /api/v1/admin/directories/select` 只调用平台固定的
  macOS/Linux 本机目录选择器命令，返回真实、非 symlink、规范化的绝对目录；浏览器只移除或提交
  这些返回值，取消选择不是错误。
- Requirement 截图使用 `application/octet-stream` 上传到当前 Project/Delivery/checkpoint 的固定
  endpoint；单张不超过 10 MB，只接受 PNG/JPEG/WebP magic bytes。回复只提交最多 4 个已验证
  attachment ID，不能提交文件路径或 data URL。CSP 只额外允许本机 blob/data 图片预览。
- static assets 使用 `textContent` 渲染外部文本；CSP 禁止外部 script/style、frame 和 form action。
- MySQL DSN/API key 是 write-only 输入：不得出现在 API response、Operation、日志、普通配置 JSON、
  plist 或 systemd unit。当前可信本机 MVP 可写入配置文件同目录的 `runtime.env`，必须 canonical
  quote、原子替换、权限 `0600` 且只包含当前 ProductionConfig 引用的 allowlist 名称。未来
  Keychain/Secret Service adapter 替换本地 store 时不得改变该 write-only API 契约。

### 3.5 User-visible flow

- 日常用户可在网页完成：Project 创建/选择、带 1–N 个 Repository 目录的 Requirement 创建、Product 对话、ProductSpec 批准、统一继续、exact
  Coder 文件范围补充审批、recovery/verification 计划批准、进度观察和 Candidate 领取。
- 新建 Requirement 通过本机弹窗一次选择多个代码目录；Product 对话支持文字、直接粘贴截图或两者组合，
  不显示截图文件选择控件。截图增删后，预览、已选集合和瞬时反馈必须同步；移除截图不得继续显示
  “截图已添加”，移除最后一张后预览区必须隐藏。
- Project 知识库的 Project selector 必须同时用可见 `selected` 样式和 `aria-selected/aria-current`
  标识当前 Project；切换后资产列表与选中态使用同一个 `selected_project_id` 重绘。
- UI 术语固定为 Team `通用知识`、Project `背景知识`；两者底层仍复用内容寻址的 knowledge document
  契约，不能因为展示名称不同而复制存储或选择逻辑。
- Requirements 页把 Project 创建放在 Project 上下文区，把 Requirement 创建放在需求列表标题与
  数量旁；两者不得作为脱离所有权上下文的全局页头动作。
- 只有尚未开始 Product 对话且无活动 Operation 的 `READY_FOR_DISCUSSION` Requirement 显示编辑；
  ProductSpec 批准前的 READY/Product 对话阶段均可逻辑删除。编辑复用预填名称与精确目录的弹窗；
  目录新增仍只来自原生目录选择器。删除必须先确认。
  UPDATE 成功后选中返回的 replacement Delivery；DELETE 成功后清除已退休选择。
- 终态 `BLOCKED` Requirement 可在 exact checkpoint fence 下“关闭需求”或直接“删除需求”。关闭追加
  `CLOSED` checkpoint、停止继续交付并进入独立“已关闭”清单；`CLOSED` 可通过
  `RESTART_REQUIREMENT` 追加 `BLOCKED` checkpoint，之后再由现有“继续交付”显式恢复执行。删除只追加
  Project retirement 记录，完整 journal、子 Task 与证据不擦除，但父需求及其所有派生子 Task 必须
  同时退出当前 Project 与 Agent 队列投影。活动中的批准后 Requirement 仍不得删除。
- `CLOSE_REQUIREMENT`、`RESTART_REQUIREMENT`、`DELETE_REQUIREMENT` 的 QUEUED/RUNNING Operation
  只表示生命周期命令正在处理，不得把原本阻塞或关闭的 Requirement 显示成“进行中”。只有
  `PRODUCT_REPLY`、`PRODUCT_APPROVAL`、`CONTINUE_DELIVERY` 或真实活动子 Task 可以覆盖交付展示阶段。
- 配置 Repository HEAD 正常前进时，旧 Requirement 继续使用自己的 retained baseline，不产生错误。
  只有 Requirement baseline commit/worktree identity、HEAD 或 clean 状态不可验证时，Manager 才把
  typed `RequirementSourceRevisionDrift` 映射为 `SOURCE_REVISION_DRIFT`。Team View 也必须识别升级前
  已持久化的 legacy `COMMAND_REJECTED` source-drift summary。此时不得提交旧 Delivery 的继续/回复/
  批准动作；应说明需要恢复该需求基线，无法恢复时才提供预填的“基于当前代码新建需求”入口。
- 需求列表中的整张 Requirement card 是一个选择控件，而不是只有标题文字可点：click 与键盘
  `Enter`/`Space` 必须打开同一个详情；详情、唯一 `aria-current` 与可见 selected 样式必须同步指向
  同一 Requirement，轮询不得把它们恢复到列表第一项。
- Requirement 详情必须使用一个稳定摘要区和同级 section：交付流程、涉及代码目录、Product 对话/输入、
  操作/批准、交付结果、阶段产物。所有同级 section 使用 `--detail-section-space` 作为分割线两侧的
  唯一垂直间距，标题统一为 `h2`；子级需求名称使用 `h3`，ID、状态和下一步保持辅助信息层级。
  section 不得再叠加独立 `margin-top`，流程组件也不得通过额外底部 margin 改变下一条分割线的位置。
- “交付流程”section 只展示七个节点及其当前/已完成状态，不追加 `QUEUED`/`RUNNING`、Manager
  恢复、离开页面或串行推进文案。Operation 状态只在全局操作/结果入口展示，Product 处理状态只在
  需求讨论 composer 内展示。当前子 Task 已开始时，Requirement 列表/摘要优先显示子 Task 阶段并
  隐藏旧父 checkpoint blocker；需求讨论只保留已提交的双方消息。活动子 Task 存在时不得再次显示
  “继续交付”。
- 设置页的模型路由分为可用模型目录和 Agent 策略。启用目录路由只使其可选，不自动成为
  备用模型；每个 Agent 选择一个主模型，并可从目录中显式添加、移除、上移或下移 0–N 个备用模型。
- 一个 Task 的 Coder/QA/Reviewer 串行。UI 只把 `current_stage=true` 的 assignment 标成执行中；
  已完成/未来角色不得同时显示为运行。
- DONE 只展示已经由 durable facts 证明的 candidate commit、可唯一定位的 branch 和验证证据。
  v0.1 不自动 merge、push 或 deploy。
- FAILED/INTERRUPTED Operation 是不可变审计事实，但通知卡不是永久页面状态。用户可在浏览器关闭
  该卡；同一 Requirement/动作出现更新的成功 Operation 后，旧失败卡自动隐藏。关闭只写入有界的
  本地 UI 偏好，不修改 Operation 日志、Delivery checkpoint 或错误证据。
- `SUCCEEDED` 只表示 Manager 命令已完整返回，不等于 Delivery 已推进。若 result stage 仍是
  `WAITING_HUMAN/BLOCKED/FAILED` 且没有可批准计划，需求页必须保留可关闭的结果卡并显示 safe
  `next_action`；同一 Requirement 只显示最新一张需要人工关注的成功结果，避免历史阻塞卡堆叠。
- 阻塞原因只在 Requirement 详情的“阻塞信息”同级 section 展示。该 section 合并相同子仓原因，
  按“当前阻塞 / 最近一次恢复 / 建议操作”呈现，并把已知内部英文状态转换为面向用户的说明。
  顶部 Operation 卡只提示前往该 section；“打开需求工作区”必须切换到需求页、选中 exact target
  Requirement 并滚动到详情。Team 队列卡和 Requirement 列表卡不得重复完整阻塞文本。
- `ase request`、`verify-*` 和底层 Runtime 保留作运维/诊断/break-glass，不是 README 的日常入口。

## 4. Validation & Error Matrix

| Case | Required result |
|---|---|
| Valid Project or new Requirement with one or many absolute roots | persist QUEUED, return 202, background Manager performs the typed action |
| Exact idle READY Requirement edit | persist UPDATE; Manager publishes replacement and retires original |
| Exact idle pre-approval Requirement delete after confirmation | persist DELETE; original leaves current inventory but dialogue/history remains |
| Exact BLOCKED Requirement close | append CLOSED successor; retain Requirement and all history; disable continuation |
| Exact CLOSED Requirement restart | append BLOCKED successor; retain history; wait for explicit continue |
| Exact BLOCKED/CLOSED Requirement delete | retire from current inventory; preserve journal, child Tasks and evidence |
| Retired Requirement owns native child deliveries | omit parent, children and their Agent queue entries from current projection |
| Close/restart/delete Operation is queued or running | keep the durable blocked/closed presentation; never show active delivery |
| Edit after Product discussion, delete an active post-approval Requirement, or stale checkpoint | terminal safe failure; no retirement or history mutation |
| Browser refresh/disconnect after 202 | accepted Operation continues; repeated same key returns same identity |
| Same idempotency key, changed intent | 409; original Operation unchanged |
| Second active command for same Delivery | 409; no second provider call |
| Relative/duplicate/lexical-parent path | 422 before persistence or project access |
| Directory picker cancelled | return an empty successful selection; do not create a Requirement |
| Picker executable missing/fails or returns relative/symlink/missing path | 503; no browser text fallback |
| Empty Product text with 1–4 valid screenshot IDs | accept and bind immutable attachments into dialogue |
| Empty text and no screenshot / duplicate or foreign attachment ID | 422; no Product invocation |
| Two Requirements in the same visible group | clicking either card body opens and marks that exact Requirement as the sole selection; polling preserves it |
| Requirement detail contains empty or populated Product/artifact modules | every module heading remains the same level and every divider has the same spacing on both sides |
| Delivery has active continue Operation or child Task | seven flow nodes only; no Manager/operation prose in the flow section |
| Enabled model exists in catalog but is not selected by an Agent | save succeeds; it is never serialized or shown as that Agent's fallback |
| Screenshot over 10 MB, unsupported magic, stale checkpoint or wrong stage | 413/422; no dialogue mutation |
| Stale displayed checkpoint | terminal FAILED with `STALE_CHECKPOINT`; no model call |
| Configured checkout HEAD advances after Requirement intake | old Requirement stays actionable against its retained baseline; no error card |
| Retained Requirement baseline commit/worktree drifts | terminal FAILED with `SOURCE_REVISION_DRIFT`; explain restore path and optionally offer prefilled CREATE |
| Existing legacy source-drift Operation uses `COMMAND_REJECTED` | recognize its bounded summary as the same terminal UI state without rewriting the Operation |
| Coder dirty inventory contains paths omitted by original policy | SUCCEEDED Operation carries `coder_scope`, exact visible paths and hidden scope digest; no content capture or Agent run yet |
| Scope approval submitted with exact current digest | capture is allowed only for those paths; next response still requires an independent recovery plan approval |
| Scope paths, checkpoint, original permissions or deny-list drift | old approval is rejected; recompute and show the current exact scope |
| Scope request targets denied, invalid, symlink, sensitive or otherwise unsafe path | fail closed; never offer an approval that broadens hard safety policy |
| Recovery/verification approval required | SUCCEEDED Operation carries safe facts plus exact hidden plan digest |
| Host exits during RUNNING | next startup appends INTERRUPTED; never silently replay |
| Executor raises an unexpected exception | terminal FAILED with generic safe summary; no traceback in browser |
| User closes a FAILED/INTERRUPTED notification | hide the card locally; keep durable Operation query/audit unchanged |
| Later success for same action and Requirement target | suppress the older failure card automatically |
| SUCCEEDED continue returns BLOCKED/FAILED without approval | keep the latest dismissible card and show its safe next action; never appear unresponsive |
| Same blocker appears on parent, child and latest Operation | one consolidated blocker section; operation card only links to it |
| Operation shortcut targets a Requirement from another visible tab | switch to Requirements, select exact target and scroll its detail into view |
| Missing production config/MySQL/team | startup/read fails safely; no fake workspace or data |
| Foreign Host/Origin, non-JSON or oversized body | 403 / 415 / 413 before command execution |
| Read-only legacy Team server | UI remains read-only and explicitly reports console unavailable |
| DONE with unique `ai/<task>/attempt-*` ref | display exact candidate branch; ambiguous/missing branch stays omitted |

## 5. Good / Base / Bad Cases

- Good: 用户提交多仓需求后关闭页面；Operation 已落盘，后台完成 prepare；重新打开后看到成功操作和
  READY_FOR_DISCUSSION 需求，不需要复制任何 ID/SHA。
- Base: 没有需求时显示空团队/空需求；旧 `ase team serve` 提供只读视图，写按钮禁用。
- Bad: POST handler 直接同步运行 Product/Coder，浏览器断开造成结果未知且再次点击重复扣额度。
- Bad: Host 重启把 RUNNING 改回 QUEUED 并重放同一个 provider Run。
- Bad: 把 source revision drift 显示成普通中断并继续提交 `CONTINUE_DELIVERY`；这会在模型调用前重复失败。

## 6. Tests Required

- `tests/web_console/test_core.py`：memory/file store 幂等、单 Delivery admission、persist-before-run、
  safe failure、重开 hash chain 与 orphan RUNNING interruption。
- `tests/web_console/test_manager.py`：全部 typed intent 委托、Project 边界、exact checkpoint、stale 拒绝、
  source-drift 专用错误码、separate scope/recovery/verification digest forwarding 和 safe facts。
- `tests/web_console/test_transport.py`：lifespan、assets/query、202 submit、operation query、Host/Origin、
  content type、body/input limit、409/404 和安全 headers。
- `tests/team_view/ui.test.cjs`：多目录创建、Product/继续/批准操作、操作状态、刷新保持、hidden digest
  不直接渲染、只读 fallback、单 Task 串行角色状态、安全文本、Requirement 详情统一标题/分割节奏，
  粘贴截图移除后的预览和反馈同步、READY draft 编辑、Product 批准前删除、阻塞需求关闭/删除、
  已关闭需求独立筛选与重启、生命周期 Operation 不冒充活动交付、
  仅含节点状态的交付流程、source-drift 重建，
  以及失败通知关闭/成功替代、successful-but-blocked 反馈、同 Requirement 去重、阻塞信息唯一入口与
  Operation 快捷跳转。
- `tests/team_view/test_live.py`：candidate branch 必须从 exact candidate ref 唯一推导；退休父需求的
  native child deliveries 与 Agent 队列投影必须同时消失。
- `tests/contracts/test_json_schema_contracts.py`：Python/JSON Schema 的 QUEUED/RUNNING/terminal 状态、
  mutually exclusive scope/plan approvals、`coder_scope` result 和 path 约束一致。

全量回归由人工按项目流程执行；实现 Agent 只运行本次改动的 focused cases、Ruff、strict Mypy、
schema/example 检查和离线构建。

## 7. Wrong vs Correct

```python
# Wrong: a write sneaks into the read model and blocks every dashboard refresh.
reader.snapshot()
host.resume_delivery(command)

# Correct: query and command modules are siblings; browser intent is durable before execution.
snapshot = reader.snapshot()
operation = console.submit(intent, idempotency_key=browser_key)
```

```python
# Wrong: process restart retries a provider call whose outcome is uncertain.
for operation in running:
    store.requeue(operation)

# Correct: record interruption; a new user-approved continue resolves current Delivery facts.
store.interrupt_running(at=clock())
```

```javascript
// Wrong: silently treat every configured path or a whole directory as recovery authority.
submitOperation({ action: "CONTINUE_DELIVERY", approved_plan_sha256: broadRecoveryPlan })

// Correct: bind the exact omitted paths to the first button; a later button approves the plan.
submitOperation({ action: "CONTINUE_DELIVERY", approved_scope_sha256: approval.plan_sha256 })
submitOperation({ action: "CONTINUE_DELIVERY", approved_plan_sha256: recovery.plan_sha256 })
```

```javascript
// Wrong: ask the user to copy a 64-character checkpoint, scope or plan digest.
prompt("plan sha256")

// Correct: bind the exact digest to the button while rendering the facts being approved.
submitOperation({ action: "CONTINUE_DELIVERY", approved_plan_sha256: approval.plan_sha256 })
```

```javascript
// Wrong: keep appending orchestration prose beside durable delivery nodes.
flow.append("Manager 正在重新交付，可以离开页面后再回来")

// Correct: flow is status-only; operation state has its own durable presentation.
flow.append(deliveryFlow(request))
renderOperationStatus(latestOperation(request.id))
```

```javascript
// Wrong: classify normal main-branch progress as drift for an older Requirement.
if (configuredHead !== requirement.baseRevision) markSourceDrift(requirement)

// Correct: verify the Requirement-owned baseline; current main HEAD is unrelated.
verifyRetainedBaseline(requirement.id, requirement.baseRevision)
```

## Scenario: blocked Requirement enters an explicit recovery approval

### 1. Scope / Trigger

Use when a successful `CONTINUE_DELIVERY` Operation returns `result.approval` while the durable
Requirement/child checkpoint intentionally remains `BLOCKED`. This is expected for `coder_scope`,
`coder_recovery`, and `candidate_verification`; an approval request is a new operator action, not a
new delivery failure.

### 2. Signatures

```javascript
latestApproval(deliveryId, checkpointSha256) -> ConsoleApprovalRequest | null
requestBlockingSummary(request) -> { reasons, operationReason, approval, suggestedAction } | null
recoveryApprovalBox(request, approval) -> HTMLElement
```

### 3. Contracts

- The unconsumed approval must be rendered inside the Requirement's single `阻塞信息` module,
  adjacent to the retained blocker and before unrelated discussion/artifact modules.
- Once an approval exists, retained Task failure text is labelled `原始阻塞`; it must not be shown
  as though the just-completed continue Operation failed again.
- `coder_scope` names every exact omitted path and renders `批准文件范围`; it must not use generic
  recovery-plan wording. The digest remains bound to the button and is never rendered.
- The joint parent may remain `BLOCKED` while the child returns the approval. UI state is derived
  from the successful Operation plus exact checkpoint, not from a synthetic stage transition.

### 4. Validation & Error Matrix

| Snapshot / Operation | Required UI |
|---|---|
| BLOCKED + successful unconsumed `coder_scope` | Original blocker is humanized; exact paths, explanation and approval button appear in `阻塞信息` |
| BLOCKED + successful unconsumed recovery/verification plan | Plan-specific suggestion and `批准并继续` appear in `阻塞信息` |
| Approval digest already submitted | Old approval disappears; normal continue/current result is shown |
| Failed continue Operation | Failure remains the latest recovery result; no approval is fabricated |
| Approval checkpoint differs from current checkpoint | Approval is stale and not rendered |

### 5. Good / Base / Bad Cases

- Good: the first continue click discovers one omitted file; the page clearly asks for that exact
  scope approval without implying Coder ran twice.
- Base: no approval exists; the durable current blocker and normal continue action remain visible.
- Bad: leave the old raw Coder failure under `当前阻塞` and place the actual approval below the
  discussion, making a successful continuation look like the same error repeated.

### 6. Tests Required

`tests/team_view/ui.test.cjs` must combine a durable BLOCKED snapshot carrying the original machine
policy failure with a successful, same-checkpoint `coder_scope` Operation. Assert the approval button
is a descendant of `request-blocking-section`, exact paths are visible, digests/raw failure text are
hidden, and the button submits only `approved_scope_sha256`.

### 7. Wrong vs Correct

```javascript
// Wrong: checkpoint stage alone decides what the last click did.
showCurrentError(request.blocker)
appendApprovalAfterDiscussion(operation.result.approval)

// Correct: preserve history while presenting the successful next operator gate in one place.
const approval = latestApproval(request.id, request.checkpoint_sha256)
showOriginalBlockerAndApproval(request.blocker, recoveryApprovalBox(request, approval))
```

## Scenario: singleton Team, Project, document knowledge and production settings administration

### 1. Scope / Trigger

Applies to `web_console.administration`, `/api/v1/admin/*`, Project creation, browser document upload,
or mutation of the secret-free production configuration. It does not turn Team View into a write
model and does not authorize remote/multi-user administration.

### 2. Signatures

```python
ConsoleAdministration.team() -> TeamSummary
ConsoleAdministration.projects() -> tuple[ProjectSummary, ...]
ConsoleAdministration.create_project(request: CreateProjectRequest) -> ProjectSummary
ConsoleAdministration.knowledge() -> tuple[KnowledgeDocumentView, ...]
ConsoleAdministration.document_content(document_id) -> KnowledgeDocumentContentView
ConsoleAdministration.import_document(*, filename: str, content: bytes) -> KnowledgeDocumentView
ConsoleAdministration.replace_document(document_id, *, filename, content) -> KnowledgeDocumentView
ConsoleAdministration.delete_document(document_id) -> tuple[KnowledgeDocumentView, ...]
ConsoleAdministration.update_team_knowledge_selection(request) -> tuple[KnowledgeDocumentView, ...]
ConsoleAdministration.project_knowledge(project_id) -> tuple[KnowledgeDocumentView, ...]
ConsoleAdministration.project_document_content(project_id, document_id) -> KnowledgeDocumentContentView
ConsoleAdministration.import_project_document(project_id, *, filename, content) -> KnowledgeDocumentView
ConsoleAdministration.replace_project_document(project_id, document_id, *, filename, content) -> KnowledgeDocumentView
ConsoleAdministration.delete_project_document(project_id, document_id) -> tuple[KnowledgeDocumentView, ...]
ConsoleAdministration.update_project_knowledge_selection(project_id, request) -> tuple[KnowledgeDocumentView, ...]
ConsoleAdministration.team_specs() -> tuple[SpecDocumentView, ...]
ConsoleAdministration.create_team_spec(request: CreateSpecDocument) -> SpecDocumentView
ConsoleAdministration.delete_team_spec(spec_key) -> tuple[SpecDocumentView, ...]
ConsoleAdministration.update_team_spec_activation(request) -> tuple[SpecDocumentView, ...]
ConsoleAdministration.project_specs(project_id) -> tuple[SpecDocumentView, ...]
ConsoleAdministration.create_project_spec(project_id, request) -> SpecDocumentView
ConsoleAdministration.delete_project_spec(project_id, spec_key) -> tuple[SpecDocumentView, ...]
ConsoleAdministration.update_project_spec_activation(project_id, request) -> tuple[SpecDocumentView, ...]
ConsoleAdministration.project_learnings(project_id) -> tuple[LearningProposalView, ...]
ConsoleAdministration.collect_project_learnings(project_id) -> tuple[LearningProposalView, ...]
ConsoleAdministration.decide_project_learning(project_id, proposal_id, request) -> LearningProposalView
ConsoleAdministration.settings() -> SettingsSnapshot
ConsoleAdministration.update_settings(request: UpdateSettingsRequest) -> SettingsSnapshot
ConsoleAdministration.test_mysql_connection(request: MySqlConnectionRequest) -> MySqlConnectionResult
ConsoleAdministration.status() -> RuntimeStatusSnapshot
LocalRuntimeEnvironmentStore.load() -> dict[str, str]
LocalRuntimeEnvironmentStore.save(values: Mapping[str, str]) -> None

GET  /api/v1/admin/team
GET  /api/v1/admin/projects
POST /api/v1/admin/projects
GET  /api/v1/admin/team/knowledge
POST /api/v1/admin/team/knowledge?filename=<basename>
GET  /api/v1/admin/team/knowledge/<document_id>/content
PUT  /api/v1/admin/team/knowledge/selection
PUT  /api/v1/admin/team/knowledge/<document_id>?filename=<basename>
DELETE /api/v1/admin/team/knowledge/<document_id>
GET  /api/v1/admin/projects/<project_id>/knowledge
POST /api/v1/admin/projects/<project_id>/knowledge?filename=<basename>
GET  /api/v1/admin/projects/<project_id>/knowledge/<document_id>/content
PUT  /api/v1/admin/projects/<project_id>/knowledge/selection
PUT  /api/v1/admin/projects/<project_id>/knowledge/<document_id>?filename=<basename>
DELETE /api/v1/admin/projects/<project_id>/knowledge/<document_id>
GET  /api/v1/admin/team/specs
POST /api/v1/admin/team/specs
PUT  /api/v1/admin/team/specs/activation
DELETE /api/v1/admin/team/specs/<spec_key>
GET  /api/v1/admin/projects/<project_id>/specs
POST /api/v1/admin/projects/<project_id>/specs
PUT  /api/v1/admin/projects/<project_id>/specs/activation
DELETE /api/v1/admin/projects/<project_id>/specs/<spec_key>
GET  /api/v1/admin/projects/<project_id>/learnings
POST /api/v1/admin/projects/<project_id>/learnings/collect
POST /api/v1/admin/projects/<project_id>/learnings/<proposal_id>/decision
GET  /api/v1/admin/settings
PUT  /api/v1/admin/settings
POST /api/v1/admin/settings/test-mysql
GET  /api/v1/admin/status
```

`RuntimeStatusSnapshot` 中的 MySQL connectivity 是显式探测结果：浏览器只在进入 Status 页或
用户点击手动刷新时调用该查询；Team 的 5 秒轮询不得重复创建 MySQL 探测连接。

### 3. Contracts

- The configured Team is the single long-lived workforce. Administration may read it but does not
  create or switch Teams at runtime. The display name is fixed by the immutable Team manifest.
- Project creation uses `ProjectWorkspaceRegistry.create/register`; every Project is bound to the
  exact Team manifest and owns its Project knowledge, Repository catalog and Requirement root.
- Document upload accepts only `application/octet-stream`, a safe basename and at most 10 MB.
  Markdown/TXT must be UTF-8; PDF/DOCX are extracted by bounded dedicated parsers. Normalized output
  must be non-empty and at most 256 KB. Original bytes, `content.md` and a digest-bound manifest are
  published atomically under one content-addressed document directory.
- Import never accepts a server-side source path and never calls a model, silently summarizes or
  auto-selects a document. The Knowledge page exposes separate `团队通用知识` and `当前 Project 知识`
  scopes. Selection is an explicit document-ID set and atomically publishes `knowledge/selection.json`
  under the owning Team or Project sidecar.
- Team selection applies to every Project; Project selection applies only to that Project. A missing
  selection record may read legacy `ProductionConfig.*_knowledge_paths` only as a compatibility
  fallback. Once the browser writes a selection record, that sidecar is authoritative, including an
  explicitly empty selection.
- The Knowledge page presents Team Knowledge and Project Knowledge as independent primary modules.
  Team Knowledge contains `通用知识` and engineering Specs; Project Knowledge contains `背景知识`,
  engineering Specs, Learning improvements and its own Project selector. The global Project tabs are not shown
  over Team Knowledge, so Team-owned assets cannot look duplicated under every Project. Learning
  evidence is always Project-owned. A Spec POST accepts bounded JSON up to 512 KB,
  creates an immutable inactive version and returns its digest. Activation is a separate PUT carrying
  the exact selected IDs; there is never an implicit latest-version switch.
- The Knowledge workspace is inventory-first: the page directly renders only current documents or
  Specs plus a scope-aware import button. `导入通用知识` / `导入背景知识` and `导入开发规范` open
  focused modal forms, using the same interaction boundary as Project/Requirement creation. Import
  forms must not remain inline beneath every inventory. Neither modal contains a separate
  maintenance-mode selector. Background import may select at most 20 files per browser action, but
  each file still crosses the existing bounded single-document API independently; partial failures
  report the successful count and first failure.
  An exact normalized filename match with current inventory pauses before the first write and shows
  an explicit replacement-risk confirmation. Duplicate filenames inside one batch and ambiguous
  multiple existing matches are rejected before upload.
- `更新文档` fetches only the verified normalized Markdown through the scope-owned content GET, then
  opens a modal editor. Saving publishes a replacement through the existing PUT; PDF/DOCX source
  content is deliberately saved as Markdown after human editing. Auto-refresh may refresh in-memory
  facts while a modal is open but must not rebuild the DOM and discard unsaved input.
- Spec import accepts 1–20 Markdown/TXT files. Every file becomes one independent inactive Spec using
  a stable internal key and human-readable title derived from its filename; the batch shares roles,
  stages, Repository IDs, path globs and optional verification guidance. A key collision requires
  explicit confirmation because it creates a new immutable version. Roles and stages are explicit
  multi-selects with at least one selected value.
  Verification guidance may be empty when no proof method has been defined; the API still carries
  the field and enforces its maximum size.
- Background update transfers the previous enabled state and retires the old content-addressed ID.
  Spec card update opens a modal with the existing body and applicability, hides/reuses the stable key
  and publishes an inactive next version. UI delete requires confirmation; the API removes selection/activation first and then writes
  a digest-bound retirement record. Retired records leave current inventory and future Context but
  immutable source/version files remain available to already-bound historical deliveries.
- Learning collection reads only persisted failed QA/rejected Review artifacts. Before publication,
  an immutable authorization must bind the exact proposal SHA, action, target, operator and rationale;
  the completion decision is also immutable. An interrupted publication exposes the authorization and
  only the exact action can resume. Publishing to `SKILL` means a non-executable design record; it
  never installs or changes runtime code.
- Settings round-trip every current secret-free `ProductionConfig` field: platform root, active
  Team/name, database backend/DSN environment name, ordered model routes,
  Codex executable, live execution and Console port. `runtime_variables` accepts only names referenced
  by that submitted config and is request-only; referenced values never enter a response. A blank UI
  input means preserve the stored value, not erase it.
- Model routes use `(provider, model, reasoning_effort)` as their stable reference identity. The
  browser must detect a duplicate normalized triple before calling the Settings API and identify both
  conflicting route positions; the backend uniqueness validator remains authoritative. The same
  provider/model may appear more than once when each route has a distinct reasoning effort, and every
  Agent policy reference must preserve that effort. A legacy reference without effort is accepted only
  when its provider/model resolves to exactly one enabled route.
- `runtime.env` is sibling to `ASE_CONFIG`, UTF-8, at most 64 KB and contains only canonical
  `NAME='POSIX-quoted value'` entries. Names follow `EnvVarName`; duplicates, controls, noncanonical
  quoting, symlinks and non-files fail closed. Save uses same-directory temporary file, fsync, atomic
  replace and `0600`. This is an explicit ease-of-use trade-off for one trusted local operator.
- MySQL test accepts a proposed DSN or the effective stored/process value, validates its scheme and
  attempts one connection. Its response is only `{connected, message}` and must never echo the DSN,
  driver exception, username or password.
- Settings and Status are separate: Settings contains editable effective/default values; Status is
  read-only and reports config source, restart requirement, MySQL readiness/source, Codex resolution,
  actual delivery-runtime composition, live-model execution switch, Team preparation/knowledge
  counts and per-route credential readiness. `RuntimeStatusSnapshot.agent_model_routes` contains the
  fixed seven roles in organization order. Every role reports `policy_source` and its exact ordered
  `(provider, model, reasoning_effort)` routes enriched with the catalog readiness facts. This is
  configuration readiness, not evidence that the Agent is currently running or calling that model.
  The separate `model_routes` catalog remains visible as “可用模型目录”. Zero knowledge is neutral.
  MySQL connectivity alone must not imply the full delivery runtime is ready.
- Full Console operation cards are rendered only on `需求与交付`. The browser may keep loading the
  durable operation facts because Requirement detail/recovery uses them, but successful operation
  history must not be repeated on Team, Knowledge, Settings or Status pages.
- The global navigation is grouped by ownership: Team, Project work, Knowledge assets and System.
  Every page renders an explicit `Team / Project / Platform` context band. The Team page Project
  control is labelled as a workload filter; it must never imply that AgentProfile belongs to a
  Project. Settings and Status are Platform Host pages and never render a Project selector.
- The Team page keeps the fixed organization role order and renders one selected Agent queue from
  existing assignment/history facts. Queue columns are `待完成 / 进行中 / 已阻塞 / 已完成`;
  `进行中` requires the exact current-stage assignment, `待完成` is a non-current active assignment,
  and terminal history must not be presented as live work. The board states that its workload is
  limited to the selected Project snapshot.
- Requirements use a wide-screen master/detail layout: a searchable Project picker scales beyond a
  handful of Projects; Project and Requirement creation use focused modal dialogs. Filtered top-level
  Requirements are the master side, while Repository Tasks, exact delivery stage, next action,
  repository scope, candidate and evidence stay in detail. With no Requirements, hide the blank detail
  panel. Narrow screens stack the same content without changing commands. Opaque Requirement, Task,
  Artifact and commit identifiers must not contribute a minimum content width: owning grid items use
  `min-width: 0`, while identifier text uses `overflow-wrap: anywhere`, so no child can cross from the
  master column into detail.
- Knowledge uses ownership navigation beside one content workspace. The existing asset inventory is
  the primary page content; scope-aware import buttons open focused modals for knowledge and Specs.
  Only existing document bodies and other secondary evidence may remain collapsed. Settings similarly
  uses local Basic/MySQL/Model navigation over one shared draft and one atomic save action. Status is
  read-only and leads with a readiness conclusion before individual runtime facts.
- Model Routing uses one shared compact disclosure/listbox control for route type, reasoning effort
  and each Agent's primary route. The control must keep focus visibility, disabled state, exact
  selected value and button keyboard activation while avoiding the unstyleable operating-system
  native option menu.
- Project creation is rendered in `需求与交付`, next to Project selection and Requirement work. The
  Settings page contains only process/runtime configuration and never presents Project creation as a
  configuration field.
- A config save uses same-directory temporary file, fsync and atomic replace. It validates the selected
  Team/name before publication. Any changed saved config or write-only runtime variable is marked
  `restart_required`; the already constructed Host is not mutated or hot-switched. Knowledge upload
  and sidecar selection, Spec activation and Learning decisions are not config saves and do not
  require restart.
- Every submitted Settings save has an explicit modal result. A successful PUT opens a success dialog
  that states whether Web Console restart is required. A failed PUT opens an `alertdialog` containing
  the bounded server `error.message` (or the generic client fallback), re-enables save and preserves
  the current draft so the operator can close the result and correct it. Inline progress text is not
  the terminal save result and must not be the only feedback.
- When an explicit save selects a new `platform_root` without that Team, initialize the selected
  immutable Team identity there. Do not migrate Team knowledge, Projects, Requirements or execution
  facts; knowledge selection must be empty until documents exist under the new root.
- Administration endpoints are optional at the transport seam for read-only/contract fixtures, but
  `ase-console` production composition must provide them. Existing Delivery commands remain bound to
  the runtime-active Team until restart.
- If the config file does not exist, `ase-console` uses visible `ProductionConfig.default()` values
  without writing the config or workspace. MySQL absence leaves delivery in `SETUP_REQUIRED`;
  Settings, Status and the safe Team shell remain available. An explicit valid Settings save is the
  first writer that may initialize the Team. An existing invalid config never falls back to defaults.
- `GET /api/v1/console` exposes secret-free `delivery_ready`; UI command controls require exact Team
  identity and `delivery_ready=true`. Setup mode keeps navigation available but must not invite a
  Requirement operation that can only fail.

### 4. Validation & Error Matrix

| Case | Required result |
|---|---|
| Duplicate exact Project name or ID/name | Idempotent reopen; no manifest rewrite |
| Existing Project ID with another name | 409 safe rejection |
| Invalid/path-like Project ID | 422/404 before filesystem access |
| Unsupported/dangerous filename or corrupt document | 422 generic safe error; no partial directory |
| Upload over 10 MB or normalized body over 256 KB | 413/422; no published record |
| Same document bytes uploaded twice | Return the original document identity |
| Browser batch contains a current filename | show exact replacement risk and issue no write before confirmation |
| Browser batch contains duplicate filenames or an ambiguous current filename | reject before the first write |
| Replace selected document | publish new document, transfer selection, retire old ID and return new view |
| Read active document content for editing | return verified normalized Markdown plus scope/name/identity only |
| Read retired, missing or tampered content | 404 safe error; no source bytes or unchecked text |
| Delete document | require confirmation in UI; remove it from selection and current inventory; retain files |
| Manifest/source/normalized digest or path drift | Entire knowledge listing fails closed |
| Unknown document ID, copied cross-scope record or invalid selection digest | 409/503 safe rejection; prior selection remains |
| Team selection changed | next Project runtime re-resolves Team context; no process restart |
| Project A selection changed | only Project A runtime is replaced; Project B stays unchanged |
| Knowledge changed after an operation prepared its context | existing preparation guard stops on drift; never reinterpret approval |
| Spec JSON over 512 KB, invalid glob/role/stage or unknown ID | 413/422/409; no draft/activation publication |
| Spec verification is empty | accept and preserve `verification=""`; mandatory platform QA/Review gates remain unchanged |
| Spec roles or stages have no selection | browser blocks before POST; direct API returns 422 |
| New Spec version created | inactive until explicit activation; older versions remain immutable |
| Update existing Spec | reuse hidden stable key, create next inactive version; never overwrite or auto-activate |
| Delete logical Spec | remove active version, retire the key and hide all versions; retain immutable records |
| Retirement digest/owner/reference drift | 409/503 safe failure; no destructive cleanup |
| Browser selects 1–20 valid background documents | issue one bounded POST per document, then refresh the inventory once |
| Browser selects over 20 background documents | reject before the first POST |
| One document in a batch fails | continue independent documents; report success count, failure count and first safe error |
| Browser selects 1–20 valid Spec documents | issue one bounded POST per file; create independent inactive Specs |
| Spec batch derives a current stable key | require explicit new-version confirmation; never auto-activate |
| Active Team/Project Spec changes | next relevant Project runtime rebuilds without restart; old preparation stops on drift |
| Learning decision uses stale proposal SHA or differs from existing authorization/decision | 409; first authorization/decision/publication remains |
| Settings select another Team/name or invalid knowledge | 409; config file unchanged |
| New platform root, current Team identity, empty knowledge selection | initialize that Team under the new root; save with restart required |
| New platform root with old-root knowledge paths | 409; never copy or reinterpret the old files |
| Plaintext DSN/API key in config payload | Pydantic/JSON Schema rejects unknown secret field |
| Duplicate `(provider, model, reasoning_effort)` route, including whitespace-only provider/model differences | browser shows both route positions and sends no PUT; direct API remains rejected |
| Same provider/model with distinct reasoning efforts | both routes remain selectable and each Agent policy stores the exact effort |
| Legacy Agent route omits effort while provider/model has multiple enabled efforts | reject as ambiguous; do not guess a route |
| Status reads an explicit per-Agent policy | render the seven roles in organization order with exact route order, effort and readiness |
| Status reads a legacy config without per-Agent policies | show every role as `global_default` with the same enabled global route order |
| Runtime variable name not referenced by submitted config | 409; neither config nor runtime.env changes |
| Invalid DSN or control-bearing secret input | 409/422; no value persisted or reflected |
| MySQL missing/unavailable on first run | Console starts setup surface; Status says NOT_CONFIGURED/UNAVAILABLE; delivery returns 503 SETUP_REQUIRED |
| Existing config is invalid | Startup fails safely; do not replace it with built-in defaults |
| Settings/runtime variable changed while Host is running | Persist plus `restart_required=true`; no hot mutation |
| Settings PUT succeeds | show a success dialog and the exact restart requirement returned by `SettingsSnapshot` |
| Settings browser validation or PUT fails safely | show its exact safe message in an `alertdialog`; keep the draft and allow retry |

### 5. Good / Base / Bad Cases

- Good: start with no config/MySQL, view defaults, enter and test a full DSN, save `runtime.env`, restart,
  create a Project, batch-upload Team DOCX/Markdown and Project Spec documents, explicitly enable them
  without restart, then prepare a new Requirement whose context digest binds both scopes.
- Base: a Team with no documents is valid and displayed neutrally; a Spec with empty verification
  guidance remains enforceable through its body and the normal QA/Review gates.
- Base: an invalid Settings submission keeps the edited values in place after its error dialog is
  dismissed, so the operator can correct only the rejected field and retry.
- Bad: let the browser submit `/etc/passwd`, recursively scan `knowledge/`, keep only an AI summary,
  return a DSN from the API, accept arbitrary environment names, or change the active Team inside an
  already-running Delivery Host.

### 6. Tests Required

- `tests/knowledge/test_documents.py` and `test_selection.py`: all four formats, Team/Project owner
  binding, exact replay, atomic selection, compatibility fallback, tamper and cross-Project rejection.
- `tests/config/test_runtime_environment.py`: canonical quote round-trip, `0600`, atomic replacement,
  duplicate/name/control/size/symlink rejection.
- `tests/web_console/test_administration.py`: singleton Team, Project catalog/create, config write/read,
  selected knowledge replacement/retirement, Spec retirement, write-only runtime values, safe MySQL
  probe, Status and restart semantics.
- `tests/web_console/test_transport.py`: admin verbs, content types/body limits, typed errors and no
  content/secret reflection, native chooser endpoint and screenshot upload, plus verified
  normalized-content reads; missing config/MySQL must still expose Settings/Status while delivery is
  `SETUP_REQUIRED`.
- `tests/web_console/test_directories.py`: canonical/unique directory output and relative, missing,
  symlink rejection.
- `tests/manager/test_requirement_attachments.py`: content addressing, tamper detection, exact
  dialogue binding and Product image-path delivery.
- `tests/specs/`: Spec/Learning stores and publication contracts; Web administration/transport tests
  cover both scopes, activation and Learning collection/decision endpoints.
- `tests/team_view/ui.test.cjs`: Project creation, scoped Knowledge navigation/live selection,
  selected-Agent queue grouping, searchable Project picker, modal Project/Requirement creation,
  master/detail Requirements, sectioned Settings, write-only DSN/key fields,
  same-name replacement confirmation, modal content editing resilient to auto-refresh, inventory-first
  Knowledge pages, modal bounded Background/Spec multi-file selection, role/stage multi-selects,
  optional verification, separate Status tab with seven per-Agent policies and route catalog, shared
  Model Routing selector styling, Settings success/error result dialogs with draft-preserving retry,
  safe text rendering and long opaque identifier containment.
- `tests/contracts/test_json_schema_contracts.py`: production config/port, knowledge manifests,
  selection/retirement and Spec document/activation/retirement Python-to-Schema parity.

### 7. Wrong vs Correct

```python
# Wrong: turns a local filename into ambient server filesystem authority.
content = Path(request.json()["path"]).read_bytes()

# Correct: the bounded browser body is the only source and becomes an immutable record.
manifest = knowledge_store.import_document(filename=query.filename, content=await request.body())
```

```javascript
// Wrong: trust a browser text field as host filesystem authority.
intent.repository_roots = textarea.value.split("\n")

// Correct: the browser can submit only canonical paths returned by the fixed native picker.
intent.repository_roots = selectedDirectories
```

```python
# Wrong: return secrets so the browser can pre-fill its controls.
return {"config": config, "mysql_dsn": stored_dsn}

# Correct: accept an allowlisted write-only update and return status only.
runtime_store.save({config.database.dsn_env: submitted_dsn})
return SettingsSnapshot(config=config, secret_status=(SecretStatus(...),))
```

```python
# Wrong: treat knowledge enablement as process configuration and require a restart.
config.team_knowledge_paths = selected_paths

# Correct: publish a scope-owned selection; the next runtime access re-resolves it.
TeamKnowledgeSelectionStore(team).save(selected_paths)
```

```python
# Wrong: uploading a Spec silently makes it govern live work.
administration.create_project_spec(project_id, command)

# Correct: publication and activation are separate human-visible operations.
view = administration.create_project_spec(project_id, command)
administration.update_project_spec_activation(
    project_id, UpdateSpecActivationRequest(spec_ids=(view.document.spec_id,))
)
```

```javascript
// Wrong: repeat a large import form beneath every inventory or treat a batch as one oversized upload
// with ambiguous partial-failure semantics.
uploadAll(files)

// Correct: open one focused modal from the current scope and reuse the bounded one-document API.
openKnowledgeImportModal(currentScope)
for (const file of files.slice(0, 20)) await importDocument(file)
```

```javascript
// Wrong: a card click mutates an upload selector that the 5-second render immediately resets.
target.value = documentId

// Correct: load verified normalized text into durable modal state and publish an immutable replacement.
editingKnowledgeDocument = await readDocumentContent(documentId)
await replaceDocument(documentId, editingKnowledgeDocument.content_markdown)
```

```python
# Wrong: erase a source/version that a completed delivery may still reference.
shutil.rmtree(document_directory)

# Correct: remove current selection/activation and retire the stable identity; keep immutable history.
selection_store.save(paths_without_old_document)
knowledge_store.retire(old_document_id)
```

## Scenario: local Web Console process lifecycle

### 1. Scope / Trigger

Applies to `scripts/ase-console-service.sh`. It is the supported macOS/Linux foreground-independent
launcher for one trusted local Host; it is not a system boot service or multi-instance supervisor.

### 2. Signatures

```text
./scripts/ase-console-service.sh start|stop|restart|status|logs
ASE_SERVICE_STATE_DIR=/absolute/path   # optional
XDG_STATE_HOME=/absolute/path          # optional fallback
```

The executable is the repository-local `.venv/bin/ase-console`. PID and log default to
`${XDG_STATE_HOME:-$HOME/.local/state}/ai-software-engineer/`.

```text
ase-console.pid line 1 = numeric child PID
ase-console.pid line 2 = absolute repository-local executable that created the record
```

### 3. Contracts

- `start` requires an executable repository-local `ase-console`, resolves `ASE_CONFIG` or its XDG
  default, then loads sibling `runtime.env` with export semantics before launching. Existing process
  environment remains available and the managed file wins for its declared names. It redirects stdio,
  records the child PID and verifies that the same executable remains alive after startup.
- `stop` sends TERM only when the PID is numeric, alive and its process command identifies this
  repository's executable, or when line 2 identifies a live `*/.venv/bin/ase-console` previously
  written by this launcher in another checkout sharing the same state directory. The latter is a
  managed checkout handoff: `restart` stops the verified old executable and starts the current
  repository executable. A numeric PID with no live process is a safe stale record: `stop` removes
  only that PID file and succeeds, allowing `restart` to continue. It waits up to 20 seconds and never
  escalates to KILL automatically.
- `start` writes both PID and executable identity, treats a verified managed process from another
  checkout as already running, and never overwrites a live unverified PID record with a second
  process. `status` reports the recorded executable when another checkout owns the managed process.
- `restart` is exact `stop` followed by `start`; `status` is read-only apart from preparing its safe
  state directory; `logs` tails the last 100 lines and follows the file.
- The state directory must be absolute, not `/`, and not a symlink. PID-file symlinks are rejected.
  A stale or foreign PID never receives a signal.
- This script does not author or mutate secrets, install dependencies, initialize MySQL, register
  launchd/systemd, or claim that a successful process start means the production Host is healthy.
  `runtime.env` is authored only by the typed administration store.

### 4. Validation & Error Matrix

| Case | Required result |
|---|---|
| Missing verb or unknown verb | print usage to stderr; exit 2 |
| Missing `.venv/bin/ase-console` | explain `uv sync`; exit 2; no PID record |
| Missing config/runtime.env | start setup surface using visible defaults; do not synthesize either file |
| runtime.env symlink/non-file | reject before starting child |
| Existing matching live PID | idempotent start |
| Missing PID on stop | report not running; success |
| Non-numeric PID | send no signal; report stopped without trusting the record |
| Numeric PID with no live process | remove only the stale PID file; report stopped; allow restart |
| Live PID and recorded executable identify another checkout's managed Console | `restart` stops that exact process, then starts the current checkout |
| Live PID has no valid recorded executable or command does not match it | send no signal; retain PID file; fail safely |
| Child exits during startup | remove its PID record, show bounded log tail, exit 1 |
| TERM does not stop in 20 seconds | leave process and PID intact; exit 1 |
| Relative/root/symlink state directory | reject before creating or deleting files |

### 5. Good / Base / Bad Cases

- Good: start once with defaults, save DSN/provider keys in Settings, restart so the launcher exports
  the canonical runtime file, then use `status`/`logs` for operations.
- Base: stopping an already stopped service is idempotent; a dead numeric PID is cleaned without
  signaling any process, then `restart` starts a fresh child. A legacy one-line PID remains valid for
  the checkout whose exact executable is running, but cannot authorize a cross-checkout handoff.
- Bad: use a PID file without process identity validation, hard-code DSN in the script, source an
  arbitrary/symlink runtime file, treat every `ase-console` command as managed, or issue `kill -9`
  after a fixed delay.

### 6. Tests Required

- `sh -n scripts/ase-console-service.sh`.
- No-argument invocation exits 2.
- Focused process tests use an isolated absolute `ASE_SERVICE_STATE_DIR` and a fake repository-local
  executable. They prove dead-PID restart recovery, safe handoff between two checkout executables
  sharing one state directory, and that a live unrelated process remains alive with its PID record
  intact.
- The launcher test must prove that sibling `runtime.env` reaches the child environment without
  printing its value.

### 7. Wrong vs Correct

```sh
# Wrong: trust a stale PID and force kill an arbitrary process.
kill -9 "$(cat "$PID_FILE")"

# Correct: remove a dead record without signaling; require recorded exact identity before TERM.
process_exists "$current_pid" || { rm -f "$PID_FILE"; exit 0; }
(is_our_process "$current_pid" || is_managed_process "$current_pid") || exit 1
kill -TERM "$current_pid"
```

### 8. Bug analysis: checkout-local identity behind a shared PID file

1. **Root cause category**: implicit assumption plus test-coverage gap. The state directory was
   intentionally Host-global, while process ownership was inferred only from the checkout executing
   the current command. A second checkout therefore made a healthy managed Console look foreign.
2. **Why the previous guard was insufficient**: validating only the current repository executable
   prevented signaling arbitrary PIDs, but discarded the executable identity known at launch time.
   Removing the PID manually would hide the symptom and could orphan the still-running service.
3. **Prevention mechanisms**:

   | Priority | Mechanism | Concrete action | Status |
   |---|---|---|---|
   | P0 | Runtime identity | Persist PID plus canonical repository executable and verify both against the live command | DONE |
   | P0 | Regression | Start from checkout A, restart from checkout B through one state directory, and assert B owns the successor | DONE |
   | P0 | Safety regression | Keep a live unrelated process and prove restart neither signals it nor overwrites its PID record | DONE |
   | P1 | Operations | Keep `ASE_CONFIG` consistent when intentionally handing the singleton Host between checkouts | DOCUMENTED |

4. **Systematic expansion**: every host-global lifecycle record that controls checkout-local resources
   needs both stable singleton identity and the concrete resource identity captured at creation. A PID
   alone proves neither ownership nor which code/config instance the browser is observing.
5. **Knowledge capture**: this executable contract, the production guide, README and isolated launcher
   regression are the maintained prevention boundary; no parallel template tree exists in this repo.

## Scenario: Product Agent 多轮需求讨论

### 1. Scope / Trigger

修改 Requirement 的 Product 对话投影、聊天界面、回复/批准控件或
`team-snapshot.schema.json` 时适用。写权威仍是 `JointDeliveryService`；浏览器和 Team View 不创建第二套
对话状态。

### 2. Signatures

```python
class DialogueAttachmentView(DomainModel):
    id: str
    name: str
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    source_bytes: int
    sha256: str


class DialogueTurnView(DomainModel):
    sequence: int
    speaker: Literal["user", "product"]
    text: str
    attachments: tuple[DialogueAttachmentView, ...]


class RequestView(DomainModel):
    dialogue: tuple[DialogueTurnView, ...]
```

写入仍只使用既有命令：

```text
PRODUCT_REPLY(project_id, delivery_id, expected_checkpoint_sha256, message, screenshot_ids)
PRODUCT_APPROVAL(project_id, delivery_id, expected_checkpoint_sha256)
```

### 3. Contracts

- `JointCheckpoint.dialogue` 是唯一 Product 对话事实；Reader 按 tuple 顺序派生从 1 开始的 sequence，
  不从 Operation、ProductSpec 或 UI 内存重建消息。
- `READY_FOR_DISCUSSION` 接收首条需求；`WAITING_PRODUCT_REPLY` 接收对 Product Agent 的回答；
  `WAITING_PRODUCT_APPROVAL` 同时允许批准 exact ProductSpec 或继续回复并使未批准候选失效。
- Product Agent 返回 `clarify` 时追加 `speaker=product` 的问题并停在
  `WAITING_PRODUCT_REPLY`；返回 `ready` 时发布 ProductSpec 并停在 `WAITING_PRODUCT_APPROVAL`。
- 对话 UI 按顺序显示 `你` 与 `Product Agent`。没有消息时不显示空聊天容器；换页、刷新和服务重启
  都从 checkpoint 恢复相同消息。
- Product 尚未批准时，历史、批准提示和输入 composer 属于同一个“需求讨论” detail section，内部
  不再使用 `detail-section` 分割线。composer 在 READY/WAITING reply/approval 可输入；
  `PRODUCT_DISCOVERY` 或同 Requirement Operation 运行时仍保持可见但禁用，显示
  “Product Agent 正在回复”。中断且没有 active Operation 时显示“继续需求讨论”，不得使用
  “继续交付”。但 `SOURCE_REVISION_DRIFT`（含 legacy summary）不是可恢复中断：隐藏 composer 和
  Product 批准入口，显示预填的“基于当前代码新建需求”动作。进入 Designer 以后保留历史只读，但
  不允许修改已批准 ProductSpec。
- 历史截图只显示安全元数据，不从浏览器拼接 sidecar 路径；所有文本继续用 `textContent`。
- Product Agent 不能批准自己生成的 ProductSpec；只有用户明确点击批准才进入 Designer。

### 4. Validation & Error Matrix

| Case | Required result |
|---|---|
| Product 返回 clarification | 持久化 Product turn，显示问题和回复输入框，不显示为已批准 |
| 用户连续回复多轮 | 每次提交 exact current checkpoint；刷新后顺序、角色和附件元数据不变 |
| ProductSpec 已生成但用户继续讨论 | 清除未批准候选，追加用户 turn，重新运行 Product Agent |
| ProductSpec 已生成且用户批准 | 只批准 exact current checkpoint，进入 Designer |
| `PRODUCT_DISCOVERY` 正在运行 | 历史和禁用 composer 保持在同一 section；显示 Product Agent 处理状态 |
| `PRODUCT_DISCOVERY` 没有 active Operation | 显示“继续需求讨论”；不得显示通用“继续交付”或第二条内部分割线 |
| 任一阶段最新 Operation 是 retained baseline drift | 显示恢复说明和预填新建入口；不提交旧 Delivery 的继续/回复/批准动作 |
| unknown speaker / malformed attachment metadata | read model validation fails closed；不猜角色 |
| stale checkpoint / duplicate active Operation | 既有 409/FAILED 规则生效；不追加重复 turn |
| 对话含 secret 或 HTML | Reader 清洗，浏览器 text-only 渲染 |

### 5. Good / Base / Bad Cases

- Good：用户描述需求，Product Agent 连续追问两轮，用户逐次回答；第三次生成 ProductSpec，用户阅读后
  批准，刷新前后完整会话一致。
- Base：简单需求首轮直接生成 ProductSpec；仍显示用户原始消息，并允许批准前继续讨论。
- Bad：只把 Product 问题放在一次 Operation 的 result 中，Operation 结束或刷新后问题消失；或 UI
  根据 `WAITING_PRODUCT_REPLY` 自己虚构一条 Agent 消息；或把聊天历史和 composer 拆成两个带
  divider 的 detail section，再把 Product 恢复动作标成“继续交付”。

### 6. Tests Required

- `tests/team_view/test_live.py`：从真实 `JointCheckpoint.dialogue` 投影双方顺序、清洗文本和截图元数据，
  并验证 `team-snapshot.schema.json` 与 Pydantic 一致。
- `tests/team_view/ui.test.cjs`：双方气泡顺序、空对话隐藏、截图元数据、澄清阶段回复控件，以及
  ProductSpec 阶段同时存在批准与继续讨论入口；`PRODUCT_DISCOVERY` 必须保留同 section 的禁用
  composer，并把普通中断恢复标为“继续需求讨论”；retained baseline drift 必须替换成恢复说明与可选的
  新建 Requirement 入口，主 checkout 正常前进不得触发该状态。
- `tests/manager/test_joint_contracts.py`：Requirement checkpoint Schema 限制 speaker union，并与模型一致。

### 7. Wrong vs Correct

```javascript
// Wrong: Operation 消失后 Product 问题也消失。
renderQuestion(lastOperation.result.next_action)

// Correct: 对话只来自当前 checkpoint 的不可变投影。
for (const turn of request.dialogue) renderDialogueTurn(turn)
```

```javascript
// Wrong: Product processing drops the composer and falls through to a delivery action section.
if (stage !== "WAITING_PRODUCT_REPLY") renderContinueDelivery()

// Correct: one Product discussion section owns history, state and composer until approval.
renderProductDiscussion({ dialogue, composerDisabled: stage === "PRODUCT_DISCOVERY" })
```

### 8. Bug analysis: source drift shown as a recoverable Product interruption

1. **Root cause (B/D/E)**: the UI inferred recovery solely from
   `request.stage === PRODUCT_DISCOVERY && no active Operation`. It ignored the latest terminal
   Operation cause, so a fail-closed Git lineage rejection looked identical to an interrupted model
   call. The broad backend `ValueError → COMMAND_REJECTED` mapping also erased the distinction.
2. **Why the earlier recovery UI was insufficient**: keeping the composer visible and adding
   “继续需求讨论” solved ordinary dispatcher interruption, but there was no test combining a
   durable PRODUCT_DISCOVERY checkpoint with a failed source-drift Operation. Retrying therefore
   reproduced the same pre-model rejection and appeared permanently stuck.
3. **Prevention mechanisms**:

   | Priority | Mechanism | Concrete action | Status |
   |---|---|---|---|
   | P0 | Architecture | Raise typed `RequirementSourceRevisionDrift` and preserve it as `SOURCE_REVISION_DRIFT` across the Manager boundary | DONE |
   | P0 | UI state matrix | Derive actions from checkpoint stage plus active/terminal Operation cause; source drift replaces recovery with prefilled CREATE | DONE |
   | P0 | Backward compatibility | Recognize only the bounded legacy source-drift summaries already persisted under `COMMAND_REJECTED` | DONE |
   | P0 | Regression | Test dedicated mapping, legacy rendering, no stale recovery action, prefilled scope and pre-approval retirement | DONE |
   | P1 | Audit | Review other broad `COMMAND_REJECTED` causes before adding any new terminal-specific UI; introduce typed codes one by one | TODO |

4. **Systematic expansion**: not every failed Operation is resumable, and not every unchanged
   checkpoint means a process is still active. Future failure-specific controls must use a typed,
   bounded error code; parsing text is allowed only for migration of known immutable legacy records.
5. **Knowledge capture**: this section, the recovery/error matrix above and
   `multi-directory-delivery.md` form the executable contract. This repository has no
   `src/templates/markdown/spec/` mirror to synchronize.
