# T030 Design

## Boundary

`AgentRole` 继续只表示 Delivery runtime 的 `orchestrator/coder/qa/reviewer`；新增
`OrganizationRole` 表示长期团队岗位。`AgentProfile.eligible_roles` 使用组织岗位，因此 Product、
Designer 与 Project Manager 可以成为正式团队成员，而不会进入现有 Artifact/Task 状态机。

Product Agent 使用独立的 `ProductAgentAdapter`，不伪造 Delivery Task，也不复用依赖 Task 的
`AgentAdapter`/`ContextBundle`。Product Agent context 直接携带并校验完整的 `ProjectProfile` 与
`ProjectSpecBaseline`，不能只传无内容的 digest；同时只读 preparation、request 和已确认对话。
唯一业务输出是 clarification 或 `ProductSpec`；没有代码写权限、状态迁移权限或审批权限。

## Durable records

- `ProductDialogueRecord`：按 sequence 与 previous digest 形成不可变对话链；人类和 Product Agent
  的发言均成为组织事实。
- `ProjectRequestRevision`：保存 request 状态变化，不覆盖旧版本。
- `ProductDiscoveryCheckpoint`：保存当前 request revision、dialogue head、当前 spec、审批和状态，
  是进程重启后的恢复入口。
- `ProductSpec`/`ProductSpecApproval`：沿用跨阶段领域契约并写入不可变 store。

文件 store 发布采用 root-relative dirfd、`O_NOFOLLOW` 与 create-exclusive/hard-link 语义；相同 ID +
相同内容是幂等 replay，相同 ID + 不同内容是冲突。外部结果校验后的第一个 durable write 是包含完整
effect bundle 的 operation receipt，随后发布 effects 和作为提交点的 checkpoint；重放从 receipt
补齐中断写入，不再次调用已完成的外部端口。

## Public flow

1. `start` 校验 exact `ProjectPreparation`，创建 `PRODUCT_DISCOVERY` request 与初始 checkpoint。
2. `record_human_message` 追加用户输入；`run_product` 构建独立 context 并调用 adapter。
3. clarification 只追加对话；ready output 校验完整 acceptance coverage、版本和 supersedes 后持久化，
   request 进入 `WAITING_PRODUCT_APPROVAL`。
4. `decide(APPROVED)` 由独立人类入口绑定 exact spec ID + digest，随后 Project Manager 才能解锁
   `SOLUTION_DESIGN`。
5. `decide(REQUEST_CHANGES)` 记录审批并回到 discovery；下一份 spec 必须 version + 1 且 supersedes
   当前 spec。旧版本永远不能解锁 Designer。

Provider error、timeout、invalid output 与 replay 都不能重复写入决定，也不能改变阶段授权。
