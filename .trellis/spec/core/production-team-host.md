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
ProductionConfig.routes_for(role: TeamRole) -> tuple[ProviderRouteConfig, ...]
ProductionConfig.effective_connection_mode(route: ProviderRouteConfig) -> Literal["direct", "proxy"] | None
ProductionConfig.path_from_environment(environment: Mapping[str, str] | None = None) -> Path
_default_platform_root() -> str
_normalize_platform_root(value: str) -> str

TeamHost.from_environment(
    environment: Mapping[str, str] | None = None,
) -> TeamHost
TeamHost.project_entry() -> UnifiedProjectEntryService
TeamHost.work_queue -> MySqlPersistentWorkQueue
TeamHost.planner_dispatcher(*, demand_builder, worker_id,
                                        owner_token_factory=None) -> DispatcherLoop
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
MySqlDispatchAuthority.current_snapshot(*, repository_id: RepositoryId,
                                        task_id: TaskId) -> DispatchWorkforceSnapshot
MySqlDispatchAuthority.commit_if_current(
    record: DispatchCommitRecord,
    *,
    expected_snapshot_sha256: DispatchSha256,
) -> DispatchCommitRecord

StructuredModelClient.complete(*, instructions: str,
                               input_payload: Mapping[str, object],
                               output_schema: Mapping[str, object],
                               timeout_seconds: int,
                               input_images: tuple[Path, ...] = ()) -> StructuredModelResult
AgentAdapter.run(request: AgentRequest) -> AgentResult
ModelRouteAttemptStore.append(attempt: ModelRouteAttempt) -> ModelRouteAttempt

ProductionProjectDeliveryBackend.prepare(repository_root: str) -> PrepareProjectResult
ProductionProjectDeliveryBackend.start_product(...) -> ProductDiscoveryResult
ProductionProjectDeliveryBackend.reply_product(...) -> ProductDiscoveryResult
ProductionProjectDeliveryBackend.approve_product(...) -> ProductDiscoveryResult
ProductionProjectDeliveryBackend.run_designer(...) -> DesignerServiceResult
ProductionProjectDeliveryBackend.run_planner(...) -> PlanningStageResult
ProductionProjectDeliveryBackend.commit_dispatch(...) -> DispatchCommitRecord
ProductionProjectDeliveryBackend.run_delivery(...) -> RetryResult
ProductionProjectDeliveryBackend.reconcile(...) -> None
_delivery_timeout_seconds(role: AgentRole) -> int
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
| `ASE_CONSOLE_PORT` | no | 兼容运维覆盖；未设置时使用 `ProductionConfig.console_port` |
| `ASE_MYSQL_DSN` | delivery yes | `mysql+pymysql://...`；可由设置页写入 sibling `runtime.env`，实际 key 可由 `database.dsn_env` 改名；缺失时 Web Console 降级启动 |
| `DASHSCOPE_API_KEY` | only when enabled | Qwen Responses route secret；名称由 route 配置 |
| `DEEPSEEK_API_KEY` | only when enabled | DeepSeek Responses route secret；名称由 route 配置 |
| `ASE_RUN_LIVE_TESTS` | live smoke only | 必须 exact `1` 才允许消费真实模型额度 |

## 3. Contracts

### 3.1 Configuration and composition

- `ProductionConfig` 必须符合 `schemas/production-config.schema.json`。macOS/Linux 省略
  `platform_root` 时纯解析为当前用户的 `~/.ase`；显式绝对路径或安全的 `~/...` 优先，后者先展开
  再进入同一校验。任何显式路径中的 `..`、控制字符或非绝对结果都失败关闭，不得回退默认值；
  解析本身不得创建目录。至少一条 enabled route，`(provider, model, reasoning_effort, kind, effective_connection_mode)` 唯一；`console_port` 必须为
  `1..65535`；JSON 中 secret 只能由环境变量间接引用。`ProductionConfig.default()` 是 Web
  Console 首次运行的内置可见配置；仅当配置文件不存在时使用，不写文件。已有但无效的配置不得
  回退默认值。CLI 生产命令仍要求有效的显式/默认路径配置文件。
- `codex_cli` route 不得声明 endpoint/API key；`responses` route 必须声明 endpoint 与
  `api_key_env`。示例默认 `live_model_execution=false`，生产执行必须显式改为 `true`。
- `agent_model_routes` 为空时兼容旧配置并对所有角色使用 enabled `model_routes` 顺序；非空时必须
  精确覆盖 Manager/Product/Designer/Planner/Coder/QA/Reviewer 七个角色，每个引用只可指向启用且
  唯一的 provider/model/reasoning effort/kind/connection mode。首项是该 Agent 主模型，后续项是冻结后的降级顺序；
  显式策略是可用模型目录的有序子集，未被该 Agent 选中的启用模型不得自动成为备用路由。
  同一模型的不同推理程度、执行类型或 Codex CLI 连接方式是可独立选择的路由。旧引用缺少
  `reasoning_effort`、`route_kind` 或 `connection_mode` 时，只在全部已声明字段过滤后恰好剩
  一条 enabled route 才可解析；否则失败关闭。
- 新生成的 `ModelSelection`、`AgentDefinition` 和 `ModelRouteAttempt` 必须固化精确的
  `reasoning_effort`、`route_kind` 与 Codex CLI `connection_mode`。升级前已持久化且缺少字段的事实保留为“未指定”；
  frozen policy、claim、实际执行和 route-attempt replay 不得在同 provider/model/effort 的
  Codex CLI 与 Responses 间猜测。旧 SHA-256 payload 不因新增可选字段重算或改写。
- `image_input` 可显式声明两类 route 的图片能力；省略时 Codex CLI 为 true、Responses 为
  false。带截图的 Product 调用跳过不支持图片的 route；没有可用图片 route 时返回非瞬态 typed
  provider error，不得丢图退化成纯文字。
- 未注入测试 provider 时，`project_entry()` 惰性缓存
  `TeamHost.from_environment().project_entry()`；不得要求每个 CLI 进程手工调用
  `configure_project_entry(...)`，也不得因配置失败回退 fake Agent。
- Host 创建时必须先验证 MySQL 并幂等初始化 schema，再打开唯一 Team workspace 和 sibling Project
  registry。`platform_root`/sidecar/worktree 不得写入目标项目。
- Project registry 由 `TeamWorkspace.project_registry()` 装配，位于
  `<platform_root>/projects/`。每次 `_runtime(project_id)` 先从 Team 与该 Project 的
  `knowledge/selection.json` 解析只读、脱敏、digest-bound 上下文；仅在 selection 记录缺失时
  使用配置字段兼容旧入口。缓存只可在 exact `ContextSource` tuple 未变化时复用；Project 选择
  变化只能替换该 Project runtime，Team 选择变化会在各 Project 下次访问时分别替换。所有权
  契约见 `team-workspace.md`。
- Team 稳定拥有三个不同的 Coder、QA、Reviewer AgentProfile；model/provider 是每次 Run 的
  `ModelSelection`，不能成为 Agent 身份。
- Host 装配组织级 `MySqlPersistentWorkQueue`；Planner 拥有流转与派发策略，Dispatcher 只执行有界、
  确定性的 tick。完整事务和 Lease fence 见 `persistent-work-queue.md`。

### 3.2 MySQL Task and dispatch authority

- MySQL 8.0/InnoDB 是 `ase project ...` 的 production relational store。Task 快照和 StateEvent 使用
  与 SQLite adapter 完全相同的 Pydantic/JSON contract。
- `append_event` 必须在一个事务内：先锁 Task row、再检查/锁 event ID、校验 from status/attempt、写入
  `(task_id, revision)` 唯一 event、CAS 更新 Task snapshot；任何失败全部 rollback。
- 不要在竞争同一 Task 的行锁前获取不同缺失 event ID 的间隙锁，否则相邻 ID 的插入会形成死锁。
  `test_competing_connections_cannot_publish_the_same_revision` 使用相邻 ID 运行 10 轮；每轮必须只有
  一个成功、一个 InvalidStateEvent，最终恰好一条 event/revision，不允许用连接错误或重跑掩盖。
- same event ID + exact body 是幂等重放；same ID + changed body 是
  `EventIdempotencyConflict`。`record_attempt` 只能单调增加且不得超过 Task budget。
- dispatch 使用全局 InnoDB reservation lock，加锁后再次读取 current workforce snapshot；必须同时
  校验 Product revision fence、TechnicalDesign/ExecutionPlan lineage、Agent 独立性、capacity、Lease
  和 selected model 后才能写 immutable dispatch commit。
- dispatch preview 不能假设数据库为空；必须以 authority 的 current snapshot 为输入，否则已有全局
  Assignment/Lease 会造成错误分配或冲突。
- current_snapshot 读取与 dispatch task_id 关联的 MySQL typed Task 快照：DONE/BLOCKED/FAILED 的
  Lease 不再计入 active_leases；保留不可变 dispatch commit 和完整 Assignment 历史。未物化或
  未结束的 Task 仍保留容量预留，不能仅凭父需求、Agent 文本或 wall-clock 猜测完成。preview 与
  commit-under-lock 使用同一派生规则，损坏的 Task JSON 必须 fail closed。

### 3.3 Providers and fallback

#### Immutable policy revisions (2026-09-08)

Scope: changing the configured primary model in an already initialized Team, both native
and recovery dispatch. `AgentProfile.id` and `default_model_policy_id` must remain stable.

Signatures: `FileTeamWorkforceStore.put_policy(policy, *, versioned=False)` and
`get_policy(policy_id, *, version=None)`. Production callers opt into versioned writes. `_workforce`
sets `ModelPolicy.version = "v0.1-" + sha256(canonical_policy_without_version)`; canonical encoding is
UTF-8, sorted JSON keys, compact separators, ensure_ascii=False. Full policy content participates.
ModelSelection already contains policy_version; no wire or SQL schema changes are required.

Versioned files use `<policy-id>__<sha256(version)>.json` in `team/model-policies`, with the
same key as envelope object_id. Their payload retains the logical policy ID/version. Legacy
`<policy-id>.json` remains unchanged. No latest pointer or implicit policy promotion is introduced.
Exact-version reads select the versioned file, otherwise accept legacy only if its version matches.
Runtime allocation reads by selection.policy_id AND selection.policy_version.

