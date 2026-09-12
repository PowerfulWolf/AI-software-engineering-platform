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
create_console_app(
    console: ConsoleApplication,
    reader: TeamReader,
    *,
    team_id: str,
    port: int = 8765,
    administration: ConsoleAdministration | None = None,
    delivery_ready: bool = True,
) -> FastAPI
production_console_app(
    environment: Mapping[str, str] | None = None,
    *,
    port: int | None = None,
) -> FastAPI
```

`ConsoleIntent` 当前只允许：

- `CREATE_PROJECT(name, project_id?)`；
- `CREATE_REQUIREMENT(project_id, name, repository_roots)`；
- `PRODUCT_REPLY(project_id, delivery_id, expected_checkpoint_sha256, message)`；
- `PRODUCT_APPROVAL(project_id, delivery_id, expected_checkpoint_sha256)`；
- `CONTINUE_DELIVERY(project_id, delivery_id, expected_checkpoint_sha256, approved_plan_sha256?)`。

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
- UI 只能批准 Manager 返回并验证过的 exact recovery/verification plan SHA。SHA 可以隐藏在
  控件中，但批准前必须显示候选提交、Agent/模型或保留修改/目标基线等可理解事实。
- checkpoint 或 plan 已变化时必须拒绝；刷新最新投影后重新提交，不得自动替换用户批准对象。

### 3.4 Security and process boundary

- Uvicorn 只监听 `127.0.0.1`；transport 要求 exact `Host=127.0.0.1:<port>`，Origin 缺省或同源。
- POST 只接受 `application/json`，body 最大 64,000 bytes；输入错误返回稳定小型 error envelope，
  不回显完整 payload、traceback、secret 或未经边界验证的模型文本。
- Repository 源码目录必须是唯一、无控制字符、无 lexical `..` 的绝对路径；真正的 Git/规范约束仍由
  Manager prepare 校验。
- static assets 使用 `textContent` 渲染外部文本；CSP 禁止外部 script/style、frame 和 form action。
- MySQL DSN/API key 是 write-only 输入：不得出现在 API response、Operation、日志、普通配置 JSON、
  plist 或 systemd unit。当前可信本机 MVP 可写入配置文件同目录的 `runtime.env`，必须 canonical
  quote、原子替换、权限 `0600` 且只包含当前 ProductionConfig 引用的 allowlist 名称。未来
  Keychain/Secret Service adapter 替换本地 store 时不得改变该 write-only API 契约。

### 3.5 User-visible flow

- 日常用户可在网页完成：Project 创建/选择、带 1–N 个 Repository 目录的 Requirement 创建、Product 对话、ProductSpec 批准、统一继续、exact
  recovery/verification 计划批准、进度观察和 Candidate 领取。
- 一个 Task 的 Coder/QA/Reviewer 串行。UI 只把 `current_stage=true` 的 assignment 标成执行中；
  已完成/未来角色不得同时显示为运行。
- DONE 只展示已经由 durable facts 证明的 candidate commit、可唯一定位的 branch 和验证证据。
  v0.1 不自动 merge、push 或 deploy。
- `ase request`、`verify-*` 和底层 Runtime 保留作运维/诊断/break-glass，不是 README 的日常入口。

## 4. Validation & Error Matrix

| Case | Required result |
|---|---|
| Valid Project or new Requirement with one or many absolute roots | persist QUEUED, return 202, background Manager performs the typed action |
| Browser refresh/disconnect after 202 | accepted Operation continues; repeated same key returns same identity |
| Same idempotency key, changed intent | 409; original Operation unchanged |
| Second active command for same Delivery | 409; no second provider call |
| Relative/duplicate/lexical-parent path | 422 before persistence or project access |
| Stale displayed checkpoint | terminal FAILED with `STALE_CHECKPOINT`; no model call |
| Recovery/verification approval required | SUCCEEDED Operation carries safe facts plus exact hidden plan digest |
| Host exits during RUNNING | next startup appends INTERRUPTED; never silently replay |
| Executor raises an unexpected exception | terminal FAILED with generic safe summary; no traceback in browser |
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

## 6. Tests Required

- `tests/web_console/test_core.py`：memory/file store 幂等、单 Delivery admission、persist-before-run、
  safe failure、重开 hash chain 与 orphan RUNNING interruption。
- `tests/web_console/test_manager.py`：五类 typed intent 委托、Project 边界、exact checkpoint、stale 拒绝、
  recovery/verification plan digest 和 safe facts。
- `tests/web_console/test_transport.py`：lifespan、assets/query、202 submit、operation query、Host/Origin、
  content type、body/input limit、409/404 和安全 headers。
- `tests/team_view/ui.test.cjs`：多目录创建、Product/继续/批准操作、操作状态、刷新保持、hidden digest
  不直接渲染、只读 fallback、单 Task 串行角色状态和安全文本。
- `tests/team_view/test_live.py`：candidate branch 必须从 exact candidate ref 唯一推导，不能猜测。
- `tests/contracts/test_json_schema_contracts.py`：Python/JSON Schema 的 QUEUED/RUNNING/terminal 状态和
  path 约束一致。

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
// Wrong: ask the user to copy a 64-character checkpoint or plan digest.
prompt("plan sha256")

// Correct: bind the exact digest to the button while rendering the facts being approved.
submitOperation({ action: "CONTINUE_DELIVERY", approved_plan_sha256: approval.plan_sha256 })
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
ConsoleAdministration.import_document(*, filename: str, content: bytes) -> KnowledgeDocumentView
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
  auto-selects a document. Only `ProductionConfig.team_knowledge_paths` selected in Settings enters
  later preparation contexts through the existing Team knowledge guard.
- Settings round-trip every current secret-free `ProductionConfig` field: platform root, active
  Team/name, selected knowledge, database backend/DSN environment name, ordered model routes,
  Codex executable, live execution and Console port. `runtime_variables` accepts only names referenced
  by that submitted config and is request-only; referenced values never enter a response. A blank UI
  input means preserve the stored value, not erase it.
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
  counts and per-route credential readiness. Zero knowledge is neutral. MySQL connectivity alone
  must not imply the full delivery runtime is ready.
- A config save uses same-directory temporary file, fsync and atomic replace. It validates the selected
  Team/name and every selected knowledge document before publication. Any changed saved config is
  marked `restart_required`; the already constructed Host is not mutated or hot-switched.
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
| Manifest/source/normalized digest or path drift | Entire knowledge listing fails closed |
| Settings select another Team/name or invalid knowledge | 409; config file unchanged |
| New platform root, current Team identity, empty knowledge selection | initialize that Team under the new root; save with restart required |
| New platform root with old-root knowledge paths | 409; never copy or reinterpret the old files |
| Plaintext DSN/API key in config payload | Pydantic/JSON Schema rejects unknown secret field |
| Runtime variable name not referenced by submitted config | 409; neither config nor runtime.env changes |
| Invalid DSN or control-bearing secret input | 409/422; no value persisted or reflected |
| MySQL missing/unavailable on first run | Console starts setup surface; Status says NOT_CONFIGURED/UNAVAILABLE; delivery returns 503 SETUP_REQUIRED |
| Existing config is invalid | Startup fails safely; do not replace it with built-in defaults |
| Settings changed while Host is running | Persist plus `restart_required=true`; no hot mutation |

### 5. Good / Base / Bad Cases

- Good: start with no config/MySQL, view defaults, enter and test a full DSN, save `runtime.env`, restart,
  create a Project, upload a Team DOCX, inspect its content-addressed record, select `content.md`,
  save, restart and prepare a new Requirement whose Team context digest binds that document.
- Base: a Team with no documents is valid and displayed neutrally; no knowledge is loaded implicitly.
- Bad: let the browser submit `/etc/passwd`, recursively scan `knowledge/`, keep only an AI summary,
  return a DSN from the API, accept arbitrary environment names, or change the active Team inside an
  already-running Delivery Host.

### 6. Tests Required

- `tests/knowledge/test_documents.py`: all four formats, exact replay, context readiness, invalid name,
  corrupt/empty input, source/manifest/content tamper and size bounds.
- `tests/config/test_runtime_environment.py`: canonical quote round-trip, `0600`, atomic replacement,
  duplicate/name/control/size/symlink rejection.
- `tests/web_console/test_administration.py`: singleton Team, Project catalog/create, config write/read,
  selected knowledge validation, write-only runtime values, safe MySQL probe, Status and restart semantics.
- `tests/web_console/test_transport.py`: admin verbs, content types/body limits, typed errors and no
  content/secret reflection; missing config/MySQL must still expose Settings/Status while delivery is
  `SETUP_REQUIRED`.
- `tests/team_view/ui.test.cjs`: Project creation, Knowledge and Settings navigation, structured model
  route fields, write-only DSN/key fields, separate Status tab, upload/selection wording and safe text rendering.
- `tests/contracts/test_json_schema_contracts.py`: production config/port and knowledge manifest
  Python-to-Schema parity.

### 7. Wrong vs Correct

```python
# Wrong: turns a local filename into ambient server filesystem authority.
content = Path(request.json()["path"]).read_bytes()

