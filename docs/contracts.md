# 角色、权限与 Artifact 契约

## 1. 角色总览

| 角色 | 读取 | 写入 | 可执行 | 不能做 | 输出 |
|---|---|---|---|---|---|
| Orchestrator | Task、全部 artifact、策略和 Git 元数据 | 状态事件、artifact 索引、运行元数据 | 受 allowlist 的 Git/测试/Agent 启动 | 不写业务代码，不替代 Reviewer | 状态迁移、路由决定 |
| Coder | 任务上下文、规范、相关代码、QA/Review findings | 生产代码、单元测试、implementation-report | lint、unit test、受限构建 | 修改 verdict、修改 Trellis 规则、访问 secrets | commit + implementation-report |
| QA | PRD、验收标准、候选 diff、生产代码、测试规范 | QA 测试目录、qa-report | 测试、静态检查、只读构建 | 修改生产代码、批准代码、改写 Coder artifact | qa-report |
| Reviewer | PRD、plan、diff、implementation-report、qa-report、规范 | review-report（仅 artifact store） | 只读检查、测试复跑 | 修改仓库、修改 QA verdict、直接 merge | review-report |

权限必须由机器可验证的 policy 表达；自然语言 prompt 只是解释，不是授权来源。

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
- `producer` 是角色 + agent 版本 + run_id；
- `source_revision` 指向实际读取/审查的 Git revision；
- `evidence` 是可定位、可复核的引用，不接受“看起来没问题”这类无证据描述；
- artifact 不可原地修改；修订通过新 artifact + `supersedes` 关系表达；
- Schema 校验、哈希计算和持久化由 Orchestrator/ArtifactStore 完成，Agent 不能自报通过。

## 7. 四类 artifact 的最小字段

| kind | 必填业务字段 |
|---|---|
| `plan` | goal、assumptions、steps、acceptance_mapping、risks |
| `implementation-report` | commit_sha、changed_files、acceptance_mapping、tests_run、known_risks |
| `qa-report` | status、criteria_results、tests_run、findings、evidence |
| `review-report` | verdict、findings、checked_dimensions、evidence |

详细机器契约见 [`schemas/`](../schemas/)。