| Case | Required result |
|---|---|
| New configured model | New version, same team members; preserve old policy/dispatch |
| Same version/body | Idempotent replay |
| Same version/different body | RuntimeWorkspaceConflict; never overwrite |
| Missing requested version / wrong identity | RuntimeWorkspaceCorruption |
| Corrupted/symlink revision | Fail closed; never fall back to legacy |
| Legacy selection | Exact matching legacy record remains readable |

Workforce publication uses exclusive atomic creation and revalidates a concurrent winner.
Good: switch models with unchanged AgentProfile and both policy versions readable. Base: legacy
unversioned callers keep strict immutable semantics. Bad: delete/replace the old policy or mint new
Agent IDs solely to change model. Tests: runtime_workspace/test_binding.py covers exact versions,
conflict, corruption and preserved legacy bytes; production_backend test preloads an old policy,
changes configured model in the same organization, then exercises native dispatch and delivery.
Recovery uses the same put_policy(versioned=True); its real Git/MySQL offline suite must also pass.

Wrong: reuse fixed policy ID/version with changed route, or read a selected policy by ID alone.
Correct: stable policy family/Agent identity, content-versioned policy, exact selected-version read.
Root cause: immutability was enforced correctly, but production configuration lacked revision identity;
fresh-organization tests hid the conflict. This does not authorize replaying terminal Tasks.

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
- 可选 `ProductionConfig.codex_cli_proxy_base_url` 仅接受不含 userinfo、query、fragment 的本机
  loopback HTTP base URL。只有 `effective_connection_mode(route) == "proxy"` 的 Codex CLI
  路由才在保留 `--ignore-user-config` 的前提下显式指定固定 `ase_local_proxy` provider、
  `wire_api=responses` 和该 base URL；显式 `direct` 即使存在全局 URL/Key 也不得接收代理参数。
  旧路由未声明 mode 时，有 URL 继承 `proxy`，否则继承 `direct`。可选
  `codex_cli_proxy_api_key_env=ASE_CODEX_PROXY_API_KEY` 只保存环境变量名；
  Settings 把完整 Key 写入 0600 `runtime.env`，CLI 仅获得该显式值并用 `env_key` 认证，同时
  以 CLI shell environment policy 排除该变量，不把值写入 argv、配置 JSON、Operation 或提示。
  若未配置平台管理的 Key，保留 `requires_openai_auth=true`，CLI 从相同 `CODEX_HOME` 的已保存
  API key 凭证获取代理密钥。未设置 URL 时保持既有直连登录语义。不得读取用户
  `config.toml`、从 URL 携带密钥，或因代理失败静默改走 OpenAI 直连。保存后必须重启 Host；
  历史 Requirement/Task/Operation 不改写，现有阻塞需求仍需用户显式继续。

### Per-route Codex connection validation

| Input | Boundary / result |
|---|---|
| 同 provider/model/effort/kind 的 direct 与 proxy | 配置允许，Agent 引用与 ModelPolicy 精确区分 |
| 显式 proxy 但 URL 缺失；Responses 声明 mode | `ProductionConfig` 拒绝，不能创建 Agent |
| 旧引用缺少 mode 且匹配双路由 | `routes_for`、policy/claim/recovery 解析拒绝歧义 |
| 显式 direct 且配置了代理 Key | structured 与 delivery adapter 均传 `proxy_base_url=None`、`proxy_api_key_env=None`，不要求代理 Key |
| 已完成旧调用缺少 mode | 保留原始 digest；只读 UI 显示“连接方式未记录” |

Good：同名 direct/proxy 两条路由各自出现在 Agent 选择和状态页，调用记录带实际 mode。
Base：旧单路由配置继续继承原全局连接语义。Bad：用当前 Settings URL 反推旧调用走了代理。
测试点：`tests/config/test_production.py` 验证迁移与唯一性；`tests/manager/test_production_{backend,delivery}.py`
断言代理 Key 隔离；`tests/agents/test_{fallback,model_diagnostics}.py` 断言真实尝试的不可变 mode；
`tests/work_queue/test_route_binding.py` 断言冻结路由歧义保护。错误实现是仅在页面增加模式标签；
正确实现必须使五元组贯穿 config → policy → selection/claim → adapter → immutable attempt → read model。
- Codex 子进程环境只允许显式非 secret keys；`UV_CACHE_DIR` 可以透传到 sandbox 可写的 `/tmp`/TMPDIR
  缓存，避免构建工具尝试写只读 home cache。透传环境变量不能扩大 Codex sandbox 文件权限。
- Responses provider 只能把 model output 中明确的 typed tool call 交给 role/run-bound
  `PolicyBoundToolRegistry`；不允许从自由文本提取 shell。所有 provider 最终都要通过相同
  Artifact/task/run/context/source revision/verdict guard。
- 默认配置优先级为 GPT → DeepSeek → Qianwen（provider key 为 `qwen`）；
  `enabled_routes()` 保留配置数组顺序并跳过禁用项，不按供应商品牌硬编码重排。
- route 顺序在 Run 开始前冻结。只有 quota/rate-limit/timeout/temporary provider unavailable 允许切换；
  auth、invalid output、policy violation、产品/规范冲突不允许换模型掩盖。
- delivery route 的每次尝试必须先形成 `ModelRouteAttempt`，写入
  `<project-sidecar>/runs/model-routes/<run-id>/`（通过 `model_route_root` 定位）。exact replay 复用已持久化 result，slot/body
  冲突或 hash 损坏 fail closed。每条 attempt 必须保存完整 canonical `AgentRequest` 的 SHA-256；进程
  重启后，同一 `run_id` 的权限、输入制品、输出 Schema、超时或其他 request 字段发生变化都必须拒绝
  replay。
- Product/Designer/Planner 的 accepted stage artifact 可在 resume 时复用；上游 structured fallback
  目前没有独立 durable attempt ledger，因此 provider 返回到 stage artifact 落盘之间仍有可能重复计费的
  crash window。修改这条边界前应另立任务，不能在文档中声称 exactly-once billing。

#### Route kind identity: validation and replay matrix

Scope / trigger: adding or editing a Model Routing catalog entry, dispatching a delivery Run, or
replaying a retained Run. `route_kind` is the optional historical wire field on
`ProviderRouteReference`, `ModelRouteReference`, `ModelRoute`, `ModelSelection`,
`AgentDefinition` and `ModelRouteAttempt`; it uses `codex_cli | responses`. New production
facts must populate it from `ProviderRouteConfig.kind`. CLIProxyAPI changes only the Codex CLI
connection and never creates a third kind.

| Case | Input | Required result |
|---|---|---|
| Good | Same provider/model/effort, distinct `kind`, explicit typed Agent references | Save, select and execute the exact kind; fallback ledger records it |
| Base | Legacy reference/selection without `route_kind`, exactly one matching frozen route | Resolve without rewriting the old fact or its digest |
| Bad | Legacy reference/selection without type, two matching frozen routes | Reject as ambiguous before execution/replay |
| Bad | Existing claim/definition says `codex_cli`, configured route now says `responses` | Reject claim/worker binding; do not silently switch transport |

Tests: `tests/config/test_production.py` asserts typed catalog/reference validation;
`tests/manager/test_team_roster.py` asserts ModelPolicy retains type;
`tests/work_queue/test_route_binding.py` asserts frozen selection and legacy ambiguity;
`tests/agents/test_fallback.py` asserts route-attempt type and replay identity;
`tests/team_view/ui.test.cjs` asserts visible capability and duplicate detection. Wrong: keying
readiness or policy only by `(provider, model, reasoning_effort)`; correct: include `kind` and
require a unique match for every older untyped reference.

#### T043: Safe CLI failure diagnostics

Scope/signatures: `SubprocessCodexCommandRunner.run(...) -> CodexInvocationResult` and
`CodexCliAgentAdapter.run(request) -> AgentResult`. Existing wire schemas and routing remain unchanged.
For nonzero exit/timeout, error.message includes a fixed-text cause category, returncode and SHA-256
of captured stdout/stderr. Raw output, task prose and secrets are never copied into diagnostics.
Cause is a heuristic match using the existing quota/rate/auth markers; an unmatched exit is labeled
UNKNOWN_EXIT rather than asserting provider unavailability. Timeout is labeled TIMEOUT.

Capture is bounded to 1,000,000 characters per stream, retaining equal head/tail portions on overflow.
Hashes identify these captured strings, not an untruncated transcript; truncation is not a substitute
for full provider evidence. TimeoutExpired partial bytes use UTF-8 replacement decoding. No durable
raw transcript or new secret-bearing log is introduced.

| Case | Routing / diagnostics |
|---|---|
| Clean quota/rate/auth exit | Existing typed routing; safe cause/exit/digests added |
| Dirty quota/auth/unknown exit | Non-transient POLICY_VIOLATION; original recognized cause or UNKNOWN_EXIT retained |
| Dirty timeout | Non-transient POLICY_VIOLATION + cause=TIMEOUT; preserve worktree |
| Long output with trailing error | Bounded tail retains the marker for classification |
| Existing historical generic error | Remains unknown; never infer or rewrite its cause |

Good: interrupted work is preserved and the next operator can distinguish known/unknown causes.
Base: same-run replay returns the existing result. Bad: replacing quota-with-dirty by a transient quota
error, deleting work to enable fallback, or asserting old discarded stderr can be recovered from a hash.
Tests: `tests/agents/test_codex_cli.py` covers dirty categories, timeout, no artifact/retry, retained file
and HEAD, secret exclusion, stable replay, bounded tail and timeout byte capture.

Wrong: return only "left changes" and discard the already available process classification.
Correct: retain POLICY_VIOLATION for safety and append a safe diagnostic, without enabling fallback.
Root cause (B/D): failure routing and failure diagnosis were conflated; the dirty guard returned before
classification and small clean-failure fixtures hid the omission. A real-Git dirty quota test caught it.
This repair cannot determine the original round3 exit cause; explicit recovery of interrupted work
and general provider error evidence remain separate work, not permission to resurrect terminal tasks.

#### Deadline-aware Codex finalization

Scope/trigger: applies whenever `AgentRequest.timeout_seconds` is passed to a Codex CLI role. The
subprocess hard limit alone is not an Agent-visible execution plan; `_compile_prompt(request,
messages) -> str` must expose it and `_completion_reserve_seconds(timeout_seconds) -> int` must
derive a deterministic reserve.

Contract: the reserve is `min(300, max(10, timeout // 5), max(0, timeout - 1))`. The compiled prompt
states the exact total and reserve. Coder must prioritize focused required tests, stop scope expansion
before the reserve, and prioritize a complete intended diff plus provisional JSON implementation
report over broader optional validation. Other roles receive the same total/reserve fact while
retaining their own read-only role instruction. This changes no external wire field, sandbox,
permission, timeout, retry, Artifact, verdict, or downstream independence contract.

