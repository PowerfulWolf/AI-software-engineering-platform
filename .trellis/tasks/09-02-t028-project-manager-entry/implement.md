# T028 Implementation

## Scope

实现 ProjectPreparation、ProjectRequest、ProductSpec/Approval、TechnicalDesign、ExecutionPlan 的
typed contract、integrity、跨阶段 guard 与 Delivery Task 派生函数。Project Manager Agent Skills、
真实上游 AgentAdapter 和 CLI 入口分别由 T029–T032 接续。

## Verification strategy

1. 先写 stage contract 与 JSON Schema 正反例；
2. 验证 exact Product Spec 用户审批门禁；
3. 验证 Design 全覆盖与串行 Execution Plan；
4. 验证完整 stage chain 才能派生 NEW Task；
5. 运行全量 pytest、Ruff、strict Mypy、offline build 和 diff check。

## Delivered

- 新增六类 frozen stage documents、canonical SHA-256 和 Draft 2020-12 wire contracts；
- 用户 Approval 绑定 exact ProductSpec version/digest，REQUEST_CHANGES 不能解锁 Designer；
- TechnicalDesign 精确覆盖 requirement/acceptance IDs；
- ExecutionPlan 固定 Coder→QA→Reviewer，只表达 capability/risk/BrainTier demand；
- 完整 stage chain 才能派生保留 exact acceptance criteria 的 NEW Task；
- Project sidecar `assignments/` 架构重置为唯一初始 layout v0.1，不保留未使用的迁移语义；
- 建立 T029–T033 可执行任务。
