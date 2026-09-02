# T031 Implementation

## 已实现

- [x] 新增 task-free Designer Context、最小权限、provider-neutral adapter/fake 和完整输出守卫；
- [x] Designer journal-first 保存预期 effects，追加 TechnicalDesign 与 `PLANNING`
  ProjectRequestRevision 时使用 expected-predecessor CAS，最终发布 DesignCommitCheckpoint；
  Agent-window revision drift 与中断重放均 fail closed，不重复调用外部端口；
- [x] 新增 Planner Context、adapter/fake、durable run receipt/checkpoint、append-only ExecutionPlan
  store 和 `READY_FOR_DELIVERY` request revision；调用 Agent 前后都检查 current revision；
- [x] Planner Preview 只调用纯 Scheduler/ModelRouter，无 write port；快照绑定 Task、WorkItem、
  ExecutionPlan、三阶段 RunDemand、Agent/Lease/Assignment/ModelPolicy；
- [x] Project Manager commit-dispatch 验证 exact durable READY revision/Planner run/plan/checkpoint，从
  authoritative authority 读取 current facts，重新计算 Coder/QA/Reviewer 分配并在最终窗口 CAS；
- [x] `SqliteDispatchAuthority` 使用 Product revision fence + `BEGIN IMMEDIATE` 在同一提交围栏内
  重验完整 Planner handoff、CAS workforce snapshot，并原子保存三组 Assignment/Lease；
- [x] 三阶段全部成功后才单次原子保存 DispatchCommitRecord；任何 capacity、self-review、model、
  stage 或 drift 错误均 zero partial writes；
- [x] 新增 Designer/Planner/Preview/Dispatch 的 6 份 Draft 2020-12 Schema 和正反 contract tests；
- [x] 更新项目 code-spec、README、milestones、contracts 和阶段 archive。

## 验证

- [x] T031 相关定向测试：145 passed；
- [x] 全量 pytest：579 passed；
- [x] Ruff check：all checks passed；
- [x] Ruff format：375 files checked；
- [x] strict Mypy：199 source files, no issues；
- [x] offline sdist/wheel build：成功；
- [x] `git diff --check`：通过。

## 当前边界

- DispatchCommitRecord 是 NEW Task 与三角色分配的原子 bundle，尚未启动 Delivery runtime；
- T032 负责统一项目入口、durable stage resume、TaskRepository/Runtime composition 和
  Python/Java/C++ E2E；
- T033 Reporter 按约定暂停；不引入自动 merge/deploy、daemon、DAG、向量库或消息队列。