| Case | Required result |
|---|---|
| timeout 1 / 2 seconds | reserve 0 / 1; always less than total |
| timeout 60 / 1,200 seconds | reserve 12 / 240 |
| Coder timeout 1,800 seconds | prompt states total 1,800 and reserve 300 plus diff/report priority |
| timeout 3,600 seconds | reserve remains capped at 300 |
| remote model ignores budget | existing hard timeout and dirty-worktree guard remain authoritative |

Good: Coder finishes focused required verification, stops expanding scope, and emits the provisional
report within the reserve; the platform-owned finalizer below creates the commit. Base: injected
runner asserts exact prompt text in milliseconds. Bad: ask the sandboxed Agent to write external Git
metadata, remove the hard timeout, commit unvalidated dirty output, or claim the prompt unit test
proves remote-model timing.

Tests: `tests/agents/test_codex_cli.py::test_coder_creates_verified_candidate_in_isolated_worktree`
asserts the real subprocess stdin contract; `test_completion_reserve_is_bounded` covers boundary and
production values. A fresh explicitly approved live recovery is required to validate model behavior;
the test suite never spends live quota by default.

Wrong: keep `timeout_seconds` only in `subprocess.run(timeout=...)` while the Agent sees no deadline.
Correct: preserve that kill switch and also compile exact total/reserve/finalization priority into the
role prompt.

Root cause (B/D/E): the external runner contract and Agent-visible work contract diverged. Fast fake
runners always committed immediately, so tests proved postconditions without proving the model was
told how to finish before the external deadline. A real 1,800-second run changed all authorized areas
and completed a broad pytest subprocess, yet timed out dirty before commit/Artifact. The deterministic
test can prevent prompt regression; only live delivery can test model compliance.

#### Candidate QA reuses provisioned project tooling

Scope/trigger: applies when QA verifies an exact candidate in a detached role worktree and the
registered repository root already contains a project-local `.venv/bin/pytest`. The detached
worktree intentionally excludes ignored virtual environments; that absence alone is not evidence
that the verifier environment is unavailable.

Contract: before invoking QA, the Manager-side Codex adapter resolves the registered Git common
directory and accepts only a real, executable, non-symlink `.venv/bin/pytest`. It injects that fixed
path as `ASE_PROJECT_PYTEST` and names the exact runner in the QA prompt. QA runs that absolute
executable while keeping the current working directory on the exact candidate worktree. The
external environment is read-only tooling: imports, test discovery, Git checks and all verdict
evidence remain bound to the candidate SHA. QA may report `ERROR`/`NOT_TESTED` only after both the
Manager-provisioned runner and permitted repository commands cannot establish a verdict.

| Case | Required result |
|---|---|
| detached worktree has no `.venv`, registered root has pytest | use registered absolute pytest against candidate cwd |
| focused tests pass | evidence binds exact candidate; criteria may PASS |
| focused tests fail due candidate | FAIL, never environment ERROR |
| no project runner and offline cache is incomplete | fixed environment ERROR/NOT_TESTED; candidate retained |

Good: QA reuses the already provisioned interpreter without copying dependencies or modifying the
candidate. Bad: create a second environment through network access, run tests against the registered
root checkout, or classify a candidate failure as infrastructure. Tests:
`tests/agents/test_codex_cli.py::test_qa_semantic_artifact_failure_has_safe_actionable_diagnostics`
locks the Agent-visible runner instruction; live candidate verification proves the end-to-end path.

If project-local tooling is still insufficient, the next architectural step is a typed Manager
environment-preparation step, not network access for QA or a silently accepted `NOT_TESTED` verdict.

## Scenario: per-Agent model routes and Product image input

### 1. Scope / Trigger

Applies when Settings changes a Team member's primary model, a configured provider advertises image
support, or Product receives Requirement screenshots. Agent identity and approval independence do not
change when the model changes.

### 2. Signatures

```python
ProductionConfig.routes_for(role: TeamRole) -> tuple[ProviderRouteConfig, ...]
ProviderRouteConfig.accepts_image_input() -> bool
ConfiguredStructuredClientFactory.for_project(
    repository_root: Path,
    role: TeamRole = TeamRole.PRODUCT,
) -> StructuredModelClient
StructuredModelClient.complete(..., input_images: tuple[Path, ...] = ())
```

### 3. Contracts

- `model_routes` is the enabled route catalog. `agent_model_routes` is the seven-role ordered policy;
  the first route is primary and every following route is an explicitly selected fallback. The
  catalog does not implicitly expand a role policy. Route identity is
  `(provider, model, reasoning_effort, kind, effective_connection_mode)`, so one model may expose
  multiple independently selectable reasoning levels, execution types and CLI transports.
  CLIProxyAPI only supplies the Codex CLI connection; it is not a route kind.
- Product, Designer and Planner resolve their own TeamRole at the structured-client seam. Coder, QA
  and Reviewer preserve the same order in the content-versioned ModelPolicy used by dispatch.
- Settings may materialize an explicit seven-role policy from a legacy empty policy by selecting only
  the first enabled route as each role's primary. It must not copy every enabled catalog route into
  fallbacks, and it may not mint new Agent IDs. Operators may add, remove and reorder zero or more
  fallbacks per Agent. Manager's route is persisted/displayed even though current Manager decisions
  use deterministic Skills and do not invoke a model.
- The read-only runtime Status projection resolves the same seven role policies through
  `ProductionConfig.routes_for(role)` and joins each exact route five-tuple with catalog readiness. It
  preserves primary/fallback order and labels whether the policy is explicit or inherited; it does
  not claim that any route is currently executing.
- Codex CLI receives one `--image <verified-path>` pair per Product screenshot. Responses receives
  standard `input_image` data URLs only when the operator explicitly marks that route image-capable.

### 4. Validation & Error Matrix

| Case | Required result |
|---|---|
| Legacy config without `agent_model_routes` | every role inherits enabled catalog order |
| Settings materializes a legacy policy | first enabled route becomes primary; no fallback is inferred |
| Explicit policy missing a role or containing duplicate/disabled/unknown route | reject config |
| Enabled catalog route is not selected by one Agent | route remains available but never runs for that Agent |
| Legacy policy reference omits effort and matches multiple enabled routes | reject as ambiguous |
| Same provider/model with different efforts | preserve both routes and the Agent's exact selection |
| Status projects explicit or inherited policy | seven ordered role records with exact effort and matching readiness |
| Product route 1 lacks image support, route 2 supports it | skip route 1; invoke route 2 with images |
| No configured route supports images | typed non-transient failure; do not omit screenshots |
| Coder primary differs from QA primary | each dispatch/model attempt records its role-specific route |
| Provider/model/reasoning edited in Settings | update matching policy references before validation |

### 5. Good / Base / Bad Cases

- Good: Product uses a vision-capable model while Coder and Reviewer use different preferred brains;
  quota fallback stays within each Agent's explicitly selected and ordered list.
- Base: one enabled Codex route serves all seven members with primary-only policies.
- Bad: encode the model into Agent identity, silently send a screenshot to a text-only endpoint, or
  copy every enabled catalog route into fallbacks after an explicit role policy exists.

### 6. Tests Required

- `tests/config/test_production.py`: full role coverage, enabled references and independent ordering.
- `tests/manager/test_team_roster.py`: delivery role order survives ModelPolicy compilation.
- `tests/agents/test_structured_models.py`: Codex `--image` binding and unsupported-route skipping.
- `tests/team_view/ui.test.cjs`: seven role selectors, distinct Product/Coder primary values, no
  inferred fallback after catalog enablement, and explicit fallback add/remove/reorder in the saved
  config.

### 7. Wrong vs Correct

```python
# Wrong: every role ignores its configured policy.
routes = config.enabled_routes()

# Correct: role resolution happens before constructing provider adapters.
routes = config.routes_for(role)
```

```javascript
// Wrong: the catalog is silently expanded into every Agent policy.
policy.routes = enabledRoutes.map(modelRouteReference)

// Correct: keep one required primary plus only operator-selected fallbacks.
policy.routes = [selectedPrimary, ...explicitFallbacks]
```

#### Platform-owned Coder candidate finalization

##### 1. Scope / Trigger

`CodexCliAgentAdapter.run(request) -> AgentResult` uses this path only after a Coder provider exits
successfully with a schema-valid provisional implementation report, unchanged HEAD, and intended
worktree changes. A linked worktree stores its index and refs under the target repository's external
`.git/worktrees/...`; the Codex `workspace-write` sandbox must not receive write access to that tree.

##### 2. Signatures

```python
CodexCliAgentAdapter._finalize_coder_candidate(
    request: AgentRequest,
    initial_head: str,
    artifact: Artifact,
) -> Artifact

_worktree_changed_paths(root: Path) -> tuple[str, ...]
```

##### 3. Contracts

- The provisional report uses the exact request source revision for both `source_revision` and
  `content.commit_sha`; it is never persisted or sent downstream as a completed Artifact.
- Before Git mutation, the platform requires unchanged HEAD, an exact reported/observed path set,
  UTF-8 NUL-delimited paths, and `WorkspacePolicy.authorize_write` for every path.
- The platform stages only that validated set. Commit execution disables repository hooks, fsmonitor,
  signing and interactive identity lookup, and uses a fixed platform author/message.
- After commit, the platform replaces only the two provisional revision fields with exact HEAD and
  reruns the existing clean-worktree, diff inventory, Artifact identity and path-policy guards.
- A Coder that already produced a clean valid commit remains supported. Provider failure/timeout,
  dirty QA/Reviewer, changed HEAD plus dirty files, invalid report or unauthorized diff is never
  finalized. Failure preserves the worktree and cannot enter QA.

##### 4. Validation & Error Matrix

| State | Result |
|---|---|
| success + unchanged HEAD + exact authorized dirty diff + provisional revision | one platform-created candidate; final report bound to exact SHA |
| report path missing/extra vs observed diff | non-transient policy failure; no commit |
| unauthorized, denied, non-UTF-8 or `.git`-resolving path | non-transient policy failure; no commit |
| provisional revision differs from request source | invalid output; no commit |
| provider nonzero/timeout with changes | existing policy failure and preserved dirty work; no finalizer |
| Agent-created clean commit | existing candidate validation; no second commit |
| changed HEAD plus dirty work | policy failure; no additional commit |
| controlled add/commit failure or concurrent drift | fail closed; preserve resulting worktree/index state |

