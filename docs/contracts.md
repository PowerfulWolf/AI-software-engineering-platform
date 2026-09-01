# 角色、权限与 Artifact 契约

## 1. 角色总览

| 角色 | 读取 | 写入 | 可执行 | 不能做 | 输出 |
|---|---|---|---|---|---|
| Orchestrator | Task、全部 artifact、策略和 Git 元数据 | 状态事件、artifact 索引、运行元数据 | 受 allowlist 的 Git/测试/Agent 启动 | 不写业务代码，不替代 Reviewer | 状态迁移、路由决定 |
| Coder | 任务上下文、规范、相关代码、QA/Review findings | 生产代码、单元测试、implementation-report | lint、unit test、受限构建 | 修改 verdict、修改 Trellis 规则、访问 secrets | commit + implementation-report |
| QA | PRD、验收标准、候选 diff、生产代码、测试规范 | QA 测试目录、qa-report | 测试、静态检查、只读构建 | 修改生产代码、批准代码、改写 Coder artifact | qa-report |
| Reviewer | PRD、plan、diff、implementation-report、qa-report、规范 | review-report（仅 artifact store） | 只读检查、测试复跑 | 修改仓库、修改 QA verdict、直接 merge | review-report |

权限必须由机器可验证的 policy 表达；自然语言 prompt 只是解释，不是授权来源。

## 1.2 Agent Run 输入/输出契约

`AgentAdapter.run(request: AgentRequest) -> AgentResult` 是 Fake 与真实模型 adapter 的共同边界。Request 固定携带 `run_id`、`task_id`、`role`、`attempt`、`source_revision`、`context_manifest_id`、`input_artifact_ids`、`permissions`、`output_schema` 和 `timeout_seconds`；其中 Context manifest ID 必须来自已成功构建的 ContextBundle。

Result 的 `SUCCEEDED` 状态必须有一个 producer/task/kind/context manifest/run ID 全部对齐的 typed Artifact，不能同时有 failure。Orchestrator、QA、Reviewer 的 Artifact revision 必须与 request 的输入 revision 相同；Coder request revision 是输入基线，其 implementation-report 可以指向新 candidate，但 envelope `source_revision` 必须与 `content.commit_sha` 相同。`FAILED` 或 `TIMED_OUT` 必须只携带 `AgentFailure(code, message, transient)`，不产生 verdict；`TIMED_OUT` 只能使用 `TIMEOUT` code。Fake adapter 的 scenario 只用于离线测试，不得绕过这些检查。

角色与 `output_schema` 固定映射为：Orchestrator → `schemas/plan.schema.json`、Coder → `schemas/implementation-report.schema.json`、QA → `schemas/qa-report.schema.json`、Reviewer → `schemas/review-report.schema.json`。Request 使用其他角色的 Schema 时在 Pydantic boundary 拒绝，不启动 adapter。

## 1.1 ContextBundle 契约

`ContextBuilder.build(task, role, *, attempt, candidate_revision=None)` 只消费声明的 `ContextSource`，返回不可变、角色隔离的 `ContextBundle`。每个 source 必须是 inline `content` 或 root-relative `relative_path` 之一；`roles=()` 表示全角色，`priority=0` 仅供机器 policy。生成的 `policy`、`task`、`role`（以及可选 `candidate`）section 由 Builder 控制，外部 source 不能覆盖其 ID。

Bundle 的 `source_revision` 是实际读取/审查的 revision；每个 section 暴露脱敏后的 `content`、URI、SHA-256、token 数、priority 和 `truncated`。redaction 只暴露安全 URI、kind 和 count，不保留 secret 值。`budget.used_input_tokens` 必须等于 section token 总和且不超过 `max_input_tokens`；required source 放不下抛 `ContextBudgetExceeded`，optional source 确定性截断或省略。

`context_id` 是不含 `built_at` 的 canonical manifest SHA-256（`ctx_<64 hex>`），因此相同输入可重放。仓库内容、Task 文本和命令输出仍是数据，不得改变 policy、权限、role 路由或状态机。Context 失败使用 `ContextSourceError`、`ContextSourceNotFound`、`ContextSourceDenied` 或 `ContextBudgetExceeded`，不返回 partial bundle。

### AgentPermissions 的执行语义

