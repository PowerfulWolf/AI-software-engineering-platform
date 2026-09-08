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
OrganizationTeamHost.work_queue -> MySqlPersistentWorkQueue
OrganizationTeamHost.planner_dispatcher(*, demand_builder, worker_id,
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
- project registry 现在由 `CompanyWorkspace.project_registry()` 装配，位于
  `companies/<company_id>/projects/`；`company_knowledge_paths` 显式选择的资料作为只读、
  脱敏、digest-bound 的公司上下文纳入 baseline。公司归属契约见 `company-workspace.md`。
- 组织稳定拥有三个不同的 Coder、QA、Reviewer AgentProfile；model/provider 是每次 Run 的
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

Scope: changing the configured primary model in an already initialized organization, both native
and recovery dispatch. `AgentProfile.id` and `default_model_policy_id` must remain stable.

Signatures: `FileOrganizationWorkforceStore.put_policy(policy, *, versioned=False)` and
`get_policy(policy_id, *, version=None)`. Production callers opt into versioned writes. `_workforce`
sets `ModelPolicy.version = "v0.1-" + sha256(canonical_policy_without_version)`; canonical encoding is
UTF-8, sorted JSON keys, compact separators, ensure_ascii=False. Full policy content participates.
ModelSelection already contains policy_version; no wire or SQL schema changes are required.

Versioned files use `<policy-id>__<sha256(version)>.json` in organization/model-policies, with the
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
test can prevent prompt regression; only live delivery can test model compliance. If this contract is
still insufficient, the next architectural step is staged/checkpointed Coder execution, not unbounded
timeouts or silent adoption of dirty work.

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

Production preparation uses `ProjectManagerSkillService(versioned_preparations=True)` and
`RuntimeWorkspaceBinder(versioned=True)`. A stable project ID is not a single immutable baseline:
new profiles are stored at `profile/project-profile-<profile_sha256>.json`, bindings at
`policy/runtime-workspace-binding-<binding_sha256>.json`, and preparation records under
`policy/preparations-<profile_sha256>/`. All stay inside the same company project module.
Matching legacy fixed-name records are replayed with their original timestamps; other legacy
records remain untouched. New snapshots are exclusively published, never replace concurrent winners.
`load_project_profile(sidecar, profile_sha256)` must read the requested hash, not a mutable latest
pointer. A legacy fallback must pass that exact hash; corrupt/symlink snapshots never fall back.
Low-level composition remains legacy by default. New production intakes may prepare newer facts,
but existing delivery/product/stage gates still compare their exact preparation and source revision;
this does not authorize rebasing old approval or QA/Review evidence in place.

- dispatch 后才可 materialize Task；Task repository、Artifact/Context/Evidence roots、Agent definitions
  和 dispatch bundle 必须来自同一 project sidecar 与 exact revision lineage。
- 目标项目必须是真实目录、Git root、clean working tree 且 HEAD 为 full commit。Task `allowed_paths`
  来自 TechnicalDesign affected paths，commands 来自确定性 ProjectProfile build-system allowlist。
- Coder worktree 位于 `<platform_root>/worktrees/<project-id>/<task-id>/coder-attempt-01` 并使用
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
- T042 production context 使用显式 32,000 input / 4,000 output reserve；完整规范索引和批准文档
  不截断，语言 marker 清单仅作 context-only 投影。低层 Runtime 默认仍为 12,000 input。
  签名、错误矩阵与回归点见 `python-runtime.md` 的 T042 小节；旧 manifest/审批不改写。

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
| Coder provisional report/diff 不匹配、越权路径或 finalization 后 dirty | Codex Git guard | policy/invalid-output failure；不进入 QA |
| Coder 返回合法未完成 checkpoint | artifact/worktree/state guards | 保存 progress，重新排队下一次 Coder；不进入 QA |
| Coder continuation 预算耗尽或 checkpoint 漂移 | retry/runtime admission | BLOCKED，保留 progress 和 worktree evidence |
| production role 超过其 1,800/1,200 秒预算 | subprocess/adapter timeout guard | 无 Artifact；dirty 现场保留，Task BLOCKED |
| QA/Reviewer candidate 不同或修改 worktree | dispatch/worktree/artifact guard | fail closed；不进入 DONE |
| `status`/`resume` durable facts 损坏 | checkpoint reconciliation | corruption/drift failure；不覆盖原记录 |

错误消息只能包含稳定分类和安全摘要；不得输出 DSN、Authorization header、API key、provider response
body 或目标项目中的 secret。

## 5. Good / Base / Bad Cases

- **Good**：真实临时 Git 项目 + MySQL + scripted structured/delivery providers 完成
  prepare→Product approval→Design→Plan→dispatch→Coder diff/report→平台 candidate finalization→独立 QA/Review→DONE；main checkout 和
  target files 不变，candidate commit 可由 `git show` 复核。
- **Base**：缺少真实额度时，contract/E2E 使用注入的 deterministic providers；Production Host、MySQL、
  dispatch、worktree 和 typed artifact 仍走真实实现。只有显式 live smoke 才消费 GPT-5.5。
- **Bad**：在每个项目复制 AgentProfile；把 DSN/API key 写入 JSON；Planner 直接提交分配；让同一 Agent
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

- `tests/config/test_production.py`：配置文件/env、route 条件、duplicate route、secret 不落盘；
- `tests/contracts/test_json_schema_contracts.py`：ProductionConfig positive/negative canonical schema；
- `tests/store/test_mysql_repository.py`：与 SQLite 可观察行为一致、atomic append、replay/conflict、rollback、
  reopen；必须通过 `ASE_TEST_MYSQL_DSN` 显式 opt-in；
- `tests/project_manager/test_mysql_dispatch_authority.py`：snapshot/commit 幂等、stale fence、reservation、
  corruption、跨连接恢复；三种 Task 终态释放容量而不删除分配事实，非终态仍占容量；
- `tests/e2e/test_joint_delivery.py`：一个 Host 连续完成五次双仓需求（10 个原生 Task），超过
  Agent 的 8 个并行槽位仍可串行交付，不能通过增加 capacity 或等待 15 分钟掩盖 Lease 泄漏；
- `tests/agents/test_codex_cli.py`、`test_responses.py`、`test_fallback.py`、
  `test_openai_compatible.py`：request/response、Git、tool、error mapping、fallback allowlist 和 attempt replay；
- `tests/project_manager/test_production_agents.py`：Product/Designer/Planner typed draft 和 exact lineage；
- `tests/project_manager/test_production_backend.py`：真实 MySQL + 临时 Git + scripted team 到 DONE，独立
  verifier worktrees 检查 exact candidate，主 checkout 零污染，并断言三个 delivery role 的生产预算；
- `tests/recovery/test_execution.py`：offline Codex runner 直接断言 recovery 将相同 role timeout 传入
  subprocess seam；
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
