# CLI 使用说明

## 团队工作台

`ase team serve --port 8765` 使用同一生产配置，在 http://127.0.0.1:8765 提供当前公司的只读团队、
多目录需求和任务详情。每 5 秒自动刷新，不初始化 workspace/schema、不调用模型、不修改交付。
配置错误/端口占用返回 exit 2；数据不可用显示明确错误，不能被解释成没有任务。
详见 [工作台说明](visualization.md)。

正常用户入口是 `ase request ...`，旧 `ase project ...` 保留兼容：Production Team Host 自动从 `ASE_CONFIG`/默认配置和环境变量装配
MySQL、组织团队、模型路由、项目 sidecar 与 worktree。`ase task ...`、`ase evaluation ...`、
`ase handoff ...` 是保留给平台开发、兼容测试和诊断的低层命令。CLI 不绕过 Task、Artifact、
StateEvent、EvaluationEvent 或 Handoff 的 typed contract。

## 统一项目接单（推荐）

完成一次 [`production-setup.md`](production-setup.md) 配置后：

```bash
ase request create /absolute/path/to/backend /another/path/to/frontend --name "Order cancellation"

ase request discuss delivery_multi_xxx \
  --checkpoint <current-checkpoint-sha256> \
  --message "The expected behavior is ..."

ase request approve delivery_multi_xxx \
  --checkpoint <current-checkpoint-sha256>

ase request status delivery_multi_xxx
ase request resume delivery_multi_xxx
```

`create` 先 prepare 全部目录并停在 READY_FOR_DISCUSSION，不调用模型；目录可以只传一个。
`discuss` 运行一个有界 Product turn；`discuss/approve` 必须引用 exact current checkpoint，旧操作
不能覆盖新事实。批准联合产品后自动推进 Designer、Planner、每仓 dispatch 与 Coder→QA→Reviewer，
最后在完整候选集合执行联合验收。进程中断后 `resume` 重算 durable facts 并继续。
联合结果在 `checkpoint.children/integration/next_action`，不会自动合并候选。
旧 `ase project start DIR... --requirement TEXT` 仍支持一步式接单。

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

## 显式接手失败 Coder 的保留修改

若 Coder 已生成候选提交，下面的命令不适用；请使用下一节的 `verify-*` 命令。不要重置终态或
重新运行 Coder 来代替候选复核，原候选和失败历史必须保留。

仅用于已停止、尚未产生 candidate 的失败 Coder。先保存现场；不要 reset、stash 或修改旧终态。
原方案必须仍适用，目标项目需处于干净的、已包含平台修复的基线。

```bash
ase recovery propose --project /absolute/project --delivery delivery_ID \
  --run run_ID --context ctx_ID
# 上条输出 plan_file；先查看，再由人类明确批准输出的完整 plan_sha256。
ase recovery inspect --plan /absolute/sidecar/state/recovery-delivery_ID/plan-SHA.json
ase recovery approve --plan /absolute/sidecar/state/recovery-delivery_ID/plan-SHA.json \
  --confirm FULL_PLAN_SHA --reference human-approval-reference
ase recovery run --plan /absolute/sidecar/state/recovery-delivery_ID/plan-SHA.json
# 另一个终端只读查看新的 Task 阶段（不重新 prepare 或执行）：
ase recovery inspect --plan /absolute/sidecar/state/recovery-delivery_ID/plan-SHA.json --runtime
```

沿用 `ASE_CONFIG`、配置中指定的 MySQL DSN 环境变量及已登录 Codex；配置必须允许真实模型运行，
且本版恢复仅支持一条 Codex route。提案/检查/批准都不调用模型；`run` 才执行新的串行角色。

如果旧补丁与新基线冲突，可以重新提案时加 `--coder-reapply`，然后批准**新计划**：

```bash
ase recovery propose --project /absolute/project --delivery delivery_ID \
  --run run_ID --context ctx_ID --coder-reapply
```

这个模式不会先应用补丁：Coder 从干净的新基线开始，收到完整旧补丁并自行适配、处理代码冲突。
省略该选项仍使用原来的 Git 自动继承，冲突即停止；不会静默切换模式。旧批准不能授权新模式。
补丁只传给 Coder，内容缺失、变化或超出上下文预算都拒绝启动，不能截断后继续。

`run` 输出新 Task、candidate SHA、artifact/context/run/event IDs 或 BLOCKED 原因；退出码
0 表示 DONE，3 表示本次交付未完成，2 表示入口拒绝。交付分支为 `ai/<新TaskID>/attempt-1`。

复核是独立 QA/Reviewer 完成的，不把已有修改视为实现报告。重复批准精确重放；Coder 一旦获准
调用，重复 `run` 会拒绝并要求检查持久化记录，避免在结果不明时重复消耗模型额度。
若在 seed 写入与 receipt 发布之间中断，保留新旧现场并拒绝盲目重放。旧父/子需求 checkpoint
仍保持原记录；本命令不自动关联联合验收、不 merge/push/deploy，也不重启已失败的新恢复 Task。

## 显式复核已有 candidate

用于原 Coder 已完成 candidate commit，但 QA/Reviewer 因平台故障失败或中断的终态交付：

```bash
ase verify-propose --project /absolute/project --delivery delivery_child_ID
ase verify-inspect --plan /absolute/sidecar/state/candidate-verification-delivery_child_ID/verification-plan-SHA.json
ase verify-approve --plan /absolute/sidecar/state/candidate-verification-delivery_child_ID/verification-plan-SHA.json \
  --confirm FULL_PLAN_SHA --reference human-approval-reference
ase verify-run --plan /absolute/sidecar/state/candidate-verification-delivery_child_ID/verification-plan-SHA.json
```

`verify-propose` 从原生 Task/event/dispatch/artifact 和联合父需求读取当前事实，固定原 candidate、
QA/Reviewer Agent、模型、权限及独立验证 Task；`verify-inspect` 纯只读。前三步不调用模型。
`verify-run` 只调用 QA，再在 QA PASS 后调用 Reviewer；它使用新的 Assignment/Lease/worktree，
但 report 的 Task 和 candidate 仍是原始身份，不创建假 Coder、不重置原 Task、不发布 DONE 事件。

同一计划的每个角色在 provider 调用前先写入不可变 invocation。进程在调用后丢失结果时，该角色
不能自动重跑；先执行 `verify-inspect`。若 invocation 已存在但没有完整报告，使用相同的 project 与
delivery 再执行一次 `verify-propose`，人工批准新的 plan SHA 后运行新计划。它会固定旧失败 run、
分配新的验证 run 并复用原 candidate，不会重跑 Coder。QA FAIL 或 Review REJECT 返回退出码 3，安全拒绝或配置问题
返回 2，只有 QA PASS + Review APPROVE 返回 0 和 `verified=true`。命令不 merge/push/deploy；计划中
绑定的 parent delivery/checkpoint 与 completion 共同保留需求关联，旧 checkpoint 仍保持历史真实。
