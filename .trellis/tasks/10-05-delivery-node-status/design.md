# 设计

新增共享纯读 `requestNodeExecution(request)` 汇总当前 Requirement、Operation 与角色工作事实，
返回节点展示 state/label；不改原 execution 或任何持久对象。各展示路径消费同一派生值。

优先级为终态、当前等待/中断/失败、待重试、同需求同 Project 上游工作 Operation、有效角色
claim、队列与 UNKNOWN。不得从 Task 阶段单独声明执行。保留 currentRequestTasks 与当前失败
角色 gate 的既有优先规则。

流程位置仍来自 durable stage 与当前任务；节点动作来自共享 helper。完成显示 done 绿、当前
执行 current 蓝、阻塞 blocked 红、等待 paused 灰；补充文字和 aria-current。原 execution
UNKNOWN 留在“执行事实状态”工程详情，流程节点可以在真实 Operation 支持下显示本轮执行中。

当前候选验证 `VERIFY_QA/VERIFY_REVIEW` 的 gate 优先于父 INTEGRATING。旧 reader-shaped
验证记录没有 role_queue/执行证明时保持灰色，不能以父 Operation 证明独立验证已开始。
QUEUED/CONTINUE_REQUIRED 即使保留旧 RUNNING claim，也在恢复到 IMPLEMENTING 前保持灰色。
合法正在处理的最后一次工作预留不因 attempts 达到上限被预算单独染红；预算、recovery、
recheck、精确审批及旧操作失败仅在没有合法当前执行时形成节点阻塞。
