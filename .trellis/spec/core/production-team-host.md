# Production Team Host Contract

## 1. Scope / Trigger

本规范适用于 `ase project start/reply/approve/status/resume` 的生产装配，以及任何修改
`ProductionConfig`、MySQL repository/dispatch authority、Codex/Responses provider、fallback、上游
Product/Designer/Planner adapter 或 delivery worktree 生命周期的代码。

它不适用于低层 SQLite `ase task ...` 兼容入口，也不授权 Reporter、自动 merge/deploy、复杂 DAG、
消息队列或向量库。

## 2. Signatures

```python
ProductionConfig.from_environment(environment: Mapping[str, str] | None = None) -> ProductionConfig
ProductionConfig.from_file(path: str | Path) -> ProductionConfig
ProductionConfig.require_mysql_dsn(environment: Mapping[str, str]) -> str
ProductionConfig.enabled_routes() -> tuple[ProviderRouteConfig, ...]

OrganizationTeamHost.from_environment(
    environment: Mapping[str, str] | None = None,
) -> OrganizationTeamHost
OrganizationTeamHost.project_entry() -> UnifiedProjectEntryService
project_entry() -> UnifiedProjectEntryService

MySqlTaskRepository(dsn: str)
MySqlTaskRepository.create(task: Task) -> None
MySqlTaskRepository.get(task_id: TaskId) -> Task
MySqlTaskRepository.append_event(event: StateEvent) -> None
MySqlTaskRepository.record_attempt(task_id: TaskId, attempt: int) -> None
MySqlTaskRepository.list_events(task_id: TaskId) -> tuple[StateEvent, ...]
MySqlTaskRepository.current_revision(task_id: TaskId) -> int

MySqlDispatchAuthority.seed_snapshot(
    snapshot: DispatchWorkforceSnapshot,
) -> DispatchWorkforceSnapshot
MySqlDispatchAuthority.current_snapshot(*, project_id: ProjectId,
                                        task_id: TaskId) -> DispatchWorkforceSnapshot
MySqlDispatchAuthority.commit_if_current(
    record: DispatchCommitRecord,
    *,
    expected_snapshot_sha256: DispatchSha256,
) -> DispatchCommitRecord

StructuredModelClient.complete(*, instructions: str,
                               input_payload: Mapping[str, object],
                               output_schema: Mapping[str, object],
                               timeout_seconds: int) -> StructuredModelResult
AgentAdapter.run(request: AgentRequest) -> AgentResult
ModelRouteAttemptStore.append(attempt: ModelRouteAttempt) -> ModelRouteAttempt

ProductionProjectDeliveryBackend.prepare(project_root: str) -> PrepareProjectResult
ProductionProjectDeliveryBackend.start_product(...) -> ProductDiscoveryResult
ProductionProjectDeliveryBackend.reply_product(...) -> ProductDiscoveryResult
ProductionProjectDeliveryBackend.approve_product(...) -> ProductDiscoveryResult
ProductionProjectDeliveryBackend.run_designer(...) -> DesignerServiceResult
ProductionProjectDeliveryBackend.run_planner(...) -> PlanningStageResult
ProductionProjectDeliveryBackend.commit_dispatch(...) -> DispatchCommitRecord
ProductionProjectDeliveryBackend.run_delivery(...) -> RetryResult
ProductionProjectDeliveryBackend.reconcile(...) -> None
```

CLI production command:

```text
ase project start ABSOLUTE_GIT_ROOT --requirement TEXT [--title TEXT]
ase project reply DELIVERY_ID --checkpoint SHA256 --message TEXT
ase project approve DELIVERY_ID --checkpoint SHA256 [--approval-reference REF]
ase project status DELIVERY_ID
ase project resume DELIVERY_ID
```

Environment contract:

