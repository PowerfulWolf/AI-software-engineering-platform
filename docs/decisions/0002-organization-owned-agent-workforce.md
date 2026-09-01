# Organization-owned Agents and run-scoped model allocation

Agent 是组织拥有的长期团队成员，Project 只拥有工作、规范、访问授权和执行记录；Task 通过
Role Assignment 与有期限的 Task Lease 使用 Agent 容量。每个 Assignment 的实际执行必须创建
隔离 Agent Run，具体模型由组织级 Model Policy 按任务风险、复杂度、角色和客观升级信号选择，
不永久写入 Agent 身份。

TaskOrchestrator 继续保证单个 Task 内 `Coder → QA → Reviewer` 串行和独立裁决；独立的
PortfolioScheduler 可以在容量允许时并发推进多个 Task，但不能共享可变 Context、worktree 或
隐式会话。同一 Task 的 Coder 与 QA/Reviewer 不得是同一 Agent；高风险任务可以进一步要求
不同模型或供应商以降低相关性错误。

调度可用性与交付状态是两个正交生命周期。`WAITING_HUMAN`、`WAITING_DEPENDENCY` 和
`RETRY_SCHEDULED` 属于 WorkItem，进入等待必须释放或允许 Task Lease 到期；Task 保留最近的
交付 checkpoint。`BLOCKED` 只保留给没有安全继续路径、预算终局耗尽或需要结束本次交付的
情况。

项目 sidecar 因此保存 `assignments/` 而不是 `agents/`。AgentProfile、ModelPolicy、团队绩效和
全局 WorkQueue 存放在组织 workspace；项目只能保存 project-specific access/policy override 和
Assignment/Run 事实。现有 `AgentDefinition` 暂时保留为从 AgentProfile、Assignment、
ModelSelection 和 Project policy 解析出的单角色运行配置，以兼容当前串行 Runtime。

拒绝的方案是为每个 Project 复制一套 Agent，以及让一个长驻 Agent 会话同时携带多个 Task 的
可变上下文：前者使组织能力和绩效碎片化，后者会造成上下文串扰、权限泄漏和不可重放行为。
