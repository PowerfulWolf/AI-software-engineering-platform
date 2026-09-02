# T031 PRD：Designer、Planner 与调度 Skills

## Goal

让 Solution Designer 从 approved ProductSpec 产出 TechnicalDesign，让 Planner 基于真实组织容量与
ModelPolicy 产出可行 ExecutionPlan；Planner 只预演，Project Manager commit-dispatch 才提交分配。

## Acceptance Criteria

- [ ] Designer/Planner 成为正式 organization roles，拥有最小 Context/permission/output contract；
- [ ] Designer 不能改写 ProductSpec，TechnicalDesign 精确覆盖 requirement/acceptance IDs；
- [ ] Planner preview Skills 调用 Scheduler/ModelRouter 时无 store 写调用；
- [ ] ExecutionPlan 不含 concrete agent/model/provider/lease，preview evidence 可重放；
- [ ] Project Manager commit-dispatch 使用当前 facts 重新计算，拒绝过期 preview；
- [ ] 只有 typed decision 成功才持久化 Assignment/Lease/ModelSelection 并派生 Delivery Task；
- [ ] 自我分配、容量超限、模型容量不足、跨项目 lineage 全部 fail closed。

## Out of Scope

- 单 Task DAG、后台队列、自动 merge。