##### 5. Good / Base / Bad Cases

- **Good**: the Agent edits only approved files and returns an exact draft; the platform creates one
  candidate and QA/Reviewer independently inspect that SHA.
- **Base**: an injected runner reproduces the sandbox-external Git condition without a model call and
  the adapter returns the same final `AgentResult` contract as an Agent-created commit.
- **Bad**: grant the Agent the target repository `.git`, run arbitrary shell from model text, stage
  paths absent from the report, or commit after provider timeout/failure.

##### 6. Tests Required

`tests/agents/test_codex_cli.py` must cover successful finalization, unauthorized path, inventory
mismatch, provisional revision mismatch, the legacy clean-commit path, dirty provider failure and
timeout. Production recovery tests must assert the same AgentResult/candidate contract and the next
explicitly approved live recovery is the real macOS proof. Default tests never consume model quota.

##### 7. Wrong vs Correct

Wrong: add `--add-dir <target-repository>/.git` to Codex or commit any dirty tree after process exit.
Correct: model-success draft → exact diff/report/policy validation → fixed platform Git commit → exact
SHA binding → existing artifact/candidate validation. This keeps Git authority in a deterministic
module while the Agent owns implementation decisions.

### 3.4 Worktree and delivery

Production preparation uses `ManagerSkillService(versioned_preparations=True)` and
`RuntimeWorkspaceBinder(versioned=True)`. A stable Repository ID is not a single immutable baseline:
new profiles are stored at `profile/repository-profile-<profile_sha256>.json`, bindings at
`policy/runtime-workspace-binding-<binding_sha256>.json`, and preparation records under
`policy/preparations-<profile_sha256>/`. All stay inside the same Project-owned Repository sidecar.
Matching legacy fixed-name records are replayed with their original timestamps; other legacy
records remain untouched. New snapshots are exclusively published, never replace concurrent winners.
`load_repository_profile(sidecar, profile_sha256)` must read the requested hash, not a mutable latest
pointer. A legacy fallback must pass that exact hash; corrupt/symlink snapshots never fall back.
Low-level composition remains legacy by default. New production intakes may prepare newer facts,
but existing delivery/product/stage gates still compare their exact preparation and source revision;
this does not authorize rebasing old approval or QA/Review evidence in place.

- dispatch 后才可 materialize Task；Task repository、Artifact/Context/Evidence roots、Agent definitions
  和 dispatch bundle 必须来自同一 Repository sidecar 与 exact Project/revision lineage。
- 目标项目必须是真实目录、Git root、clean working tree 且 HEAD 为 full commit。Task `allowed_paths`
  来自 TechnicalDesign affected paths，commands 来自确定性 RepositoryProfile build-system allowlist。
- Coder worktree 位于 `<platform_root>/worktrees/<repository-id>/<task-id>/coder-attempt-01` 并使用
  `ai/<task-id>/attempt-1` branch；QA、Reviewer 在 exact candidate SHA 的不同 detached worktree。
- Coder 必须留下完整 intended diff 和 provisional report；平台 finalizer 形成 clean candidate commit，
  且 changed paths 不越权。QA/Reviewer 不得改变 HEAD 或工作树。
  clean worktree 可以关闭，dirty/漂移现场必须保留，禁止 force reset/delete。
- delivery 完成只产生 `DONE + candidate_revision`；不 merge、不 push 目标保护分支、不 deploy。
- production v0.1 的 Task attempt budget 是 3。Coder 可在预算内用 `coder-progress` 明确请求下一次
  Run；每次都经过 `CONTINUE_REQUIRED → QUEUED → IMPLEMENTING` 并持久化 attempt。预算耗尽或
  checkpoint/worktree 漂移时生成 BLOCKED 证据，不得无限重试或把草稿交给 QA。
- production role 执行仍有硬上限，但按职责分配：Coder 1,800 秒，QA 与 Reviewer 各 1,200 秒，
  deterministic Orchestrator 60 秒。native 与 recovery delivery 都必须通过同一
  `_agent_definitions` seam 获得这些预算；未知 delivery role fail closed。超时仍无 Artifact，dirty
  worktree 仍保留且不得自动重试。未来的风险自适应或 operator 配置不能静默改变已批准 Run。
- T042 production context 使用显式 64,000 input / 4,000 output reserve；完整规范索引和批准文档
  不截断，语言 marker 清单仅作 context-only 投影。低层 Runtime 默认仍为 12,000 input。
  签名、错误矩阵与回归点见 `python-runtime.md` 的 T042 小节；旧 manifest/审批不改写。
- Production TeamHost 每次按 Project 读取 active Team/Project Spec 快照。Team Spec 进入
  `PLATFORM_ENGINEERING` rules；Project Spec 由 `ProductionProjectRuleProvider` 按 Repository
  过滤并提供 exact URI/hash provenance。缓存身份同时包含知识和 Spec 快照：任何一方变化只重建
  受影响 Project runtime，不要求进程重启，也不允许已 prepare 的交付静默采用新版本。联合
  Requirement 的 derived delivery 显式重放该 Requirement 已封存的 preparation/spec/context；新版本
  只进入之后创建的 Requirement。
- Joint Requirement 的 child backend 可以冻结在 intake 时的 preparation/source revision，用于继续验证
  原 Product/Design/Plan 和失败 Coder lineage；但 `TeamHost._resume_controller(...)` 装配的
  `NativeRecoveryEntry` 与 `CandidateVerificationEntry` 必须使用当前 Project runtime backend。恢复计划的
  `target_preparation_sha256`、RepositoryProfile `source_revision` 与 `target_base_revision` 必须来自同一
  当前 clean HEAD。禁止用 frozen child backend 产生 target preparation 后再把当前 HEAD 写入计划；否则
  主分支正常前进后，所有旧 Requirement 都会稳定失败为 `target profile mismatch`。

## 4. Validation & Error Matrix

| 输入/故障 | 检测点 | 结果 |
|---|---|---|
| Web Console 配置文件不存在 | console composition | 使用 `ProductionConfig.default()` 启动设置/状态面；不创建配置文件；交付返回 `SETUP_REQUIRED` |
| 已有配置未知字段、损坏、相对/控制字符/含 `..` 的 `platform_root` | ProductionConfig/Schema | `ProductionConfigError`/ValidationError，不回退默认值、不连接模型 |
| DSN env 缺失、MySQL 停止/认证失败 | Host/MySqlTaskRepository | CLI 脱敏失败并 exit 2；Web Console 使用 setup runtime，设置/状态仍可访问，交付不可用 |
| duplicate Task / unknown Task | MySQL repository | `TaskAlreadyExists` / `TaskNotFound` |
| stale event status/revision 或 changed replay | locked append transaction | rollback；`InvalidStateEvent`/`EventIdempotencyConflict` |
| stale workforce snapshot / capacity/Lease 冲突 | MySQL dispatch lock | rollback；不发布 partial dispatch |
| Codex 未登录、HTTP auth 失败 | provider adapter | non-transient failure，无 fallback、无 Artifact |
| HTTP 429/quota/timeout/5xx | adapter + fallback policy | append attempt evidence；最多尝试下一 enabled route |
| provider JSON/Artifact 不合法 | Pydantic/artifact guard | `INVALID_OUTPUT`，不 fallback、不生成 verdict |
| Product 缺关键决策 | Product Agent | `WAITING_PRODUCT_REPLY`，要求 exact checkpoint reply |
| ProductSpec 未获 exact human approval | Product gate | `WAITING_PRODUCT_APPROVAL`，不运行 Designer |
| 项目规则冲突 | SpecCompiler | `WAITING_HUMAN`，不静默选边 |
| Team/Project knowledge selection 在新需求前变化 | TeamHost runtime lookup | 重建受影响 Project runtime，无需进程重启 |
| standalone 已 prepare 交付所绑定知识发生变化 | preparation guard | 安全停止并要求重新 prepare；不沿用旧批准 |
| Requirement 创建后知识/Spec 或主 checkout 更新 | frozen preparation + retained baseline | 旧 Requirement 继续使用封存版本；新 Requirement 使用新版本 |
| Team Spec activation 变化 | TeamHost runtime lookup | 各 Project 下一次访问重建 runtime；无进程重启 |
| Project A Spec activation 变化 | Project-scoped cache identity | 只重建 Project A；Project B 保持原 runtime |
| standalone 已 prepare 交付所绑定 Spec 发生变化 | preparation guard | 安全停止并要求重新 prepare；不沿用旧批准 |
| 新 intake 的 target project dirty/not Git/HEAD 在准备期间漂移 | delivery precondition | stable failure + preserved project/worktree |
| 已有 Requirement 的配置 checkout HEAD 前进或 dirty | Requirement-owned baseline | 不影响旧交付；Task.base_ref 仍为封存 revision |
| frozen Requirement child 阻塞后，配置 checkout HEAD 前进 | recovery composition | source/entry 保留旧基线；recovery/verification target 使用当前 Project backend 并生成同一 HEAD 的 profile、preparation 与 plan |
| Requirement baseline worktree/commit 漂移 | reconciliation | typed source drift；保留现场，不 fallback 到配置 checkout |
| Coder provisional report/diff 不匹配、越权路径或 finalization 后 dirty | Codex Git guard | policy/invalid-output failure；不进入 QA |
| Coder 返回合法未完成 checkpoint | artifact/worktree/state guards | 保存 progress，重新排队下一次 Coder；不进入 QA |
| Coder continuation 预算耗尽或 checkpoint 漂移 | retry/runtime admission | BLOCKED，保留 progress 和 worktree evidence |
| production role 超过其 1,800/1,200 秒预算 | subprocess/adapter timeout guard | 无 Artifact；dirty 现场保留，Task BLOCKED |
| QA/Reviewer candidate 不同或修改 worktree | dispatch/worktree/artifact guard | fail closed；不进入 DONE |
| `status`/`resume` durable facts 损坏 | checkpoint reconciliation | corruption/drift failure；不覆盖原记录 |

错误消息只能包含稳定分类和安全摘要；不得输出 DSN、Authorization header、API key、provider response
body 或目标项目中的 secret。

## 5. Good / Base / Bad Cases