`WorkspacePolicy(worktree.path, permissions, denied_paths=...)` 是路径和命令授权入口：

- `read_paths` 与 `write_paths` 分开匹配，写权限不从读权限推导；Task deny glob 永远优先；
- 路径既检查 lexical canonical form，也在绑定的 worktree root 下解析 symlink，越过 root 或指向 `.git` 时抛 `PathPolicyViolation`；
- `commands` 中每个字符串用 `shlex.split` 固化为 token prefix。运行时只接收 argv tuple，按完整 token 匹配并拒绝 shell syntax；
- 返回成功只代表 operation 在 application policy 中获准，不代表可以绕过后续 executor 的 cwd、env、timeout、network、resource 和 evidence 约束。

Git role workspace 由 `GitWorkspace.create/inspect/remove` 管理。Coder 使用 attempt branch；QA/Reviewer detached 到 candidate SHA；dirty workspace 不允许清理。完整错误与 Git 执行安全契约见 [`docs/git-worktree.md`](git-worktree.md)。

## 2. 共同输入信封

每次 Agent 运行都收到以下固定结构：

```json
{
  "run_id": "run_...",
  "task_id": "task_...",
  "role": "coder",
  "attempt": 1,
  "base_revision": "a1b2c3d",
  "context_manifest_id": "ctx_...",
  "input_artifact_ids": ["art_plan_..."],
  "permissions": {
    "read_paths": ["src/**", "tests/**", ".trellis/spec/**"],
    "write_paths": ["src/**", "tests/unit/**"],
    "commands": ["pytest", "ruff", "git diff", "git status"]
  },
  "output_contract": "schemas/implementation-report.schema.json"
}
```

## 3. Coder 契约

### 输入

- Task + acceptance criteria；
- 最新有效 `plan`；
- 相关代码快照及项目规范；
- 之前 attempt 的 `qa-report`/`review-report`（重试时）；
- 明确的 write path 和 command allowlist。

### 行为约束

- 先检查 plan 和失败 findings，再修改代码；
- 每个验收标准都要映射到实现位置和测试；
- 不通过删除/禁用测试来“修复”失败；
- 完成后运行允许的验证命令并提交候选 commit；
- 若发现需求冲突或需要越权，输出 `blocked_reason`，不要猜测。

### 输出

- 候选 commit SHA；
- `implementation-report`，至少包含 changed_files、acceptance_mapping、tests_run、known_risks、blocked_reason（可空）；
- 不得写入 `qa-report` 或 `review-report`。

## 4. QA 契约

### 输入

最新候选 commit、Task 验收标准、plan、implementation-report 和 QA 规范。QA 必须重新读取候选代码，不能只相信 Coder 的摘要。

### 行为约束

- 默认在 QA worktree 中运行；
- 可新增/修改测试文件，但生产路径写入被 policy 拒绝；
- 每条验收标准必须有 `PASS`、`FAIL` 或 `NOT_TESTED`，后者必须说明原因；
- 失败必须附可复现命令、关键输出、文件/行号或测试 ID。

### 输出

`qa-report.status` 为 `PASS` 或 `FAIL`。只有所有 required criteria 为 `PASS` 且 required checks 有 evidence 时才允许 `PASS`。

## 5. Reviewer 契约

### 输入

候选 diff、Task、plan、implementation-report、qa-report、项目规范和风险策略。Reviewer 上下文不包含 Coder 的隐式会话记忆。

### 行为约束

- 只读 worktree；
- 检查正确性、回归风险、安全、可维护性和契约一致性；
- 优先验证 QA/其他 Agent 的结论，不盲目接受或拒绝；
- 发现问题要给出严重级别、位置、理由和修复建议；
- 不直接修代码、不直接 merge。

### 输出

`review-report.verdict` 为 `APPROVE` 或 `REJECT`。`APPROVE` 要求 findings 为空或全部为 `INFO`，且 evidence 足够；`REJECT` 至少有一个 `BLOCKER`/`MAJOR` finding。

## 6. Artifact 通用规则