| Key | Required | Contract |
|---|---|---|
| `ASE_CONFIG` | no | Secret-free JSON path；缺省 `~/.config/ai-software-engineer/config.json` |
| `ASE_MYSQL_DSN` | yes by default | `mysql+pymysql://...`；实际 key 可由 `database.dsn_env` 改名 |
| `DASHSCOPE_API_KEY` | only when enabled | Qwen Responses route secret；名称由 route 配置 |
| `DEEPSEEK_API_KEY` | only when enabled | DeepSeek Responses route secret；名称由 route 配置 |
| `ASE_RUN_LIVE_TESTS` | live smoke only | 必须 exact `1` 才允许消费真实模型额度 |

## 3. Contracts

### 3.1 Configuration and composition

- `ProductionConfig` 必须符合 `schemas/production-config.schema.json`；`platform_root` 是绝对、安全路径；
  至少一条 enabled route，`(provider, model)` 唯一；secret 只能由环境变量间接引用。
- `codex_cli` route 不得声明 endpoint/API key；`responses` route 必须声明 endpoint 与
  `api_key_env`。示例默认 `live_model_execution=false`，生产执行必须显式改为 `true`。
- 未注入测试 provider 时，`project_entry()` 惰性缓存
  `OrganizationTeamHost.from_environment().project_entry()`；不得要求每个 CLI 进程手工调用
  `configure_project_entry(...)`，也不得因配置失败回退 fake Agent。
- Host 创建时必须先验证 MySQL 并幂等初始化 schema，再打开 organization workspace 和 project
  registry。`platform_root`/sidecar/worktree 不得写入目标项目。
- 组织稳定拥有三个不同的 Coder、QA、Reviewer AgentProfile；model/provider 是每次 Run 的
  `ModelSelection`，不能成为 Agent 身份。

### 3.2 MySQL Task and dispatch authority

- MySQL 8.0/InnoDB 是 `ase project ...` 的 production relational store。Task 快照和 StateEvent 使用
  与 SQLite adapter 完全相同的 Pydantic/JSON contract。
- `append_event` 必须在一个事务内：锁 event ID、锁 Task row、校验 from status/attempt、写入
  `(task_id, revision)` 唯一 event、CAS 更新 Task snapshot；任何失败全部 rollback。
- same event ID + exact body 是幂等重放；same ID + changed body 是
  `EventIdempotencyConflict`。`record_attempt` 只能单调增加且不得超过 Task budget。
- dispatch 使用全局 InnoDB reservation lock，加锁后再次读取 current workforce snapshot；必须同时
  校验 Product revision fence、TechnicalDesign/ExecutionPlan lineage、Agent 独立性、capacity、Lease
  和 selected model 后才能写 immutable dispatch commit。
- dispatch preview 不能假设数据库为空；必须以 authority 的 current snapshot 为输入，否则已有全局
  Assignment/Lease 会造成错误分配或冲突。

### 3.3 Providers and fallback

- Product、Designer、Planner 只能通过 `StructuredModelClient` 返回 Pydantic 可校验的 draft；最终
  ProductSpec/TechnicalDesign/ExecutionPlan ID 与 lineage 由平台生成，模型不能自选事实 identity。
- 任何传给 strict structured-output provider 的 Pydantic Schema 必须先通过
  `strict_output_schema(...)` 深拷贝规范化：每层 object 的 `required` 包含全部 `properties` 且
  `additionalProperties=false`，并删除 provider 不接受的 `default` annotation（尤其 `$ref` sibling）。
  不得修改原始 canonical/Pydantic Schema；domain default 仍负责兼容非 strict provider 的旧输出。
- Coder/QA/Reviewer 都通过相同 `AgentAdapter` 返回 typed Artifact 或无 Artifact 的 typed failure。
  Codex CLI provider 使用 `--ephemeral --ignore-user-config` 和显式 `--sandbox`；当前 CLI 禁止将
  `--approve-for-me` 与 `--sandbox` 组合。Coder 使用
  `workspace-write` sandbox，QA/Reviewer 使用 `read-only` sandbox。