# Correct: the bounded browser body is the only source and becomes an immutable record.
manifest = knowledge_store.import_document(filename=query.filename, content=await request.body())
```

```python
# Wrong: return secrets so the browser can pre-fill its controls.
return {"config": config, "mysql_dsn": stored_dsn}

# Correct: accept an allowlisted write-only update and return status only.
runtime_store.save({config.database.dsn_env: submitted_dsn})
return SettingsSnapshot(config=config, secret_status=(SecretStatus(...),))
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

### 3. Contracts

- `start` requires an executable repository-local `ase-console`, resolves `ASE_CONFIG` or its XDG
  default, then loads sibling `runtime.env` with export semantics before launching. Existing process
  environment remains available and the managed file wins for its declared names. It redirects stdio,
  records the child PID and verifies that the same executable remains alive after startup.
- `stop` sends TERM only when the PID is numeric, alive and its process command identifies this
  repository's executable. It waits up to 20 seconds and never escalates to KILL automatically.
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
| Non-numeric, dead or foreign PID | send no signal; fail safely or report stopped |
| Child exits during startup | remove its PID record, show bounded log tail, exit 1 |
| TERM does not stop in 20 seconds | leave process and PID intact; exit 1 |
| Relative/root/symlink state directory | reject before creating or deleting files |

### 5. Good / Base / Bad Cases

- Good: start once with defaults, save DSN/provider keys in Settings, restart so the launcher exports
  the canonical runtime file, then use `status`/`logs` for operations.
- Base: stopping an already stopped service is idempotent.
- Bad: use a PID file without process identity validation, hard-code DSN in the script, source an
  arbitrary/symlink runtime file, or issue `kill -9`
  after a fixed delay.

### 6. Tests Required

- `sh -n scripts/ase-console-service.sh`.
- No-argument invocation exits 2.
- Focused process tests, when added, must use an isolated absolute `ASE_SERVICE_STATE_DIR` and a fake
  repository-local executable; they must never signal an unrelated host process.
- The launcher test must prove that sibling `runtime.env` reaches the child environment without
  printing its value.

### 7. Wrong vs Correct

```sh
# Wrong: trust a stale PID and force kill an arbitrary process.
kill -9 "$(cat "$PID_FILE")"

# Correct: require numeric PID + exact executable identity, request TERM, and fail without escalation.
is_our_process "$current_pid" || exit 1
kill -TERM "$current_pid"
```