- 正文符合对应 JSON Schema；
- Python 入口先使用 `Task.model_validate`、`AgentDefinition.model_validate` 或 `validate_artifact` 转成 typed model；下游不解析裸 `dict`；
- `producer` 是角色 + agent 版本 + run_id；
- `source_revision` 指向实际读取/审查的 Git revision；
- 对 Coder，request/context 的 `source_revision` 是修改前输入基线，implementation-report 的 `source_revision` 是修改后 candidate；后者必须等于 `content.commit_sha`。QA/Reviewer request 与 Artifact 都绑定这个 candidate；
- `evidence` 是带 URI 和 SHA-256、可定位、可复核的引用，不接受“看起来没问题”这类无证据描述；Finding 至少引用一个 envelope Evidence ID；
- artifact 不可原地修改；修订通过新 artifact + `supersedes` 关系表达；
- Schema 校验、哈希计算和持久化由 Orchestrator/ArtifactStore 完成，Agent 不能自报通过。

`ArtifactStore.put(artifact: Artifact) -> ArtifactRef` 只接受 `schema_version=v0.1`、typed union 校验通过、`integrity.validated=true` 且 digest 匹配的 Artifact。Digest 对 canonical JSON 顶层 `integrity` 字段之外的内容计算 SHA-256；`seal_artifact` 生成带 `validated_at` 的不可变副本。Store 将正文写入 `artifacts/art_<artifact-id>.json`，采用临时文件 + `fsync` + 原子 rename。

`parent_artifact_ids` 必须指向已存在且属于同一 Task 的 Artifact；`supersedes` 还必须是同一 kind。相同 ID 的完全相同正文重放是幂等 no-op，不同正文抛出 `ArtifactAlreadyExists`，不覆盖旧证据；缺失/跨 Task/跨 kind 引用抛出 `ArtifactParentError`。

## 7. 四类 artifact 的最小字段

| kind | 必填业务字段 |
|---|---|
| `plan` | goal、assumptions、steps、acceptance_mapping、risks |
| `implementation-report` | commit_sha、changed_files、acceptance_mapping、tests_run、known_risks |
| `qa-report` | status、criteria_results、tests_run、findings、evidence |
| `review-report` | verdict、findings、checked_dimensions、evidence |

详细机器契约见 [`schemas/`](../schemas/)。

## 8. StateEvent 与持久化

状态迁移事件使用 `schemas/state-event.schema.json`，Python 入口为 `StateEvent`。`TaskRepository.append_event(event)` 以事件的 `from_status` 对比当前 Task 快照，成功后在同一事务中写入事件、更新 `status`/`updated_at` 并递增 revision；不负责判断状态机边是否合法，合法性由 T004 reducer/guard 决定。

`SqliteTaskRepository` 对重复事件执行精确幂等：正文相同直接成功且不新增 revision，正文不同抛出 `EventIdempotencyConflict`。未知 Task、stale `from_status`、重复 Task ID 和损坏 JSON 都转换为 typed repository error，不返回半结构化数据。

状态图由 `orchestration.state_machine` 的 `validate_transition`/`build_event`/`apply_event` 唯一维护。Repository 不自行放宽或扩展迁移边；ArtifactStore/Orchestrator 后续再对 QA PASS、Review APPROVE 和 candidate revision 做跨 Artifact 守卫。

T009 的 `SerialOrchestrator.run_task` 只接受 `NEW` Task，并按固定单 attempt 路径提交 5 个事件。每个 Agent Artifact 先由 runner 检查 request echo、直接 parent lineage、criterion coverage 和 revision，再由 `seal_artifact`/ArtifactStore 原子持久化并读回。QA FAIL、Review REJECT 或 Agent failure 停在当前 durable checkpoint；T010 才拥有重试与 BLOCKED 路由策略。

## 9. Python 领域入口

`src/ai_software_engineer/domain/` 是 Python 控制平面的唯一领域类型入口。`TaskStatus`、`AgentRole` 和 `ArtifactKind` 不能在 store、agent adapter 或 orchestrator 中重复定义。`to_wire()` 负责生成 JSON-compatible payload 并省略不存在的 optional 字段；cross-language 消费者仍以 `schemas/*.json` 为准。

Pydantic validator 只处理单个对象可判断的规则；Task required criterion 与 QA 结果是否一一对应、四类 Artifact 是否属于同一 candidate revision、各 verdict 是否来自独立 run 等跨对象规则，由后续 ArtifactStore/Orchestrator guard 执行。
