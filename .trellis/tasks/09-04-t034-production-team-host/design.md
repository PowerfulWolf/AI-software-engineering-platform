# T034 Design：Production Team Host 与真实交付闭环

## 1. 边界与上线顺序

T034 不推翻 T032 的 facade，而是填上它故意留下的 production composition seam。上线顺序固定为：

```text
ProductionConfig
  -> MySQL durable state
  -> OrganizationTeamHost
  -> ProjectDeliveryBackend
  -> Product/Designer/Planner adapters
  -> serial Coder -> QA -> Reviewer execution
```

每一层只依赖下一层的 typed Port。CLI 不感知数据库驱动、provider SDK 或 Agent prompt；目标 Git
项目也不保存这些平台事实。

## 2. 部署目录

```text
ASE_HOME/
  organization/                    # 组织规则与 AgentProfile
  projects/<project_id>/           # 项目 sidecar、事实、artifact、context
  worktrees/<project_id>/<task>/   # Coder/QA/Reviewer 隔离 checkout

target-project/                    # 用户给出的 Git 项目，只有业务改动
```

`ASE_HOME` 必须是绝对目录，并不得与目标项目重叠。数据库连接不落盘到目标项目；secret 只从环境变量
读取。

## 3. ProductionConfig

部署配置由一个非 secret JSON 文件和环境变量共同组成：

```json
{
  "platform_root": "/absolute/ase-data",
  "database": {"backend": "mysql", "dsn_env": "ASE_MYSQL_DSN"},
  "model_policy": {
    "routes": [
      {"provider": "codex", "model": "gpt-5.5"},
      {"provider": "qwen", "model": "qwen3.8-max"},
      {"provider": "deepseek", "model": "deepseek-v4-pro"}
    ]
  }
}
```

默认配置文件由 `ASE_CONFIG` 指定；未指定时使用 `~/.config/ai-software-engineer/config.json`。
MySQL DSN、HTTP API key 只允许通过被配置项引用的环境变量注入。错误消息不得输出 DSN、header、
provider body 或 secret。

## 4. MySQL durable state

### 4.1 TaskRepository

新增 `MySqlTaskRepository`，继续实现现有 `TaskRepository`，不向 domain 暴露 SQL/driver 类型。

```text
tasks(id PK, payload_json JSON, status, revision, created_at, updated_at)
state_events(event_id PK, task_id FK, revision, payload_json JSON,
             UNIQUE(task_id, revision))
```

`create`、`get`、`record_attempt`、`append_event`、`list_events`、`current_revision` 与 SQLite 的可观察
行为完全一致。`append_event` 使用事务和 `SELECT ... FOR UPDATE` 锁定 Task 行：先检查 event ID
幂等，再校验当前状态和 revision，最后写 event 并 CAS 更新 snapshot。死锁、连接中断和 schema 错误
统一映射为脱敏的 `StoreError`；重复键根据约束语义映射为现有 typed error。

### 4.2 Dispatch authority

`MySqlDispatchAuthority` 使用同一个 MySQL 实例中的 snapshot/commit 表和行锁。Product revision 目前仍是
文件事实，因此 commit 顺序继续是：

```text
acquire Product revision fence
  -> begin MySQL transaction
  -> lock workforce snapshot row FOR UPDATE
  -> verify current Product/Designer/Planner facts
  -> insert immutable dispatch commit
  -> commit
```

SQLite adapter保留给单机离线测试。生产 Host 默认拒绝 SQLite，除非配置显式声明
`mode=offline_test`。

### 4.3 Docker

仓库提供独立 `docker-compose.yml`，服务名和 volume 使用本项目专属前缀，不探测也不复用现有 MySQL
容器。Compose 的开发账号只用于 loopback 本地开发；生产必须外部注入强凭据。

## 5. Model execution 与降级

### 5.1 身份分离

`AgentProfile` 是长期组织成员；`ModelSelection` 是单次 Run 的大脑分配。更换 provider/model 不创建新
Agent，也不能改变 Assignment、权限、上下文或验收门禁。

### 5.2 默认路由

```text
primary:  codex / gpt-5.5 / reasoning=medium
fallback: qwen / qwen3.8-max
fallback: deepseek / deepseek-v4-pro
```