- **Good**：macOS/Linux 首次运行 Web Console 时展示稳定默认配置，缺少 MySQL 仍可填写 DSN、测试
  连接并查看状态；保存后由服务脚本加载 `runtime.env` 并重启为 delivery runtime。配置解析本身仍
  不创建目录；显式 setup writer 才初始化 workspace。真实临时 Git 项目 + MySQL + scripted structured/delivery providers 完成
  prepare→Product approval→Design→Plan→dispatch→Coder diff/report→平台 candidate finalization→独立 QA/Review→DONE；main checkout 和
  target files 不变，candidate commit 可由 `git show` 复核。
- **Base**：显式安全绝对路径或 `~/custom-ase` 覆盖默认值。缺少真实额度时，contract/E2E 使用注入的 deterministic providers；Production Host、MySQL、
  dispatch、worktree 和 typed artifact 仍走真实实现。只有显式 live smoke 才消费 GPT-5.5。
- **Bad**：接受 `/tmp/root/../escape` 或已有配置失败后静默改用默认值；在每个项目复制 AgentProfile；把 DSN/API key 写入 JSON、API response、日志或非 allowlist 环境变量；Planner 直接提交分配；让同一 Agent
  同时当 Coder 和 Reviewer；在 main checkout 写代码；auth/invalid output 后静默换模型；自动 merge。
- **Role-budget Good**：复杂 Coder 在 1,800 秒硬上限内完成 intended diff/report，平台形成候选提交与 Artifact，随后由各自拥有
  1,200 秒上限的独立 QA、Reviewer 验证。
- **Role-budget Base**：离线 scripted runner 只验证 `AgentDefinition → AgentRequest → subprocess`
  传递的 exact timeout，不等待 wall clock，也不调用 provider。
- **Role-budget Bad**：所有 delivery role 共享 600 秒，导致代码已改完但验证/提交被杀；或把上限改为
  无界、超时后把 dirty worktree 当候选继续 QA。
- **Continuation Good**：Coder 在收尾预算内输出 progress，平台保留 exact dirty inventory；下一次
  Run 消费该 checkpoint，完成后由 CandidateCommit Skill 创建候选。
- **Roster Good**：Host 初始化时持久化七个长期 AgentProfile；需求 dispatch 只引用它们，不复制身份。

## 6. Tests Required

- T040: `tests/e2e/test_project_revision_preparation.py` uses real Git/MySQL to prepare two baselines,
  preserve all previous JSON bytes, reopen/replay the new request, and reject old request drift
  before any model call. `test_preparation_versions.py` covers legacy replay plus Product gate;
  `test_binding_versions.py` covers old/new bindings, timestamp replay, corruption and symlinks.
  Good: new intake/new snapshot with stable project identity. Bad: overwrite fixed profile or allow
  an old request to adopt new source facts. RuntimeWorkspaceError is a stable CLI error, not traceback.

- `tests/config/test_production.py`：配置文件/env、首次运行默认值零写入、route 条件、duplicate route、secret 不落 JSON；
- platform-root 配置测试必须覆盖省略值的 cwd 独立性、macOS/Linux 默认、显式绝对/`~/` 优先、
  绝对与 home-relative traversal 拒绝、模块导入/只读零创建，以及显式 writer 创建边界；
- `tests/contracts/test_json_schema_contracts.py`：ProductionConfig positive/negative canonical schema；
- `tests/store/test_mysql_repository.py`：与 SQLite 可观察行为一致、atomic append、replay/conflict、rollback、
  reopen；必须通过 `ASE_TEST_MYSQL_DSN` 显式 opt-in；所有 `mysql` 标记测试在 fixture 执行前必须校验
  database 名称属于 `test_*`、`*_test` 或 `*_tests` 专用测试库，非测试库 fail closed，错误不得回显
  DSN 凭据；
- `tests/manager/test_mysql_dispatch_authority.py`：snapshot/commit 幂等、stale fence、reservation、
  corruption、跨连接恢复；三种 Task 终态释放容量而不删除分配事实，非终态仍占容量；
- `tests/e2e/test_joint_delivery.py`：一个 Host 连续完成五次双仓需求（10 个原生 Task），超过
  Agent 的 8 个并行槽位仍可串行交付，不能通过增加 capacity 或等待 15 分钟掩盖 Lease 泄漏；
- `tests/agents/test_codex_cli.py`、`test_responses.py`、`test_fallback.py`、
  `test_openai_compatible.py`：request/response、Git、tool、error mapping、fallback allowlist 和 attempt replay；
- `tests/manager/test_production_agents.py`：Product/Designer/Planner typed draft 和 exact lineage；
- `tests/manager/test_production_backend.py`：真实 MySQL + 临时 Git + scripted team 到 DONE，独立
  verifier worktrees 检查 exact candidate，主 checkout 零污染，并断言三个 delivery role 的生产预算；
- `tests/manager/test_team_host.py`：active Team Spec 变化使所有 Project cache 失效，Project Spec
  变化只使所属 Project cache 失效；新 baseline 绑定 exact sidecar provenance；
- `tests/recovery/test_execution.py`：offline Codex runner 直接断言 recovery 将相同 role timeout 传入
  subprocess seam；
- `scripts/smoke-live-gpt55.sh`：只有 `ASE_RUN_LIVE_TESTS=1` 才运行，不进默认 CI，不自动 merge；
- 合并门禁：full pytest、Ruff check/format、strict mypy、offline build、`git diff --check`。

## 7. Wrong vs Correct

### Platform root normalization

#### Wrong

```python
# `resolve()` hides lexical traversal and configuration loading performs a write.
platform_root = Path(raw_value).expanduser().resolve()
platform_root.mkdir(parents=True, exist_ok=True)
```

#### Correct

```python
# Validation rejects every lexical `..` component. Loading stays pure; an explicit
# workspace writer owns directory creation later.
config = ProductionConfig.model_validate({"platform_root": raw_value})
TeamWorkspace.initialize(config.platform_root, team_id)
```

`/tmp/platform/../escape` and `~/platform/../escape` are invalid even if filesystem normalization
would produce an absolute path. `ProductionConfig` parsing and read-only projections never create
`~/.ase`; only an explicit workspace writer may do so.

### Production composition

### Wrong

```python
# Per-command manual composition, plaintext secret, and fake fallback.
config = {"mysql_dsn": "mysql://user:password@host/db"}
configure_project_entry(lambda: fake_team(repository_root))
result = planner.choose_and_commit_agent_and_model()
```

### Correct

```python
config = ProductionConfig.from_environment()
host = TeamHost(config=config, environment=os.environ)
entry = host.project_entry()
result = entry.start(
    StartProjectDelivery(repository_root=absolute_git_root, requirement=requirement)
)
```

前者让 secret、fake 执行和调度权限穿透用户入口；后者由唯一 production composition root 加载环境
secret、MySQL、Team-owned team 和 policy-bound adapters，Planner 仍只能 preview，Project
Manager 在 MySQL authority 下重新校验后 commit dispatch。

### Role timeout budget

#### Wrong

```python
AgentDefinition(role=phase.role, timeout_seconds=600, ...)
```

#### Correct

```python
AgentDefinition(
    role=phase.role,
    timeout_seconds=_delivery_timeout_seconds(phase.role),
    ...,
)
```

固定职责预算同时解决两个风险：复杂实现不会被过早杀死，每个真实模型调用又仍受领域层
`1..3600` 秒边界约束。新增角色必须先获得显式预算和测试；不得回退到共享默认值。

Root cause (D/E): fast scripted fixtures hid the implicit assumption that a shared 600-second
whole-role budget was sufficient. A real Coder reached every authorized file but was killed before
verification, commit, and Artifact sealing; the full repository test suite alone consumes most of
that budget. Prevention is three-layered: a pure role contract test, production adapter assertions,
and recovery's offline command-runner assertion. Model latency must not be tested with wall-clock
sleeps, and a future configurable/adaptive policy must preserve a bounded, approval-visible value.

## Explicit output lineage and failure read-back (2026-09-09)

Scope: delivery Agent requests/prompts and errors returned after runtime execution.
`AgentRequest.expected_parent_artifact_ids: tuple[ArtifactId, ...] | None = None` distinguishes
context inputs from direct parents. None preserves historical request serialization; orchestrators
always supply the exact existing `expected_parents`, including empty for plan. Non-null parents
must be unique and a subset of inputs. Both RequestPromptBuilder and ContextPromptBuilder include
`output_contract.parent_artifact_ids`; Codex compiles these same messages. No Artifact schema or
parent policy changes: QA parent is implementation only, Reviewer parent is QA only. Coder retry
parents remain the exact runtime-selected set. Existing persisted requests are not rewritten.

Wrong returned parents are non-transient `AgentRunFailed(INVALID_OUTPUT)` at the orchestration
guard, not PLATFORM_BUG. The invalid report is not sealed; no Reviewer or automatic model fallback
is allowed. Provider-level VALID evaluation records mean adapter validation, not final acceptance.
The facade labels INVALID_OUTPUT as INVALID_AGENT_OUTPUT rather than retry-budget exhaustion.

`DeliveryBackendFailure(..., snapshot: DeliveryFailureSnapshot | None = None)` may carry typed
Task, task_revision and candidate_revision read after a runtime exception. Production run_delivery
reads the exact Task and events, checks revision/count/status and rechecks for concurrent changes.
Candidate comes only from a persisted candidate_ready event, never model prose. The facade checks
task identity/repository/revision, then appends a BLOCKED checkpoint with actual Task status, revision,
candidate and incremented delivery attempt; timestamp is at least Task.updated_at. It never rewrites
Task state or previous checkpoints. Earlier-stage failures without a snapshot retain existing behavior.

| Case | Required result |
|---|---|
| QA inputs contain plan + implementation | Prompt parents contain implementation only |
| QA copies all inputs as parents | INVALID_OUTPUT/BLOCKED; no accepted QA or Reviewer |
| Runtime exception after progress | Read-back status/revision/candidate, not stale NEW |
| Snapshot wrong task/root, decreasing revision, concurrent drift | Reject, no fabricated parent facts |
| Historical terminal delivery | Unchanged; this patch does not resurrect or auto-replay it |

Good: explicit output contract plus immutable failure facts. Base: valid first delivery unchanged.
Bad: silently repair QA parent IDs, accept a schema-valid report as final approval, or reset FAILED.
Tests: `test_output_parent_contract.py` exercises the runtime and real failure pattern;
`test_openai_compatible.py` asserts the production context prompt; `test_delivery_failure_snapshot.py`
checks failure projection, timestamp, candidate preservation, wrong identity and reopen.
Wrong: use all input_artifact_ids as direct parents and preserve pre-run NEW on exception.
Correct: transmit exact parents, reject invalid output, and project checked durable runtime facts.
Root cause (B/D/E): runtime kept lineage expectations private while exposing a larger context set;
fake adapters already knew the expected chain. Exception conversion discarded post-run progress.
Prevention: explicit contract tests at the adapter seam and facade failure tests, not weaker guards.
Recovery of existing terminal Tasks remains a separate exact-candidate authorized operation.

