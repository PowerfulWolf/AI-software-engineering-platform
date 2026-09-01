# CLI 使用说明

T013–T014 将 v0.1 的持久化、评估和串行运行能力组装为 `ase` 命令。CLI 只负责
composition，不绕过 Task、Artifact、StateEvent、EvaluationEvent 或 Handoff 的 typed
contract。

## 默认目录

```text
.ase/state.sqlite3             # Task 快照和 StateEvent
artifacts/runs/                # sealed Artifact JSON
artifacts/evaluation-events/   # EvaluationEvent JSON envelope
artifacts/handoffs/            # Handoff JSON + Markdown
```

所有路径都能通过参数覆盖，适合测试或把运行时目录放到独立 volume。

## 创建和检查 Task

Task 文件必须是 `schemas/task.schema.json` 对应的完整 JSON，并且创建入口只接受
`status=NEW`、`attempts=0`：

```bash
ase task create --file task.json
ase task show task_example_001
ase task events task_example_001
```

三个成功命令都输出可重新解析的 JSON。重复 Task ID、非法 JSON、未知 Task ID 或试图导入
已完成快照都会以退出码 2 失败，不会修改已有记录。

## 重算 Evaluation/ADR

```bash
ase evaluation report case_example_001 \
  --database .ase/state.sqlite3 \
  --artifacts artifacts/runs \
  --events artifacts/evaluation-events
```

报告来自 `EvaluationTraceBuilder + EvaluationEngine` 对 durable facts 的重放。命令不接受
`--adr` 或其他覆盖参数；缺失 CaseStartedEvent、事件损坏或 Artifact 断链会 fail closed。

## 运行 Task

使用 Runtime 配置装配真实 OpenAI-compatible AgentAdapter，并按固定顺序执行
`Orchestrator → Coder → QA → Reviewer`：

```bash
export OPENAI_API_KEY='...'
ase task run task_example_001 --config runtime.json
```

配置中的 `paths.database` 必须指向创建 Task 时使用的同一个 SQLite 文件。API key 不得写入
JSON；只允许通过 `api_key_env` 指定环境变量名。完整字段、role override 和离线 fake 注入
方式见 [`docs/runtime.md`](runtime.md)。

成功输出包含 `case_id` 和 typed retry result；失败输出单行错误并返回退出码 2，不打印
provider secret。`--case-id` 可提供外部评估使用的稳定 case identity。

## 生成 Human Handoff

```bash
ase handoff build task_example_001 \
  --database .ase/state.sqlite3 \
  --artifacts artifacts/runs \
  --output artifacts/handoffs
```

只有 `DONE` 或 `BLOCKED` Task 可以生成 handoff。成功输出包含 `handoff_id`、摘要哈希和
JSON/Markdown 路径；命令不会执行 review command、merge 或修改终态 Task。

## 当前边界

T014 的 `task run` 仍只做单仓库、单 Task、串行 Coder → QA → Reviewer。它不创建复杂 DAG、
消息队列、向量库或容器 sandbox，不自动 merge/deploy；Git worktree 和最终合并继续由
后续 composition/human boundary 负责。CLI 不直接修改状态、verdict、artifact 或执行
merge。
