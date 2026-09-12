# Local Web Console Contract

## 1. Scope / Trigger

修改 `web_console/`、浏览器交付操作、Team View 中的写入口、后台 Project Manager 执行、
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

ProjectManagerConsoleAdapter.execute(intent: ConsoleIntent) -> ConsoleCommandResult
create_console_app(
    console: ConsoleApplication,
    reader: TeamReader,
    *,
    company_id: str,
    port: int = 8765,
) -> FastAPI
production_console_app(
    environment: Mapping[str, str] | None = None,
    *,
    port: int = 8765,
) -> FastAPI
```

`ConsoleIntent` 当前只允许：

- `CREATE_REQUIREMENT_PROJECT(name, project_roots)`；
- `PRODUCT_REPLY(delivery_id, expected_checkpoint_sha256, message)`；
- `PRODUCT_APPROVAL(delivery_id, expected_checkpoint_sha256)`；
- `CONTINUE_DELIVERY(delivery_id, expected_checkpoint_sha256, approved_plan_sha256?)`。

公开持久化契约是 `schemas/console-operation.schema.json`。

## 3. Contracts

### 3.1 Command/query separation

- `ProductionTeamReader` 和 Team View projection 永远只读；不得为了方便在 snapshot/GET 中装配
  `OrganizationTeamHost`、初始化数据库、创建 workspace 或推进 Delivery。
- 浏览器命令只能进入 `ProjectConsole`；它不重新实现 Product、Designer、Planner、Delivery、QA、
  Reviewer 或 recovery 规则，只委托现有 Project Manager application interfaces。
- Operation 是“浏览器操作执行状态”，不是 Task、Delivery、Artifact 或 verdict 的替代权威。
  成功、失败或重启后继续都必须重新读取 durable Delivery facts。

### 3.2 Persist before execution

- HTTP 先校验 typed intent，再将 `QUEUED` Operation 追加到
  `companies/<company_id>/requests/_console_operations/operation_<id>/000001.json`，最后返回 `202`。
- HTTP request handler 不执行 provider；后台 dispatcher 领取后追加 `RUNNING`，完成后追加一个终态。
- Operation 状态只允许：
  `QUEUED → RUNNING → SUCCEEDED | FAILED | INTERRUPTED`。
- 每个 record 包含 previous digest、immutable intent digest 和自身 digest；文件名必须等于六位 sequence。
  生产写使用进程锁、exclusive append 和 fsync，不覆盖历史。
- operation ID 由 company + browser idempotency key 稳定派生。同一个 key + exact intent 返回同一
  Operation；同 key 不同 intent 拒绝。同一 Delivery 同时只允许一个非终态 Operation。

### 3.3 Recovery and at-most-once boundary

- Host 启动时把遗留 `RUNNING` 标记为 `INTERRUPTED`，不得自动再次调用 provider。
- 用户在 UI 点击统一“继续交付”时，新的 Operation 根据当前 Delivery checkpoint 决定下一动作；
  已完成阶段不重跑，不确定模型调用遵守既有 recovery/verification approval 规则。
- UI 只能批准 Project Manager 返回并验证过的 exact recovery/verification plan SHA。SHA 可以隐藏在
  控件中，但批准前必须显示候选提交、Agent/模型或保留修改/目标基线等可理解事实。
- checkpoint 或 plan 已变化时必须拒绝；刷新最新投影后重新提交，不得自动替换用户批准对象。

### 3.4 Security and process boundary

- Uvicorn 只监听 `127.0.0.1`；transport 要求 exact `Host=127.0.0.1:<port>`，Origin 缺省或同源。
- POST 只接受 `application/json`，body 最大 64,000 bytes；输入错误返回稳定小型 error envelope，
  不回显完整 payload、traceback、secret 或未经边界验证的模型文本。
- 项目目录必须是唯一、无控制字符、无 lexical `..` 的绝对路径；真正的源码/Git/规范约束仍由
  Project Manager prepare 校验。
- static assets 使用 `textContent` 渲染外部文本；CSP 禁止外部 script/style、frame 和 form action。
- MySQL DSN/API key 不得写入浏览器、Operation、配置文件、plist 或 systemd unit。安全自动登录启动
  必须先实现 macOS Keychain / Linux Secret Service 等 secret adapter。

### 3.5 User-visible flow

- 日常用户可在网页完成：多目录需求项目创建、Product 对话、ProductSpec 批准、统一继续、exact
  recovery/verification 计划批准、进度观察和 Candidate 领取。
- 一个 Task 的 Coder/QA/Reviewer 串行。UI 只把 `current_stage=true` 的 assignment 标成执行中；
  已完成/未来角色不得同时显示为运行。
- DONE 只展示已经由 durable facts 证明的 candidate commit、可唯一定位的 branch 和验证证据。
  v0.1 不自动 merge、push 或 deploy。
- `ase request`、`verify-*` 和底层 Runtime 保留作运维/诊断/break-glass，不是 README 的日常入口。

## 4. Validation & Error Matrix

| Case | Required result |
|---|---|
| Valid new request, one or many absolute roots | persist QUEUED, return 202, background Project Manager prepares it |
| Browser refresh/disconnect after 202 | accepted Operation continues; repeated same key returns same identity |
| Same idempotency key, changed intent | 409; original Operation unchanged |
| Second active command for same Delivery | 409; no second provider call |
| Relative/duplicate/lexical-parent path | 422 before persistence or project access |
| Stale displayed checkpoint | terminal FAILED with `STALE_CHECKPOINT`; no model call |
| Recovery/verification approval required | SUCCEEDED Operation carries safe facts plus exact hidden plan digest |
| Host exits during RUNNING | next startup appends INTERRUPTED; never silently replay |
| Executor raises an unexpected exception | terminal FAILED with generic safe summary; no traceback in browser |
| Missing production config/MySQL/company | startup/read fails safely; no fake workspace or data |
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
- `tests/web_console/test_project_manager.py`：四类 typed intent 委托、exact checkpoint、stale 拒绝、
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
