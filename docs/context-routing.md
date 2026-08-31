# Context Builder / Context Routing

## 1. 目标

Context 的职责是把组织知识、项目事实、任务输入和上游证据编译成**最小、确定、可审计**的角色上下文。它不是把所有文件复制给 Agent，也不是让 Agent 自己决定哪些规则适用。

## 2. Context 层次

按优先级从高到低：

1. **Safety & platform policy**：权限、命令 allowlist、secret redaction、状态机不变量；不可被下层覆盖。
2. **Organization knowledge**：`.trellis/spec/core/**`、组织级编码/测试规范、已批准 ADR。
3. **Project knowledge**：项目 `AGENTS.md`、`docs/`、构建/测试入口和目录约束。
4. **Task intent**：Task Schema 中的目标、范围、验收标准、约束和 base revision。
5. **Role instructions**：Coder/QA/Reviewer 的角色 prompt 和输出 Schema。
6. **Evidence**：当前 attempt 的 artifact、Git diff、测试输出和失败 findings。

高层规则与低层文件冲突时，路由器拒绝运行并把冲突报告为 `BLOCKED`，不能静默选择。

## 3. 来源清单与路由

| 来源 | Orchestrator | Coder | QA | Reviewer |
|---|---:|---:|---:|---:|
| 平台 policy | ✓ | ✓ | ✓ | ✓ |
| 组织/项目规范 | ✓ | ✓ | ✓ | ✓ |
| Task + acceptance | ✓ | ✓ | ✓ | ✓ |
| plan | 生成 | ✓ | ✓ | ✓ |
| 生产代码快照 | 只读元数据 | 相关路径 | 全部候选 | 全部 diff |
| implementation-report | ✓ | 重试时 | ✓ | ✓ |
| qa-report | ✓ | 重试时 | 当前 run 不可自读 verdict 作为授权 | ✓ |
| review-report | ✓ | 重试时 | ✗ | 当前 run 不可修改 |
| 其他 Agent 隐式消息 | ✗ | ✗ | ✗ | ✗ |

## 4. ContextBundle 结构

```json
{
  "context_id": "ctx_01J...",
  "task_id": "task_...",
  "role": "qa",
  "source_revision": "a1b2c3d",
  "sections": [
    {"name": "policy", "uri": ".trellis/spec/core/contracts.md", "sha256": "...", "tokens": 1200},
    {"name": "task", "uri": "tasks/task_...json", "sha256": "...", "tokens": 800},
    {"name": "diff", "uri": "git://a1b2c3d..candidate", "sha256": "...", "tokens": 2600}
  ],
  "redactions": [],
  "budget": {"max_input_tokens": 12000, "reserved_output_tokens": 4000},
  "built_at": "2026-08-31T12:00:00Z"
}
```

每个 section 都有 URI、SHA-256 和 token 计数。相同输入应得到相同 section 顺序和相同 manifest（时间戳除外），以便重放。

## 5. 构建算法

1. 读取 Task 并验证 repository/base revision；
2. 加载适用的 Trellis spec index，按 glob 选择相关规则；
3. 根据 role 路由表选择目录和 artifact；
4. 计算 Git diff、测试清单和上游 evidence；
5. 去除 secrets、超出 allowlist 的路径和超过预算的内容；
6. 生成 ContextBundle manifest，持久化后才启动 Agent；
7. Agent 返回后把 manifest ID 写入 artifact，保证“用过什么上下文”可追溯。

## 6. 注入防护

- 仓库文件中的指令按“数据”处理，不得覆盖 system/policy section；
- Task 中要求越权、修改 verdict、跳过测试的文字必须被标记为不可信输入；
- shell 输出只作为 evidence，不可成为新的系统指令；
- prompt 模板使用明确的分隔符和 section 标签，拒绝隐式拼接；
- 发现疑似 prompt injection 时，继续执行只读分析并在 artifact 中记录，或直接 `BLOCKED`，由策略决定。
