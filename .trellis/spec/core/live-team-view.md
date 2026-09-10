# T036 Live team read side

## Scope / Trigger

Changes to team_view, read-only store opening, ase team serve, MySQL aggregation or browser payloads.
Existing DashboardRenderer stays pure; socket lives in separate server composition.

## Signatures

`ProductionTeamReader(config: ProductionConfig, environment: Mapping[str,str]).snapshot(company_id: str | None = None) -> TeamSnapshot`
`create_team_server(reader: TeamReader, *, port: int = 8765) -> ThreadingHTTPServer`
`ase team serve --port 8765`; `GET /api/v1/team` reads the configured company and
`GET /api/v1/team/<company_id>` reads one prepared company. Both return
`team-snapshot.schema.json`, including the safe company-tab catalog.
Existing ASE_CONFIG/database.dsn_env applies. No model credentials needed by reads.

## Contracts

- Company initialize(read_only=True) verifies existing state without creating a missing company.
- Journal/checkpoint/artifact/evaluation/route-attempt read_only opens never mkdir; writes reject.
- Never construct OrganizationTeamHost/MySqlTaskRepository/dispatch authority to read: constructors
  initialize schema/workspaces. Use REPEATABLE READ + WITH CONSISTENT SNAPSHOT, READ ONLY;
  rollback/close every connection on success and failure.
- Discover prepared company workspaces only from direct `platform_root/companies/company_*`
  children. Validate each included manifest and binding; a directory without `company.json` is not a
  company. The configured company must exist. A requested company ID must satisfy `CompanyId` and
  match the discovered catalog before any company facts are read.
- Read one selected company per snapshot; never aggregate its requests/tasks into another company.
  Validate chain, intake, dispatch digest and normalized immutable Task identity. Reuse
  RunProjectionBuilder event validation.
- A joint parent's child checkpoint is a committed observation, not a mutable latest pointer. When
  the native child has advanced, accept the parent reference only when it is the exact record at its
  sequence in the same fully validated native hash chain. Missing, replaced, future or cross-delivery
  references reject the whole snapshot; the Task view uses the latest native checkpoint.
- Match in-flight children with DerivedStageInputs + existing delivery identity, never titles/prose.
- Capture file prefixes before SQL snapshot; event-linked artifacts support gate evidence. Completed
  model-route records can precede state transitions but cannot become verdict authority.
- Current role is Task stage + committed assignment; terminal tasks are history, not active work.
- Agent cards must render assignment-stage state, not copy the Task's global delivery status onto every
  planned assignment. Only `AssignmentView.current_stage=true` may display the Task's active-stage label.
  Earlier serial roles display `本轮已完成`, later roles display `等待<角色>阶段`, and a Task with no
  current-stage assignment displays `已分配 · 等待调度`. Task detail keeps the complete assignment plan.
- `AgentRole.ORCHESTRATOR` 是 legacy planning/control Run，可保留在 Task/Run timeline，但不是
  `OrganizationRole`。`RunProjectionBuilder` 只能把 Coder/QA/Reviewer delivery roles 映射成组织角色；
  没有 AgentProfile 且只含 orchestrator Run 的 synthetic identity 不得生成 Agent card。
- execution_liveness stays UNKNOWN without heartbeat. Enabled/capacity configuration and company counts
  are not online, utilization or organization-global workload.
- Member display state is assignment-derived: current-stage assignment = `执行中`; non-current active
  assignment = `等待当前阶段`; no non-terminal assignment in the selected company = `空闲中`.
  `空闲中` is a company workload statement, never a process-online statement.
- The task page renders every selected-company Task in exactly one UI group: `DONE` is `已完成`;
  blocker/`WAITING_*`/`BLOCKED`/`FAILED` is `阻塞中`; other non-terminal work is `执行中`;
  any remaining audit-terminal status is `已完成`.
- Planned models come from dispatch; actual completed calls from validated ModelRouteAttempt.
- Delivery writer and reader must use `agents.fallback.model_route_root(project_workspace_root)`:
  `<project-sidecar>/runs/model-routes/<run-id>/<route-index:02d>.json`. Do not reconstruct ledger
  paths from prose. A scripted successful Coder/QA/Reviewer delivery must expose all three completed
  model calls; asserting only an empty-compatible list misses broken read/write wiring.
- HTTP only 127.0.0.1, exact Host and optional same-origin Origin, no CORS/downloads/write APIs or models.
- Redact displayed text. Render with textContent; URI/digests are text, not arbitrary navigation URLs.
- Failed polls preserve explicitly stale data; unchanged polls preserve DOM, changed ones preserve open
  reports/history. UI never infers percentage, success or process liveness.

## Validation & Error Matrix