## Structured Agent output semantics and safe diagnostics (2026-09-10)

### 1. Scope / Trigger

This contract applies when Codex CLI exits successfully and writes structured Coder, QA, or Reviewer
output. Provider JSON Schema admission is necessary but insufficient because Pydantic model validators
also enforce evidence references, verdict coherence, role policy, and run identity.

### 2. Signatures

```python
CodexCliAgentAdapter.run(request: AgentRequest) -> AgentResult
_compile_prompt(request: AgentRequest, messages: Sequence[object]) -> str
_validation_location(error: ValidationError) -> tuple[str | None, str | None]
```

No public wire field changes. A rejected output remains `FAILED + INVALID_OUTPUT`, has no Artifact,
does not enter Reviewer/DONE, and is not eligible for provider fallback.

### 3. Contracts

- The compiled prompt contains exact task, source revision, context manifest, direct parent set,
  producer role and producer run bindings from `AgentRequest`. Context inputs are not implicitly
  promoted to parents.
- Every content-level evidence reference must resolve to one unique record in the top-level
  `evidence` array. QA `PASS`, Reviewer `APPROVE`, and Reviewer `REJECT` must obey the domain verdict
  validators; the prompt states those conditions explicitly.
- Provider output uses provisional integrity (`sha256=64 zeroes`, `validated=false`,
  `validated_at=null`). Final validation and sealing remain platform-owned.
- Invalid output diagnostics expose only a fixed cause, SHA-256 and UTF-8 byte count. Pydantic errors
  may add a sanitized validation type and location path; raw model output, validation messages,
  task prose, evidence descriptions and secrets must never be copied into `AgentFailure`.
- Cause values are `JSON_DECODE`, `ARTIFACT_VALIDATION`, `ROLE_CONTRACT`, `GIT_CONTRACT`, or
  `RUN_IDENTITY`. A historical generic error cannot be retroactively classified after its ephemeral
  output file has been deleted.

### 4. Validation & Error Matrix

| Output state | Result / safe diagnostic |
|---|---|
| malformed JSON | `INVALID_OUTPUT; cause=JSON_DECODE` + output digest/bytes |
| Schema-valid JSON with unknown evidence reference or incoherent verdict | `INVALID_OUTPUT; cause=ARTIFACT_VALIDATION` + sanitized type/path |
| valid Artifact kind outside the assigned role | `INVALID_OUTPUT; cause=ROLE_CONTRACT; path=kind` |
| Coder report does not bind the resulting Git candidate | `INVALID_OUTPUT; cause=GIT_CONTRACT` |
| Artifact does not bind Task/run/context/source identity | `INVALID_OUTPUT; cause=RUN_IDENTITY` |
| QA/Reviewer mutates its read-only worktree | existing `POLICY_VIOLATION`; never relabel as output failure |

### 5. Good / Base / Bad Cases

- **Good**: QA cites complete evidence, returns a coherent verdict and exact envelope bindings; the
  typed Artifact proceeds to the existing lineage guard and store seal.
- **Base**: a deterministic runner writes Schema-valid but semantically invalid QA JSON; the adapter
  returns the exact safe cause/path/digest without retaining or disclosing the payload.
- **Bad**: treat structured-output schema success as domain success, leak Pydantic messages or raw
  output into logs, silently repair parents/verdict/evidence, or retry the consumed invocation.

### 6. Tests Required

`tests/agents/test_codex_cli.py` must exercise the public adapter seam with a real temporary Git
repository and injected successful process runner. It must prove the semantic-invalid QA report is
`INVALID_OUTPUT`, the diagnostic is actionable and secret-free, the digest binds the exact discarded
payload, and the prompt contains the envelope/evidence/verdict rules. Existing Codex adapter and
provider contract tests remain required. The next live attempt must use a fresh approved verification
plan because the failed plan is at-most-once.

### 7. Wrong vs Correct

#### Wrong

```python
payload = json.loads(raw_output)
artifact = validate_artifact_payload(payload)  # every failure becomes one generic sentence
```

#### Correct

```python
try:
    artifact = validate_artifact_payload(payload)
except ValidationError as error:
    validation_type, path = _validation_location(error)
    raise _CodexOutputContractError(
        cause="ARTIFACT_VALIDATION",
        raw_output=raw_output,
        validation_type=validation_type,
        path=path,
    ) from error
```

Root cause category is B/D/E: strict JSON Schema and domain validation are two different layers, but
the model prompt described only the former and the adapter erased the latter's failure stage. Fast
positive fixtures hid the semantic gap; ephemeral output deletion then made live diagnosis
irreversible. Prevention combines an Agent-visible semantic contract, a negative adapter-seam test,
stable secret-free diagnostics, and explicit fresh-plan recovery rather than silent replay.

## Scenario: legacy Project dispatch authority upgrade

### 1. Scope / Trigger

This contract applies when `MySqlDispatchAuthority` opens a database created before dispatch
identity changed from the old code-directory `project_id` to the current Project-owned
`repository_id`. It also governs the browser result of retrying a pre-Task dispatch interruption.

### 2. Signatures

```python
MySqlDispatchAuthority.__init__(dsn, *, request_revisions, planner_records)
_ensure_current_dispatch_tables(cursor) -> None
UnifiedProjectEntryService.retry_interrupted_stage(command) -> ProjectDeliveryResult
DeliveryResumeController.resume(command) -> DeliveryResumeResult
```

Current and archived database shapes are exact:

```text
dispatch_workforce_snapshots(repository_id, task_id, payload_json, snapshot_sha256)
dispatch_commits(id, repository_id, task_id, payload_json, dispatch_sha256)
verification_reservations(plan_sha256, payload_json, completion_sha256)

dispatch_workforce_snapshots_legacy_project_v01(project_id, ...)
dispatch_commits_legacy_project_v01(id, project_id, ...)
```

### 3. Contracts

- Initialization reads `information_schema.COLUMNS` before using the dispatch tables. A current
  exact schema and a fresh database are idempotent no-ops apart from `CREATE TABLE IF NOT EXISTS`.
- The identity-bearing legacy snapshot/commit pair must be present as one exact set. One atomic MySQL
  `RENAME TABLE` preserves that pair under the fixed `_legacy_project_v01` names; new empty current
  tables are then created. Legacy JSON and digests remain byte-for-byte historical facts and are not
  relabelled or decoded as Repository records.
- `verification_reservations` never carried Project/Repository identity. It may be absent on older
  installations or already have the current exact schema; it is created or retained, never renamed
  with the identity migration. Any other verification schema fails closed.
- A restart between rename and create is recoverable: a complete two-table archive plus absent current
  identity tables creates the current set. Partial archives, mixed Project/Repository columns,
  unexpected columns, or simultaneous legacy active and archive sets fail closed as
  `DispatchCommitCorruption`.
- MySQL connection/transaction/commit failures use `DispatchStoreUnavailable`, which the production
  backend exposes as retryable `RESOURCE_UNAVAILABLE`; structural/schema drift remains non-transient.
- Existing pre-upgrade checkpoints that recorded the exact old pre-Task DISPATCHING MySQL transaction
  or commit summary as `CHECKPOINT_DRIFT` may re-enter that stage. Other `CHECKPOINT_DRIFT` failures
  remain ineligible for automatic retry.
- If a continue Operation finishes but its returned checkpoint is still BLOCKED/FAILED, the public
  next action uses its safe `failure_summary`, not the opaque `REQUEST_HUMAN` enum.

### 4. Validation & Error Matrix

| Stored state / failure | Required result |
|---|---|
| No dispatch tables | create the three current tables |
| Exact current tables, with or without a complete archive | idempotent reopen |
| Exact legacy snapshot/commit pair, verification absent/current, no archive | atomically archive the identity pair; create/retain current verification table |
| Complete archive and no current tables after interrupted startup | create current set; preserve archive |
| Verification table has unexpected columns | `DispatchCommitCorruption`; do not rename or reinterpret it |
| Mixed columns, partial archive, or unexpected archive shape | `DispatchCommitCorruption`; do not guess or rewrite facts |
| MySQL temporarily unavailable during dispatch | BLOCKED `RESOURCE_UNAVAILABLE`; one explicit continue may retry |
| Exact old pre-Task MySQL `CHECKPOINT_DRIFT` summary | bounded compatibility retry of DISPATCHING |
| Any other `CHECKPOINT_DRIFT` | remain blocked for explicit human diagnosis |

### 5. Good / Base / Bad Cases

- **Good**: 18 old Project-based commits are retained in the archive; a blocked current Repository
  Requirement creates one new snapshot/commit and advances to Coder implementation.
- **Base**: a fresh database or already upgraded database opens repeatedly without renaming tables.
- **Bad**: rename only the SQL column, rewrite `project_id` JSON to `repository_id`, or recompute old
  digests. The old ID value names a different domain object and this would forge audit history.

### 6. Tests Required

- `tests/manager/test_mysql_dispatch_schema.py`: fresh/current idempotence, exact two-table identity
  archive with verification present or absent, rename-before-create ordering, mixed schema rejection
  and incomplete archive rejection.
- `tests/manager/test_production_backend.py`: unavailable dispatch storage maps to
  `RESOURCE_UNAVAILABLE`, not `CHECKPOINT_DRIFT`.
- `tests/e2e/test_unified_project_entry.py`: only the exact legacy pre-Task MySQL failure can retry.
- Manual production check: after restart, assert the six table names/column sets and row preservation,
  then continue the real blocked Requirement and observe its Repository Task enter implementation.

### 7. Wrong vs Correct

#### Wrong

```sql
ALTER TABLE dispatch_commits CHANGE project_id repository_id VARCHAR(128);
UPDATE dispatch_commits SET payload_json = JSON_REPLACE(...);
```

#### Correct

```sql
RENAME TABLE
  dispatch_commits TO dispatch_commits_legacy_project_v01,
  dispatch_workforce_snapshots TO dispatch_workforce_snapshots_legacy_project_v01;
-- Retain/create verification_reservations independently; it has no Project identity.
-- Create clean Repository-identity tables; retain old hash-bound allocation facts unchanged.
```

