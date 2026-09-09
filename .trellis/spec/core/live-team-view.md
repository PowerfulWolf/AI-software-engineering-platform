# T036 Live team read side

## Scope / Trigger

Changes to team_view, read-only store opening, ase team serve, MySQL aggregation or browser payloads.
Existing DashboardRenderer stays pure; socket lives in separate server composition.

## Signatures

`ProductionTeamReader(config: ProductionConfig, environment: Mapping[str,str]).snapshot() -> TeamSnapshot`
`create_team_server(reader: TeamReader, *, port: int = 8765) -> ThreadingHTTPServer`
`ase team serve --port 8765`; `GET /api/v1/team` returns `team-snapshot.schema.json`.
Existing ASE_CONFIG/database.dsn_env applies. No model credentials needed by reads.

## Contracts

- Company initialize(read_only=True) verifies existing state without creating a missing company.
- Journal/checkpoint/artifact/evaluation/route-attempt read_only opens never mkdir; writes reject.
- Never construct OrganizationTeamHost/MySqlTaskRepository/dispatch authority to read: constructors
  initialize schema/workspaces. Use REPEATABLE READ + WITH CONSISTENT SNAPSHOT, READ ONLY;
  rollback/close every connection on success and failure.
- Discover only configured company; validate manifests, chain, intake, dispatch digest and normalized
  immutable Task identity. Reuse RunProjectionBuilder event validation.
- Match in-flight children with DerivedStageInputs + existing delivery identity, never titles/prose.
- Capture file prefixes before SQL snapshot; event-linked artifacts support gate evidence. Completed
  model-route records can precede state transitions but cannot become verdict authority.
- Current role is Task stage + committed assignment; terminal tasks are history, not active work.
- `AgentRole.ORCHESTRATOR` 是 legacy planning/control Run，可保留在 Task/Run timeline，但不是
  `OrganizationRole`。`RunProjectionBuilder` 只能把 Coder/QA/Reviewer delivery roles 映射成组织角色；
  没有 AgentProfile 且只含 orchestrator Run 的 synthetic identity 不得生成 Agent card。
- execution_liveness stays UNKNOWN without heartbeat. Enabled/capacity configuration and company counts
  are not online, utilization or organization-global workload.
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
| Task/dispatch/event binding drift | reject snapshot, never hide corrupted records |
| Terminal Task | history, no current-stage assignment |
| Orchestrator plan artifact/run | Run/timeline 保留；不创建虚假组织成员，不抛角色转换异常 |
| Foreign Host/Origin | 403 before reader invocation |
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
expanded documents. No real models. Full regression, Ruff, strict Mypy and offline build required.
`tests/projection/test_projector.py` 必须覆盖 orchestrator Run 可见但 `snapshot.agents` 不含虚假成员。

## Wrong vs Correct

Wrong: `OrganizationTeamHost.from_environment().project_entry().status(id)` on every refresh.
Correct: `ProductionTeamReader(config, environment).snapshot()` with read-only opens and a read-only
MySQL transaction. Refresh observes, never advances delivery.

Wrong: `OrganizationRole(run.role.value)` 对所有 delivery/control Run 强转。
Correct: 仅显式映射 Coder/QA/Reviewer；Project Manager/Product/Designer/Planner 由 AgentProfile 提供，
orchestrator 只作为控制 Run 留在时间线。

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
_read_task_details(native: _Native, cursor: DictCursor, base: TaskView) -> TaskView
```

`TaskView` exposes `work_kind = delivery | candidate_verification | remediation`, optional
`source_delivery_id`, `source_task_id`, and `plan_sha256`. The JSON contract is
`schemas/team-snapshot.schema.json`.

### 3. Contracts

- Read `dispatch_commits`, `verification_reservations`, Tasks, events and route attempts inside the
  same repeatable-read transaction.
- An incomplete verification reservation is a first-class QA/Reviewer work item. Current role is QA
  until its invocation/report exists, then Reviewer; a sealed completion makes it terminal.
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
| Sealed QA FAIL | terminal verification with blocker; Reviewer not active |
| Continuation dispatch | remediation work with fresh Task plus source lineage |
| Reservation references missing/wrong source Task/project | reject snapshot; do not hide row |
| Missing optional file record before reservation publication | reservation remains SQL-derived; no invented verdict |

### 5. Good / Base / Bad Cases

- Good: during candidate verification the long-lived QA member shows the exact work item, route and
  repository directory; after QA FAIL the successor Coder remediation appears.
- Base: a completed reservation remains auditable but no longer counts as active capacity.
- Bad: query only `dispatch_commits`, or infer verification liveness from the BLOCKED source Task.

### 6. Tests Required

`tests/team_view/test_live.py` must insert a real MySQL verification reservation and assert its QA
assignment, source identity, work kind and exact repository scope. The real resume suite must also
interrupt an admitted QA verification and assert the card contains that exact QA Run. Existing schema
equality, no-write, company isolation, HTTP and browser tests remain required.

### 7. Wrong vs Correct

```python
# Wrong: terminal source Tasks suppress independent verification work.
active = source_task.status not in TERMINAL

# Correct: the reservation/completion lifecycle owns verification liveness.
active = reservation.completion_sha256 is None
```
