# T032 统一项目接单与可恢复串行交付

## 阶段目标

把 T029 prepare、T030 Product confirmation、T031 Designer/Planner/dispatch 与既有
Coder→QA→Reviewer Delivery 组合成一个 Project Manager application facade。单次业务输入只包含绝对
项目目录和需求；内部 Runtime 路径由外置 organization/project workspace 组合。

## 已完成

- 新增 `ase project start/reply/approve/resume/status`，只暴露项目、需求、Product 消息与 exact
  checkpoint 等业务字段；未绑定 application host 时稳定 fail closed，不使用隐式 fake；
- 新增 `UnifiedProjectEntryService` 和 provider-neutral `ProjectDeliveryBackend`，固定推进
  prepare→Product gate→Designer→Planner→dispatch→serial delivery；
- 新增 immutable `ProjectDeliveryIntake`。它在 Product 原生事实出现前保存目录、标题、需求和原始时间，
  因此 PREPARING/PRODUCT_DISCOVERY 中断后也可用 `resume` 精确重放；
- 新增 append-only `ProjectDeliveryCheckpoint` chain，只保存各阶段 native fact references/digests、
  attempt、next action 和安全失败摘要；stale human checkpoint、changed replay、tamper、gap、symlink/path
  drift 均拒绝；
- 新增 `DispatchTaskMaterializer`，把原子 Dispatch 的 NEW Task intent exact-create-or-compare 到
  TaskRepository；已推进 Task 只忽略合法的 status/attempt/event revision，不接受 immutable collision；
- 新增 `ExecutionPlanAgentAdapter`，把已批准组织计划机械转换成 Delivery `PlanArtifact`，不二次规划；
- 新增 `DispatchRoleWorktreeCoordinator` 和严格 worktree recovery：Coder 从 frozen base SHA 工作，QA 与
  Reviewer 在相同 candidate SHA 的独立 detached worktree 验证；Agent/model/allocation drift 在 checkout
  前拒绝，dirty 现场保留；
- 为目标项目矩阵补充无依赖 CMake/C++ fixture，并以 Python、Java、C++ 验证目录+需求→Product
  approval→DONE；目标项目 tree 不被 sidecar/checkpoint 污染。

## 关键不变量

1. Intake、checkpoint 和 native stage records 是组织事实；恢复不依赖进程内 Agent 记忆。
2. ProductSpec 的 exact human approval 是正常业务流程唯一人工门禁；安全冲突仍可进入人工处理。
3. ExecutionPlan 不含 concrete allocation；Delivery bridge 只能消费 T031 dispatch，不能重新选 Agent/model。
4. Coder、QA、Reviewer 的 Git 环境互相隔离；QA/Reviewer 只验证同一 immutable candidate commit。
5. 统一入口不会 merge/deploy，不启动 daemon，不引入单 Task DAG、消息队列或向量库。

## 验证范围

- CLI business-only surface 与 unconfigured-host safe error；
- intake/checkpoint exact replay、hash chain、tamper/path/root swap 和 Product-start interruption resume；
- Dispatch Task materialization、Plan lineage 与 collision；
- 真实 Git worktree create/recover、branch/detached/HEAD/common-dir/path drift、dirty preservation；
- Python、Java、C++ unified offline flow，以及既有 Go/TypeScript target delivery regression；
- 全量 pytest、Ruff、strict Mypy、offline build 和 `git diff --check`。

最终命令与数量记录在 `.trellis/tasks/09-02-t032-unified-project-entry/implement.md` 和本阶段集成
提交中。

## 当前边界

T032 完成的是可恢复 application/CLI facade、native-fact bridge、严格 Git/worktree consumer seam 与
deterministic fake-team E2E。仓库不会为生产默选模型、凭据或 fake Agent；部署宿主必须一次性调用
`configure_project_entry(...)` 绑定实际 organization-owned team composition。已有 delivery
`OpenAICompatibleAgentAdapter` 仍只产出 typed artifact；让真实模型通过受控工具实际修改任意项目、以及
生产 provider adapters 的完整宿主装配，是实用化阶段，不应被本次 fake-agent 验收冒充为已完成。

T033 Reporter 保持暂停；不因 T032 完成而自动启动。

本记录随 T032 集成提交归档；精确提交可通过
`git log -- docs/archive/2026-09-02-t032-unified-project-entry.md` 查询。