Bug analysis: this was primarily **C — change propagation failure**, reinforced by **D — test
coverage gap** and **E — implicit assumption**. The Team/Project/Requirement refactor changed domain
models and queries while `CREATE TABLE IF NOT EXISTS` silently retained the old schema. The first
surface fix made the error retryable, but could not make the incompatible store usable. Prevention is
exact startup schema inspection, lossless archive migration, a negative migration test, typed
transient failure classification, and a browser assertion that a completed-but-blocked command is
never rendered as no response.

## Scenario: MySQL integration-test database isolation

### 1. Scope / Trigger

Apply whenever pytest code reads `ASE_TEST_MYSQL_DSN`, especially fixtures that reset shared dispatch,
verification or work-queue tables. A test-prefixed environment variable is not proof that its value
points to disposable storage.

### 2. Signatures

```python
require_isolated_mysql_test_database(dsn: str) -> str
reset_mysql_test_facts(dsn: str) -> None
pytest_runtest_setup(item: pytest.Item) -> None
isolated_mysql_facts(request: pytest.FixtureRequest) -> Iterator[None]
```

Implementation locations are `tests/mysql_safety.py` and the repository-wide `tests/conftest.py`.
Dispatch and queue fixtures use the same autouse boundary as production-host, recovery and reader
tests; they must not implement incomplete module-local cleanup.

### 3. Contracts

- Every test marked `mysql` must pass the repository-wide guard before pytest constructs any fixture
  or opens a MySQL connection. `reset_mysql_test_facts` repeats the guard before opening its connection
  as defense in depth.
- An absent `ASE_TEST_MYSQL_DSN` retains the existing opt-in behavior: the individual fixture skips
  the integration test.
- A configured DSN is accepted only when its decoded database name is a safe identifier matching
  `test_*`, `*_test` or `*_tests`. The database naming rule is an explicit disposable-storage fence.
- Rejection aborts the test session before SQL. Its message may include the safe database name but
  must never include the DSN, user name, password, host, query or control characters.
- Broad fixture cleanup remains permitted only behind this guard. Production runtime configuration
  uses `ASE_MYSQL_DSN` and must never be copied into `ASE_TEST_MYSQL_DSN` unless it points to a separate
  test-named database.
- The function-scoped autouse fixture resets before dependent fixtures, then resets in `finally`
  after them, including test-body and fixture-setup failures. It captures the validated DSN once so
  test monkeypatches cannot redirect teardown. Unmarked tests do not connect or reset.
- Cleanup deletes only existing tables from this fixed child-before-parent order:
  `work_queue_accepted_artifacts`, `work_queue_steps`, `work_queue_admissions`,
  `work_queue_events`, `work_queue_claims`, `work_queue_items`, `verification_reservations`,
  `dispatch_commits`, `dispatch_workforce_snapshots`, `state_events`, `tasks`. Table discovery is
  restricted to `DATABASE()`; identifiers in DELETE come only from this source-code allowlist.
  Keep schemas, authority lock rows, legacy archive tables and unrelated tables. Empty/partial
  schemas are valid; the real stores still initialize their own schema. Deletes commit together;
  errors rollback and propagate instead of silently declaring the database clean.
- A disposable database is exclusive to one serial pytest process/worker. Concurrent workers must
  receive different DSNs; this fixture does not provide cross-process locking. A killed process may
  skip teardown, so the next test's setup must also reset. Preserve required debug facts before rerun.

### 4. Validation & Error Matrix

| Input / state | Required result |
|---|---|
| `ASE_TEST_MYSQL_DSN` absent | MySQL fixture skips; non-MySQL tests continue |
| database `ase_self_iteration_test`, `test_ase` or `platform_tests` | allow the marked test to construct fixtures |
| database `ase_self_iteration`, `production` or `staging_copy` | abort before fixture setup and before SQL |
| malformed scheme, missing database, nested path or unsafe/control text | abort with a bounded `<invalid>` name |
| credentials embedded in rejected DSN | no credential substring in the guard error or session exit message |
| earlier test left active verification/dispatch/queue facts | clear before fixtures; no cross-test capacity |
| test body or dependent fixture raises | `finally` clears the same captured test database |
| empty/partial schema | delete only present allowlisted tables; never initialize or drop schema |
| unknown table or authority lock row | preserve unchanged |
| database delete fails | rollback and fail the fixture; do not continue with polluted facts |

### 5. Good / Base / Bad Cases

- **Good**: full pytest receives `ASE_TEST_MYSQL_DSN=.../ase_self_iteration_test`; destructive fixture
  reset is confined to that disposable schema.
- **Base**: a developer runs focused unit tests without a MySQL DSN; MySQL cases skip as before.
- **Bad**: set `ASE_TEST_MYSQL_DSN` to the Web Console's `ase_self_iteration` schema because both are
  local. Dispatch and queue fixture cleanup then deletes live allocation facts while filesystem
  checkpoints and SQL Tasks survive, making Team View fail closed with a missing dispatch.

### 6. Tests Required

- `tests/test_mysql_test_safety.py` must cover accepted and rejected database names, malformed unsafe
  names, and credential redaction.
- A focused pytest invocation against one `mysql`-marked case with a non-test database must terminate
  before its fixture executes; the output must contain only the safe database name.
- Dispatch and queue integration tests still run only against a separately provisioned test-named
  schema. They must not be used as verification against production data.
- `tests/test_mysql_test_isolation.py` must run actual pytest items against real MySQL, including a
  producer leaving an active verification reservation, a subsequent clean consumer, test failure
  and fixture failure. Verify both setup isolation and final teardown.
- Repeating `test_active_candidate_verification_is_visible_as_qa_work` before
  `test_serial_joint_deliveries_do_not_exhaust_finished_agent_capacity` must retain DONE delivery.

### 7. Wrong vs Correct

#### Wrong

```python
dsn = os.environ["ASE_TEST_MYSQL_DSN"]
cursor.execute("DELETE FROM dispatch_commits")
```

#### Correct

```python
# Repository-wide hook runs before fixture setup.
dsn = require_isolated_mysql_test_database(os.environ["ASE_TEST_MYSQL_DSN"])
# Destructive fixture reset is now confined to an explicitly disposable database.
```

### Regression analysis: test reservations consume later tests' capacity (2026-09-19)

Root cause is D/E (missing cross-test coverage / implicit database emptiness). `tmp_path` isolates
Git and sidecars, but production fixtures reuse `agent_team_qa`/`agent_team_reviewer` and a shared
MySQL authority. The Team View active-verification test intentionally inserts an unfinished
`verification_reservations` row. Module-local dispatch cleanup only runs when that module executes;
it cannot isolate e2e, recovery or reader tests, or consecutive pytest invocations.

Repeating that real producer fills eight slots and makes the original serial joint-delivery test
BLOCKED at `PlanningPreviewRejected`; on clean storage the same ten Tasks finish. A two-item pytest
regression also detects one residual reservation immediately, without waiting for capacity exhaustion.
Passing the target alone or just its own module does not disprove persistent-state contamination.

Prevention is the guarded per-item setup/finally boundary across all MySQL tests, including Task
events and queue facts, with lifecycle regression coverage. Production terminal-Task release and
unfinished-reservation safety remain unchanged. Existing-data handling: do not modify production
Requirements, Tasks, approvals or queues. The next marked test safely resets old disposable test
facts; rerun the failed test/suite using its dedicated database. No production migration is needed.

## Bug Analysis: full regression deleted live dispatch and queue facts

### 1. Root Cause Category

- **Category**: E — Implicit Assumption, reinforced by D — Test Coverage Gap.
- **Specific cause**: MySQL fixtures trusted the variable name `ASE_TEST_MYSQL_DSN` but never validated
  the target database. A full regression was run with the live `ase_self_iteration` database. The
  dispatch fixture deleted all workforce snapshots and commits, and the queue fixture deleted all
  queue items, claims and events. SQL Tasks and filesystem checkpoints were stored elsewhere and
  survived, leaving a cross-store lineage that correctly failed closed on read.

### 2. Why Fixes Failed

1. Restarting the Console could not help because configuration and connectivity were healthy; the
   durable allocation row itself was gone.
2. Treating the 503 as a Reader compatibility issue would only hide corruption and weaken the
   filesystem/SQL integrity contract.
3. Documentation already said “专用测试数据库”, but prose without an executable pre-fixture guard
   did not prevent the destructive command.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
|---|---|---|---|
| P0 | Runtime test guard | Reject non-test database names before every `mysql` fixture | DONE |
| P0 | Regression | Cover accepted/rejected names and secret-safe errors | DONE |
| P0 | Documentation | State the exact naming fence and destructive-table reason in README/spec | DONE |
| P1 | Operations | Provision `ase_self_iteration_test` separately for local full regression | HUMAN SETUP |

### 4. Systematic Expansion

- **Similar issues**: both dispatch authority and persistent queue fixtures performed aggregate-wide
  cleanup; guarding only one fixture would leave the other capable of damaging live state.
- **Design improvement**: database disposability is now checked once at the repository pytest
  boundary instead of relying on each future fixture author to remember it.
- **Process improvement**: a production DSN must never be reused to gain MySQL coverage during a full
  regression; absent isolated storage, leave MySQL tests skipped.

### 5. Knowledge Capture

- The executable isolation contract, validation matrix and test locations are recorded above.
- README names the allowed test database patterns and explains why the guard exists.
- This repository has no `.trellis/spec/guides/` or `src/templates/markdown/spec/` mirror; there is no
  guide or template file to synchronize.

### 3.6 T046 Worker composition

`TeamHost` composes `MySqlRoleQueue` with the shared dispatch authority. Production delivery binds the
approved `DeliveryAllocation` and `ExecutionPlan` to one `QueuedRoleStep` at a time. A single Manager
operation may supervise the bounded steps synchronously for compatibility, but every Coder, QA and
Reviewer model invocation requires a real T046 claim and lease heartbeat. `DispatcherLoop.tick` supports
an explicit `work_item_id` filter for this compatibility supervisor so it cannot execute another Task's
claim in the current repository worktree.

The Worker must be stopped before a native/queue rollout is reversed. Existing terminal Tasks, approvals,
Task events, dispatch records and Artifact files are immutable; only queue adoption, role-step and
accepted-receipt records are new facts. A missing queue claim is not repaired by changing a Task status.