`qwen3.7-plus` 和 `deepseek-v4-flash` 作为 economy/standard route，由 Planner 的风险、复杂度和后续
evaluation 决定；不是无条件替代复杂交付模型。“免费”是部署账户的额度事实，而不是模型静态属性。

### 5.3 Provider adapters

- `CodexCliAgentAdapter` 使用当前机器已登录的 Codex 账号，执行 `codex exec --ephemeral`；
- `ResponsesAgentAdapter` 面向 OpenAI/Qwen/DeepSeek 的 Responses-compatible HTTP endpoint；
- 两者都只返回 `AgentResult`，输出必须通过同一 Artifact schema 和 lineage 校验；
- provider 原始输出只在内存中短暂存在，durable evidence 只保存脱敏摘要和 typed usage。

Coder 必须在 disposable role worktree 中运行。CLI provider 的第一阶段隔离边界是 Git worktree + Codex
sandbox + 运行后 changed-path/commit 校验；HTTP tool-loop provider 必须在每次工具调用前通过
`PolicyBoundToolRegistry`。QA/Reviewer 不能修改 production paths，且必须验证同一 candidate SHA。

### 5.4 有界 fallback

新增一个 provider-neutral `FallbackAgentAdapter`。候选列表在 Run 开始时冻结，最多每条 route 一次：

| 失败 | fallback | 结果 |
| --- | --- | --- |
| quota exhausted / HTTP 429 | 是 | 记录 route attempt 后试下一条 |
| timeout / HTTP 5xx / provider unavailable | 是 | 有界切换 |
| authentication/authorization | 否 | fail closed |
| invalid Artifact/JSON | 否 | fail closed |
| policy violation | 否 | fail closed |
| 产品/规范冲突 | 否 | `WAITING_HUMAN` |

每一次尝试写 immutable `ModelRouteAttempt` evidence：run、provider、model、顺序、开始/结束时间、结果码、
是否切换。不得保存 secret 或 provider response body。

## 6. Production Team Host

`OrganizationTeamHost.from_environment()` 是唯一 production composition root：

1. 读取、校验配置并建立 MySQL；
2. initialize-or-open organization workspace 和 project registry；
3. 加载组织硬规则、AgentProfile 与 ModelPolicy；
4. 建立 preparation/Product/Designer/Planner/dispatch/Runtime services；
5. 返回 `UnifiedProjectEntryService`。

`project_entry()` 在没有测试注入 provider 时惰性调用 Host，因此安装后的 `ase project start` 不需要应用
代码再手工调用 `configure_project_entry(...)`。缺配置、数据库不可达或模型 route 不可用时应返回稳定
配置错误，不可回退 fake Agent。

## 7. 恢复与幂等

- 所有 stage 先查原生 store，再 exact-create 或 exact-compare；
- 进程重启后从 append-only delivery checkpoint 指向的首个未完成阶段继续；
- fallback attempt 和已接受 Artifact 按 `run_id` 幂等，不能因 resume 再次计费或改变 route；
- dirty/漂移 worktree 保留现场并 `WAITING_HUMAN`，绝不 reset/delete；
- main checkout 不写、不 merge、不 deploy。

## 8. 测试与验收

### Offline required

- SQLite/MySQL 共用 repository contract suite；
- MySQL Docker 集成测试验证重启、并发 revision、重复事件和回滚；
- scripted provider 验证 fallback 矩阵与 evidence；
- Python/Java/C++ 临时 Git fixture 验证目录+需求、Product gate、真实 candidate、独立 QA/Review；
- CLI 子进程验证自动 Host、脱敏错误和跨进程 resume。

### Live opt-in

`scripts/smoke-live-gpt55.sh` 只在显式环境开关和本地登录/secret 可用时执行，不进入默认 CI。它使用
临时 Git fixture，不自动 merge，并输出 delivery/candidate/evidence ID；缺额度或权限报告真实 typed
failure，不能伪报通过。

## 9. 分批交付

T034 内部按可独立验收的 vertical slices 提交：

1. MySQL TaskRepository + Docker；
2. provider policy、Responses/Codex adapters + fallback evidence；
3. ProductionConfig + auto Host；
4. native upstream producers + policy-bound role execution；
5. full offline E2E、opt-in live smoke、文档和 archive。

在第 5 步完成前只能称为“production path 正在组装”，不能宣称平台已经完成真实自主交付。
