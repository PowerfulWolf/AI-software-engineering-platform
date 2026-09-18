# T047 — 建设面向复杂需求的 Planner Agent

## Goal

保留 Planner“提出执行方案”、Manager“复核并授权执行”的职责边界，将当前固定的
`Coder → QA → Reviewer` 三阶段草案扩展为面向复杂需求的真实任务规划能力。Planner 应能够基于
已批准的 Product Spec、Technical Design、项目基线和组织能力，规划模块、工作步骤、依赖、风险、
测试矩阵和执行顺序；Manager 仍独占具体 Agent/模型选择、资源预留、状态迁移、恢复和最终交付权。

简单需求不得强制消耗一次 Planner 模型调用。Product 和 Designer 只提供需求范围、验收标准、组件、
接口、数据变更和风险等结构化事实；Manager 拥有的确定性 `PlanningGate`/`ComplexityClassifier` 根据
这些事实决定走快速计划还是调用 Planner Agent。Planner 不得决定自己是否被调用。系统只在复杂度、
风险或依赖达到明确阈值时调用 Planner Agent。

## Acceptance Criteria

- [ ] 由 Manager 的确定性 `PlanningGate`/`ComplexityClassifier` 负责简单/复杂需求分类；Product、Designer
      只提供结构化事实，Planner 不参与路由自身；
- [ ] 定义可测试、版本化的分类输入、规则、理由码和决策结果；相同事实必须得到相同分类；
- [ ] 至少覆盖多 Repository/模块、工作包依赖、数据库迁移、接口兼容、数据回填、安全、性能、并发、
      中高技术风险和多组集成测试矩阵等复杂条件；
- [ ] 人工可以把简单需求升级为复杂规划，但不得把规则判定为复杂或高风险的需求强制降级；升级决定
      必须作为不可变审计事实持久化；
- [ ] 简单需求通过确定性计划生成器产出最小 `Coder → QA → Reviewer` 计划，零模型调用；
- [ ] 复杂需求的 Planner 输出包含模块、工作步骤、依赖、风险、测试矩阵、执行顺序和检查点；
- [ ] 计划能够表达多个有界工作包及其依赖，但不得直接写入具体 Agent、provider、model、Assignment 或 Lease；
- [ ] Planner 只能读取 Scheduler/ModelRouter preview，不得持有数据库写口、Lease 或调度提交权限；
- [ ] Manager 使用当前事实重新校验计划、容量、模型能力和依赖后，才可以原子提交 dispatch；
- [ ] Product Spec 的验收标准不可被 Planner 改写、删除或弱化；每个工作包和测试项必须可追溯到验收标准；
- [ ] Planner 被打回后，新版本必须引用前一计划和结构化反馈，旧计划保持不可变；
- [ ] 进程重启后能够从 durable Planner run/plan/checkpoint 恢复，不能依赖模型会话记忆；
- [ ] 覆盖简单快速计划、复杂串行计划、合法有界并行、依赖环、验收覆盖缺失、容量漂移和越权分配测试。

## Non-goals

- Planner 不负责选择具体 Agent 或模型；
- Planner 不负责持有队列轮询、数据库锁、Lease 心跳或超时回收；
- Planner 不负责修改代码、执行 QA、作出 Review verdict 或最终交付；
- Product、Designer 和 Planner 均不得覆盖 Manager 的复杂度分类或绕过 Planning Gate；
- 本任务不授权无限 DAG、跨需求共享可变工作区或绕过 Manager commit-dispatch。

## Design Decision

Planner 与 Manager 保持独立：Planner 是无执行权限的计划提出者，Manager 是团队 Leader 和唯一执行
授权者。若后续发现复杂需求规划仍可完全由确定性规则覆盖，应保留该权限边界并允许取消生成式
Planner，而不是让 Manager 同时生成并批准自己的计划。

复杂度路由同样属于 Manager 的 policy-bound Skill，而不是 prompt 判断。分类输出至少包含规则版本、
输入事实摘要、`SIMPLE`/`COMPLEX` 结论和理由码；简单路径的快速计划与复杂路径的 Planner 计划都必须
经过同一个 Manager commit-dispatch 校验边界。