`QueueLeaseLost` passes through the production execution guard as `DeliveryQueuePending`, retaining
the native/joint DELIVERING checkpoint rather than persisting INVARIANT_VIOLATION/BLOCKED. Only ordinary
queue corruption/authorization conflicts fail closed as invariants. Supervisor exceptions preserve
all role worktrees, including clean ones whose branch already exists; cleanup occurs after a normal
terminal result. `test_host_records_isolated_delivery_without_polluting_project[64000-True]` interrupts
the real adapter lease and verifies the same delivery resumes to DONE with three accepted receipts.

The frozen policy version authorizes explicit fallback routes; only the primary route is represented
in the claim. Validate ordered fallback membership/reasoning through `ApprovedRoleDispatch` before
client construction, and retain ModelRouteAttempt actual-model facts. Separate candidate verification
continues through its original reservation, whose capacity must not be dropped on native adoption.
Follow `docs/t046-worker-operations.md` for rollout/rollback; do not resume an adopted nonterminal Task
with an old binary that does not know about queue admission.

## Scenario: explicit local proxy for production Codex CLI routes (2026-09-23)

### 1. Scope / Trigger

Use this contract when an operator wants platform-owned Codex CLI calls to use a
local Responses proxy. A normal `~/.codex/config.toml` provider is deliberately
insufficient: both production adapters pass `--ignore-user-config`, so loading
that file would also import unrelated hooks, approval choices and provider
behavior. This scenario changes transport configuration, not Task/Artifact
identity, role permissions or retry semantics.
The original URL-only login mode is described first; the write-only Settings
key mode below supersedes its authentication details when configured.

### 2. Signatures

```python
ProductionConfig.codex_cli_proxy_base_url: str | None
normalize_local_codex_proxy_base_url(value: str) -> str
codex_cli_proxy_overrides(base_url: str | None) -> tuple[str, ...]
CodexCliStructuredModelClient(..., proxy_base_url: str | None = None)
CodexCliAgentAdapter(..., proxy_base_url: str | None = None)
ConfiguredStructuredClientFactory.for_projects(...) -> StructuredModelClient
ConfiguredDeliveryRouteAdapterFactory.create(...) -> AgentAdapter
```

The URL wire field is optional in `schemas/production-config.schema.json` and
`config/production.example.json`; `GET/PUT /api/v1/admin/settings` uses the
existing typed `ProductionConfig` request/response. This URL-only baseline
introduces no new API endpoint, database migration or Task Schema.

### 3. Contracts

- Only absolute `http` URLs whose host is exactly `localhost`, `127.0.0.1`
  or `[::1]` are accepted. The URL may have a valid port and base path, but no
  userinfo, query, fragment, whitespace, control character, double quote or
  backslash.
  For URL-only mode, the proxy is trusted local infrastructure. Authentication uses a Codex
  API-key login in the same CLI credential cache as the service; the key never
  crosses platform Settings, persisted JSON, role subprocess environment or
  command-line arguments. A revoked ChatGPT login is not a substitute.
- `None` emits no proxy overrides and retains the direct-login CLI behavior.
  A configured URL without a managed key emits fixed, quoted `-c` values for
  `model_provider="ase_local_proxy"`, `model_providers.ase_local_proxy.name`,
  `base_url`, `wire_api="responses"` and `requires_openai_auth=true`.
  The provider name and config keys are code-owned, not arbitrary UI strings.
- `src/ai_software_engineer/manager/production_backend.py` passes the same
  setting to Product/Designer/Planner structured calls;
  `manager/production_delivery.py` passes it to Coder/QA/Reviewer. Both use
  `config/codex_proxy.py` to construct overrides and keep
  `--ephemeral --ignore-user-config`, explicit sandbox, schema, worktree and
  tool-policy arguments unchanged.
- The URL-only Settings baseline writes only the base URL. `LocalConsoleAdministration`
  persists the secret-free field through the existing atomic configuration
  writer and reports `restart_required`; no hot mutation of an in-flight run.

### 4. Validation & Error Matrix

| Input or event | Expected behavior |
|---|---|
| No proxy field / `null` | Historical direct CLI command; ChatGPT CLI authentication may be needed |
| `http://127.0.0.1:8317/v1` | Schema and Pydantic accept; both production factories pass it to CLI adapters |
| Remote HTTP/HTTPS, credentials, query, fragment, quote, whitespace or bad port | Reject typed config before persistence or model invocation; never interpolate free-form argv |
| Proxy unavailable / incompatible Responses wire API | Existing typed CLI failure; preserve diagnostics and retry budget, never silently use direct provider |
| Missing proxy API key / revoked CLI credential in URL-only mode | Explicit authentication failure; operator must use `codex login --with-api-key` in the service's CLI credential environment |
| Settings save while Host runs | Return `restart_required=true`; old Host keeps its frozen config until application restart |
| Existing failed Requirement | Preserve Operation and checkpoint history; operator explicitly continues after restart |

### 5. Good / Base / Bad Cases

- Good: a loopback CLIProxyAPI base URL appears as fixed `model_provider` and
  `base_url` overrides in upstream and delivery CLI invocations; all role
  sandbox and `--ignore-user-config` flags remain present, and the proxy API
  key is read by Codex from its own credential cache.
- Base: no URL means no new overrides and the current direct CLI behavior.
- Bad: remove `--ignore-user-config` to pick up an operator's proxy. That also
  imports unrelated user policy and may change the execution boundary.

### 6. Tests Required

- `tests/config/test_production.py`: schema/typed round-trip for valid URL;
  reject remote, credential-bearing, query/fragment, malformed and injection
  strings.
- `tests/agents/test_structured_models.py` and
  `tests/agents/test_codex_cli.py`: exact proxy override tokens, retained
  `--ignore-user-config`, URL-only `requires_openai_auth=true`, no override in
  the default case, and no proxy key in argv.
- `tests/manager/test_production_backend.py` and
  `tests/manager/test_production_delivery.py`: both production composition
  seams pass the same value to the right adapter.
- `tests/web_console/test_administration.py` and
  `tests/team_view/browser/settings-layout.test.cjs`: Settings persists the
  URL field, requires restart and keeps model-page layout aligned at desktop
  and narrow widths.

### 7. Wrong vs Correct

```python
# Wrong: personal config becomes ambient authority for every production run.
argv = ("codex", "exec", "--sandbox", "read-only", "-")

# Correct: fixed proxy transport is explicit, while user config stays ignored.
argv = (
    "codex", "exec", "--ignore-user-config", "--sandbox", "read-only",
    *codex_cli_proxy_overrides(config.codex_cli_proxy_base_url), "-",
)
```

## Follow-up: write-only proxy key in Settings (2026-09-23)

### Signatures and fields

```python
ProductionConfig.codex_cli_proxy_api_key_env: EnvVarName | None
codex_cli_proxy_overrides(base_url: str | None,
                          api_key_env: str | None = None) -> tuple[str, ...]
codex_cli_proxy_key_environment(source: Mapping[str, str],
                                api_key_env: str | None) -> dict[str, str]
UpdateSettingsRequest.runtime_variables: tuple[RuntimeVariableUpdate, ...]
```

The only accepted key name is `ASE_CODEX_PROXY_API_KEY`; it requires a valid
`codex_cli_proxy_base_url` and must not collide with MySQL/Responses credentials.
The browser sends the value only as a `runtime_variables` item in
`PUT /api/v1/admin/settings`, never inside `config`. The existing
`LocalRuntimeEnvironmentStore.save` writes it to sibling `runtime.env` with
mode `0600`; GET returns only `SecretStatus(configured=...)`. An empty input
retains the value, explicit CLI-login selection removes the config reference
and the next save prunes the stored key. A new key or changed mode requires
Host restart. Existing Requirement/Task/Operation facts are not rewritten.

With no managed key, provider overrides remain
`requires_openai_auth=true`. With the managed key, they set
`requires_openai_auth=false`, `env_key="ASE_CODEX_PROXY_API_KEY"`,
`shell_environment_policy.ignore_default_excludes=false` and an exact
`shell_environment_policy.filters.ASE_CODEX_PROXY_API_KEY="exclude"`.
Both adapters add only that referenced value to the otherwise non-secret
Codex process environment. The model-invoked shell must not inherit it.
The delivery adapter's own Git inspection subprocess uses a separate
`PATH`/`LANG`/`LC_ALL`/`GIT_TERMINAL_PROMPT` allowlist; it must not inherit the
host's managed proxy key.
Factories fail before CLI launch if the value is missing; the structured
adapter replaces potentially credential-bearing stderr with a fixed message.
No raw key may enter argv, stdout/stderr-derived diagnostics, Operation or
model prompts. This is the trusted single-user local `runtime.env` trade-off;
the file remains sensitive and must not be placed in a target repository.
The shell environment exclusion does not prove that the same-UID model process
cannot read that file; do not claim filesystem secret isolation for this mode.

| Case | Result |
|---|---|
| No URL / no key reference | Historical direct CLI command |
| URL only | Existing Codex CLI login provider behavior |
| URL + key reference + stored value | Both CLI paths use `env_key`, exact process env and shell exclusion |
| Key reference without URL, wrong name or credential-name collision | Pydantic/Schema rejection before persistence |
| Key reference with missing runtime value | `ProductionConfigError`; no CLI launch or fallback |
| Proxy reports `401`/`403` or `Missing API key` | `AUTHENTICATION_ERROR`, non-transient; preserve checkpoint without consuming transient retries |
| Replace key | Save new 0600 value, return status only, mark restart required |
| Clear key reference | Prune stored value, revert to CLI login mode after restart |

Good: UI saves a write-only key and a subsequent CLI invocation has the
referenced process variable but no key in argv/tool-shell policy. Base: URL
only keeps the previous login mode. Bad: set `env_key` while retaining
`requires_openai_auth=true` (Codex ignores `env_key`), echo the submitted
value from GET, or inherit the full host environment.

Required assertions: `tests/config/test_production.py` checks Schema/model
parity; `tests/web_console/test_administration.py` checks 0600 persistence,
replacement, redacted status and pruning; both `tests/agents/test_*codex*`
paths check fixed argv, exact env and error secrecy; both
`tests/manager/test_production_*` factories check missing-value refusal;
`tests/team_view/browser/settings-layout.test.cjs` checks password input,
aligned layout and request-only value. Both CLI adapter test modules assert
that a `401 Missing API key` response is non-transient.
`tests/agents/test_codex_cli.py` also asserts Git inspection receives no
managed proxy key from the host environment.
