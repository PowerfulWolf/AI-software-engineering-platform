# T036 Live team read side

## Scope / Trigger

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
- Capture file prefixes before SQL snapshot; event-linked artifacts support gate evidence. Completed
  model-route records can precede state transitions but cannot become verdict authority.
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
- `RequestView.failed_stages` 是从当前 native child checkpoint 的 `failed_stage` 只读投影的失败阶段集合；
  不得从 blocker 文本猜测阶段，也不得使用已被 successor Task 取代的历史 child checkpoint。浏览器的
  交付流程在有失败阶段时必须把失败阶段之前的节点显示为已完成、失败节点显示为阻塞警告、后续节点
  保持待处理，从而在 `BLOCKED`/`FAILED` 且没有活动 Task 时仍能看出卡点。活动 successor Task 重新出现时，
  Reader 清除旧的 `failed_stages`，流程恢复显示当前 Task 阶段。
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
  children and execution plan, then excludes those native Tasks before standalone fallback and Agent
  queue projection. Audit sidecars remain on disk but cannot reappear as unrelated current work.
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

### Scope and signatures

`read_role_queue(cursor, *, task_id, repository_id, allocation_sha256, now) -> tuple[RoleQueueView, ...]`
reads inside the existing READ ONLY SQL snapshot. `TaskView.role_queue` defaults to `()` for legacy
Tasks. `RoleQueueView` carries work_item_id, role, attempt, status, agent_id, heartbeat_at,
lease_expires_at, lease_liveness and wait_reason; schema parity is required.

### Contract and validation matrix

| Facts | Projection |
|---|---|
| No admission table/record | legacy empty queue; do not initialize tables |
| Valid admission with exact dispatch digest | read ordered role queue items and their latest claim |
| RUNNING + ACTIVE lease with expiry in future | LEASE_VALID; may own current_stage if Task role also matches |
| Expired/released claim or READY/WAITING item | no current-stage assignment; no claim of execution |
| Queue CLOSED | 本次执行已结束, not Task DONE or role verdict |
| Queue WAITING_HUMAN/WAITING_DEPENDENCY | taskGroup is blocked; raw gap ID/hash is not shown as user guidance |
| Admission/Task/repository/assignment/lease binding drift or multiple open roles | reject read; never repair facts on GET |

Good: Task is at QA checkpoint but the expired QA lease is not shown as QA executing.
Base: legacy Task without admission remains readable. Bad: infer online execution from dispatch alone.
Wrong: label all CLOSED entries “交付完成”. Correct: render queue lifecycle separately from Task verdict.

`tests/team_view/test_live.py::test_real_inflight_joint_and_terminal_reads` checks actual RUNNING claims,
heartbeat and all-CLOSED terminal history with no writes. `ui.test.cjs` verifies localized status,
heartbeats and waiting task-group placement. Existing schema, read-only, stale-poll and isolation gates
still apply; existing production data needs no SQL rewrite.