- Codex 子进程环境只允许显式非 secret keys；`UV_CACHE_DIR` 可以透传到 sandbox 可写的 `/tmp`/TMPDIR
  缓存，避免构建工具尝试写只读 home cache。透传环境变量不能扩大 Codex sandbox 文件权限。
- Responses provider 只能把 model output 中明确的 typed tool call 交给 role/run-bound
  `PolicyBoundToolRegistry`；不允许从自由文本提取 shell。所有 provider 最终都要通过相同
  Artifact/task/run/context/source revision/verdict guard。
- route 顺序在 Run 开始前冻结。只有 quota/rate-limit/timeout/temporary provider unavailable 允许切换；
  auth、invalid output、policy violation、产品/规范冲突不允许换模型掩盖。
- delivery route 的每次尝试必须先形成 `ModelRouteAttempt`，写入
  `<project-sidecar>/evidence/model-route-attempts/<run-id>/`。exact replay 复用已持久化 result，slot/body
  冲突或 hash 损坏 fail closed。每条 attempt 必须保存完整 canonical `AgentRequest` 的 SHA-256；进程
  重启后，同一 `run_id` 的权限、输入制品、输出 Schema、超时或其他 request 字段发生变化都必须拒绝
  replay。
- Product/Designer/Planner 的 accepted stage artifact 可在 resume 时复用；上游 structured fallback
  目前没有独立 durable attempt ledger，因此 provider 返回到 stage artifact 落盘之间仍有可能重复计费的
  crash window。修改这条边界前应另立任务，不能在文档中声称 exactly-once billing。

### 3.4 Worktree and delivery

- dispatch 后才可 materialize Task；Task repository、Artifact/Context/Evidence roots、Agent definitions
  和 dispatch bundle 必须来自同一 project sidecar 与 exact revision lineage。
- 目标项目必须是真实目录、Git root、clean working tree 且 HEAD 为 full commit。Task `allowed_paths`
  来自 TechnicalDesign affected paths，commands 来自确定性 ProjectProfile build-system allowlist。
- Coder worktree 位于 `<platform_root>/worktrees/<project-id>/<task-id>/coder-attempt-01` 并使用
  `ai/<task-id>/attempt-1` branch；QA、Reviewer 在 exact candidate SHA 的不同 detached worktree。
- Coder 必须留下 clean candidate commit，且 changed paths 不越权；QA/Reviewer 不得改变 HEAD 或工作树。
  clean worktree 可以关闭，dirty/漂移现场必须保留，禁止 force reset/delete。
- delivery 完成只产生 `DONE + candidate_revision`；不 merge、不 push 目标保护分支、不 deploy。
- production v0.1 每个 delivery role 的 Task attempt budget 是 1；自动路径不能安全继续时必须生成
  BLOCKED/WAITING_HUMAN 证据，而不是无限重试。

## 4. Validation & Error Matrix

| 输入/故障 | 检测点 | 结果 |
|---|---|---|
| 配置缺失、未知字段、相对 `platform_root` | ProductionConfig/Schema | `ProductionConfigError`/ValidationError，不连接模型 |
| DSN env 缺失、MySQL 停止/认证失败 | Host/MySqlTaskRepository | 脱敏 StoreError，CLI exit 2，不创建 fake Host |
| duplicate Task / unknown Task | MySQL repository | `TaskAlreadyExists` / `TaskNotFound` |
| stale event status/revision 或 changed replay | locked append transaction | rollback；`InvalidStateEvent`/`EventIdempotencyConflict` |
| stale workforce snapshot / capacity/Lease 冲突 | MySQL dispatch lock | rollback；不发布 partial dispatch |
| Codex 未登录、HTTP auth 失败 | provider adapter | non-transient failure，无 fallback、无 Artifact |
| HTTP 429/quota/timeout/5xx | adapter + fallback policy | append attempt evidence；最多尝试下一 enabled route |
| provider JSON/Artifact 不合法 | Pydantic/artifact guard | `INVALID_OUTPUT`，不 fallback、不生成 verdict |
| Product 缺关键决策 | Product Agent | `WAITING_PRODUCT_REPLY`，要求 exact checkpoint reply |
| ProductSpec 未获 exact human approval | Product gate | `WAITING_PRODUCT_APPROVAL`，不运行 Designer |
| 项目规则冲突 | SpecCompiler | `WAITING_HUMAN`，不静默选边 |
| target project dirty/not Git/HEAD 漂移 | delivery precondition | stable failure + preserved project/worktree |
| Coder 未 commit、越权路径或 dirty | Codex/Responses Git guard | policy/invalid-output failure；不进入 QA |
| QA/Reviewer candidate 不同或修改 worktree | dispatch/worktree/artifact guard | fail closed；不进入 DONE |
| `status`/`resume` durable facts 损坏 | checkpoint reconciliation | corruption/drift failure；不覆盖原记录 |

