# CLI 使用说明

T013 将 v0.1 的持久化和评估能力组装为离线 `ase` 命令。CLI 只负责 composition，不绕过
Task、Artifact、StateEvent、EvaluationEvent 或 Handoff 的 typed contract。

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

T013 没有添加 `ase task run`：真实 Agent 运行仍由应用层装配 `RetryingOrchestrator`、
`AgentAdapter`、ContextStore 和 Git workspace。这样 CLI 可以先稳定地消费和复核事实，
不会把 provider 凭据、工作树写权限或状态迁移逻辑藏进入口脚本。