| Case | Result |
|---|---|
| Missing config / occupied port | safe CLI exit 2 |
| Missing company / bad digest / path / unavailable DB | TeamReadError / HTTP 503, no init |
| Prepared empty company | honest empty data; no DB/model needed without native deliveries |
| Running child before parent publication | visible via deterministic identity |
| Parent references an exact historical child; native child advanced | latest child remains visible |
| Parent child record is absent/replaced or ahead of native history | reject snapshot |
| Task/dispatch/event binding drift | reject snapshot, never hide corrupted records |
| Terminal Task | history, no current-stage assignment |
| IMPLEMENTING with Coder current, QA/Reviewer planned | Coder `实现中`; QA `等待测试阶段`; Reviewer `等待评审阶段` |
| QA with QA current | Coder `本轮已完成`; QA `测试中`; Reviewer `等待评审阶段` |
| Non-terminal Task with no current assignment | every planned role `已分配 · 等待调度`; none shown as executing |
| Orchestrator plan artifact/run | Run/timeline 保留；不创建虚假组织成员，不抛角色转换异常 |
| Foreign Host/Origin | 403 before reader invocation |
| Valid prepared company tab | one isolated snapshot for that company |
| Invalid/path-like/unknown company ID | safe 404 or unavailable response; no path traversal |
| Enabled member without selected-company assignment | `空闲中`; no online claim |
| Active, blocked and done Tasks | exactly one matching task section each |
| Non-GET / unknown path or query | 405 / 404 |
| Malicious HTML / secret in title | redacted text, no executable markup |
| Failed poll then recovery | stale banner then clear banner after valid read |

## Good / Base / Bad

Good: current QA visible with exact modules before joint child writeback. Base: empty company has no
fake members. Bad: initialize Host on GET or label old IMPLEMENTING checkpoint as Agent online.

## Tests Required

tests/team_view: real MySQL/Git scripted providers, in-flight Coder/QA/Review, multi-request history,
no file writes, company isolation, tamper rejection; actual HTTP GET/assets/Host/Origin/write/errors;
exact Schema model equality; Node DOM harness for multi-assignment/views/HTML safety/refresh/stale/
expanded documents, company tabs, member workload state and three task groups. No real models. Full
regression, Ruff, strict Mypy and offline build required.
The DOM harness must include one serial Task assigned to Coder/QA/Reviewer and assert that exactly the
current assignment receives the active Task-stage label before and after a Coder-to-QA transition.
`tests/projection/test_projector.py` 必须覆盖 orchestrator Run 可见但 `snapshot.agents` 不含虚假成员。

## Wrong vs Correct

Wrong: `OrganizationTeamHost.from_environment().project_entry().status(id)` on every refresh.
Correct: `ProductionTeamReader(config, environment).snapshot()` with read-only opens and a read-only
MySQL transaction. Refresh observes, never advances delivery.

Wrong: `OrganizationRole(run.role.value)` 对所有 delivery/control Run 强转。
Correct: 仅显式映射 Coder/QA/Reviewer；Project Manager/Product/Designer/Planner 由 AgentProfile 提供，
orchestrator 只作为控制 Run 留在时间线。

Wrong: every Agent card renders `badge(task.status)`, so all three planned roles appear `实现中`.
Correct: render the badge from `assignment.current_stage` plus serial role order; preserve
`task.status` as the Task-level delivery state and never infer concurrent execution from a plan.

Wrong: label every enabled profile `已启用 · 运行状态未确认`, or call it online/idle without scope.
Correct: derive `执行中 / 等待当前阶段 / 空闲中` from selected-company assignments and separately
state that process liveness remains unknown.

Wrong: render company tabs while every tab still fetches the configured company's snapshot.
Correct: each tab calls `GET /api/v1/team/<company_id>` and the reader validates that company against
the prepared-company catalog before reading its isolated facts.

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
    company_id: str,
) -> tuple[TaskView, ...]
_native_task_sources(native: _Native) -> dict[str, _Native]
_read_task_details(native: _Native, cursor: DictCursor, base: TaskView) -> TaskView
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
- Agent cards count these active assignments exactly as ordinary delivery work. The projection remains
  read-only and never creates a Host, schema, workspace, or state transition.

### 4. Validation & Error Matrix

| Fact | Projection |
|---|---|
| Active reservation, no QA invocation | QA current; source directory visible |
| QA invocation/report, no completion | QA run visible; Reviewer current only after QA PASS |
| Older incomplete reservation plus newer committed reservation for the same source | older is terminal `VERIFICATION_SUPERSEDED`; newer owns liveness |
| Sealed QA FAIL | terminal verification with blocker; Reviewer not active |
| Continuation dispatch | remediation work with fresh Task plus source lineage |
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
schema equality, no-write, company isolation, HTTP and browser tests remain required.

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
```