错误消息只能包含稳定分类和安全摘要；不得输出 DSN、Authorization header、API key、provider response
body 或目标项目中的 secret。

## 5. Good / Base / Bad Cases

- **Good**：真实临时 Git 项目 + MySQL + scripted structured/delivery providers 完成
  prepare→Product approval→Design→Plan→dispatch→Coder commit→独立 QA/Review→DONE；main checkout 和
  target files 不变，candidate commit 可由 `git show` 复核。
- **Base**：缺少真实额度时，contract/E2E 使用注入的 deterministic providers；Production Host、MySQL、
  dispatch、worktree 和 typed artifact 仍走真实实现。只有显式 live smoke 才消费 GPT-5.5。
- **Bad**：在每个项目复制 AgentProfile；把 DSN/API key 写入 JSON；Planner 直接提交分配；让同一 Agent
  同时当 Coder 和 Reviewer；在 main checkout 写代码；auth/invalid output 后静默换模型；自动 merge。

## 6. Tests Required

- `tests/config/test_production.py`：配置文件/env、route 条件、duplicate route、secret 不落盘；
- `tests/contracts/test_json_schema_contracts.py`：ProductionConfig positive/negative canonical schema；
- `tests/store/test_mysql_repository.py`：与 SQLite 可观察行为一致、atomic append、replay/conflict、rollback、
  reopen；必须通过 `ASE_TEST_MYSQL_DSN` 显式 opt-in；
- `tests/project_manager/test_mysql_dispatch_authority.py`：snapshot/commit 幂等、stale fence、reservation、
  corruption、跨连接恢复；
- `tests/agents/test_codex_cli.py`、`test_responses.py`、`test_fallback.py`、
  `test_openai_compatible.py`：request/response、Git、tool、error mapping、fallback allowlist 和 attempt replay；
- `tests/project_manager/test_production_agents.py`：Product/Designer/Planner typed draft 和 exact lineage；
- `tests/project_manager/test_production_backend.py`：真实 MySQL + 临时 Git + scripted team 到 DONE，独立
  verifier worktrees 检查 exact candidate，主 checkout 零污染；
- `scripts/smoke-live-gpt55.sh`：只有 `ASE_RUN_LIVE_TESTS=1` 才运行，不进默认 CI，不自动 merge；
- 合并门禁：full pytest、Ruff check/format、strict mypy、offline build、`git diff --check`。

## 7. Wrong vs Correct

### Wrong

```python
# Per-command manual composition, plaintext secret, and fake fallback.
config = {"mysql_dsn": "mysql://user:password@host/db"}
configure_project_entry(lambda: fake_team(project_root))
result = planner.choose_and_commit_agent_and_model()
```

### Correct

```python
config = ProductionConfig.from_environment()
host = OrganizationTeamHost(config=config, environment=os.environ)
entry = host.project_entry()
result = entry.start(StartProjectDelivery(project_root=absolute_git_root, requirement=requirement))
```

前者让 secret、fake 执行和调度权限穿透用户入口；后者由唯一 production composition root 加载环境
secret、MySQL、organization-owned team 和 policy-bound adapters，Planner 仍只能 preview，Project
Manager 在 MySQL authority 下重新校验后 commit dispatch。
