# CLI 使用说明

正常用户入口是 `ase project ...`：Production Team Host 自动从 `ASE_CONFIG`/默认配置和环境变量装配
MySQL、组织团队、模型路由、项目 sidecar 与 worktree。`ase task ...`、`ase evaluation ...`、
`ase handoff ...` 是保留给平台开发、兼容测试和诊断的低层命令。CLI 不绕过 Task、Artifact、
StateEvent、EvaluationEvent 或 Handoff 的 typed contract。

## 统一项目接单（推荐）

完成一次 [`production-setup.md`](production-setup.md) 配置后：

```bash
ase project start /absolute/path/to/project \
  --requirement "Add the approved feature"

ase project reply delivery_xxx \
  --checkpoint <current-checkpoint-sha256> \
  --message "The expected behavior is ..."

ase project approve delivery_xxx \
  --checkpoint <current-checkpoint-sha256>

ase project status delivery_xxx
ase project resume delivery_xxx
```

`start` 自动 prepare/reopen 外置 project sidecar、发现项目规范并运行一个有界 Product turn。`reply` 和
`approve` 必须引用 exact current checkpoint；旧页面或重复命令不能覆盖新事实。批准后 Project
Manager 自动推进 Designer、Planner、dispatch 和 `Coder → QA → Reviewer`。进程中断后用 `resume`
重算 durable facts 并继续。

未调用测试注入的 `configure_project_entry(...)` 时，CLI 会惰性创建
`OrganizationTeamHost.from_environment()`；缺配置、MySQL 不可达、`live_model_execution=false` 或模型
路由不可用时返回退出码 2，绝不回退 fake Agent，也不会输出 DSN/API key。

成功时返回 `checkpoint.stage=DONE` 和 `checkpoint.candidate_revision`。CLI 不自动 merge/deploy；目标
项目主 checkout 不变。完整首次配置、返回值和候选复核方法见
[`production-setup.md`](production-setup.md)。

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

`project` 入口也不会自动 merge/deploy，且不会把 fake Agent 当作真实团队。Provider secret 只来自
宿主环境，不写入配置、checkpoint、sidecar 或 CLI 输出。SQLite 默认目录仅属于低层兼容命令；Production
Team Host 固定使用 MySQL。
