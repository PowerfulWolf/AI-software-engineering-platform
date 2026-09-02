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

## 统一项目接单

T032 提供面向 Project Manager 的业务入口；一次接单不再要求用户手工传 database、artifact、context
或 worktree 路径：

```bash
ase project start /absolute/path/to/project \
  --requirement "Add the approved feature"

ase project reply delivery_xxx \
  --checkpoint <current-checkpoint-sha256> \
  --message "The expected behavior is ..."

ase project approve delivery_xxx \
  --checkpoint <current-checkpoint-sha256>

ase project resume delivery_xxx
ase project status delivery_xxx
```

`start` 自动 prepare/reopen 外置 project sidecar，并运行一个有界 Product turn；它在需要澄清或
ProductSpec 等待批准时返回 checkpoint。`reply` 和 `approve` 都必须引用 exact current checkpoint，
旧页面或重复命令不能覆盖新事实。批准后 Project Manager 自动推进 Designer、Planner、dispatch 与
现有串行 Delivery；进程中断后使用 `resume`。

`ase` 的 application host 必须在启动时通过 `configure_project_entry(...)` 绑定 organization-owned
team composition，包括 Agent adapters、policy 和平台 workspace root。这是一次部署配置，不是每个需求
都要用户拼装的参数；未绑定时命令以退出码 2 fail closed。仓库的 offline E2E 使用 deterministic fake
team 验证完整组合，不把 fake 隐式设为生产默认值。

## 当前边界

T014 的 `task run` 仍只做单仓库、单 Task、串行 Coder → QA → Reviewer。它不创建复杂 DAG、
消息队列、向量库或容器 sandbox，不自动 merge/deploy；Git worktree 和最终合并继续由
后续 composition/human boundary 负责。CLI 不直接修改状态、verdict、artifact 或执行
merge。

`project` 入口也不会自动 merge/deploy，且不会把 fake Agent 当作真实团队。生产宿主需要明确绑定
真实 provider/team composition；Provider 的 secret 仍只来自宿主环境，不写入 checkpoint、sidecar
或 CLI 输出。
