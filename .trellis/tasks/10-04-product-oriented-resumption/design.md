# 工程中断续跑与产品状态设计

## 决定

采用现有 Dispatcher/Worker/Runtime/TaskOrchestrator，增加普通 Coder 的事实与 admission 接入。不重写状态机，不把终态重开，不把 UI 当执行控制器。新普通 Task 冻结 InterruptionContinuationPolicy v1，旧 Task 缺字段完全保持原语义。

## 契约与数据流

`Task.interruption_continuation_policy` → production dispatch 重算 → Worker claim → native Coder → bounded workspace final-state inventory +可信进程组停止事实 → `ExecutionInterruptionReceipt`（非角色artifact）→ TaskOrchestrator正确工作/transient记账 →新 RoleRunBoundary→原子队列finish(next_step)→新claim→`ContinuationAdmission`（policy授权、一次消费）→同worktree新Coder →候选→独立QA/Review。

接口：

```python
InterruptionContinuationPolicy.policy_sha256: str
capture_mutation_inventory(root: Path) -> WorkspaceMutationInventory
changed_mutation_paths(before, after) -> tuple[str, ...]
FileContinuationStore.initialize(root, *, task_id) -> FileContinuationStore
FileContinuationStore(root, *, task_id)  # read-only, no implicit mkdir
FileContinuationStore.put_receipt(receipt) -> ExecutionInterruptionReceipt
FileContinuationStore.receipt_for_task(task_id) -> ExecutionInterruptionReceipt | None
FileContinuationStore.put_admission(admission) -> ContinuationAdmission
CoderInterruptionControl.prepare(request, root) -> str | None
CoderInterruptionControl.started(request, root) -> WorkspaceMutationInventory | None
CoderInterruptionControl.finished(request, root, *, before) -> None
CoderInterruptionControl.interrupted(request, root, *, before, cause,
    original_error_code, process_stop: NativeProcessStop | None,
    output_present: bool) -> InterruptionObservation
InterruptionRetryControl.resume(task, repository) -> int | None
InterruptionRetryControl.next_attempt(task, result, repository) -> int | None
```

构造 seam 仅由 production composition 持有，模型没有 store/fs/shell/Task mutation authority。初始检查不再把任意dirty flag当许可：只有精确 receipt + 当前Task/权限/预算+新claim匹配才能进。

Receipt绑定scope、原request/claim、frozen Task intent、policy、退出原因、停止证明hash、完整CapturedChanges、包含ignored的前后inventory、实际变化路径与SHA。最多一次，first Coder attempt1、无candidate/accepted delivery output、同HEAD/branch。库存是有界最终文件状态核验，不是OS级预防性沙箱或完整系统调用追踪；拒绝不可证明能力和unsupported变化，不扩大native CLI权限。已允许的编译/pytest缓存为明确capability内部输出，protected/denied优先，不允许借cache写规范。

新 admission绑定receipt/policy、全新request/WorkItem/Lease并写前重验；不同run不能重放已经消费的许可。脏中断返回 WORK_INTERRUPTED/FAILED/nontransient，普通同Run模型fallback不会发生。本地窗口消耗工作额度，明确provider错误按原typed transient记账；不造进度、不退款未知中断。

## 状态与产品交互

Task保持交付checkpoint；新Run通过既有队列重新领取。无法安全自动继续时明确工程责任与停止/等待条件；业务知识与验收变化才交产品。新增typed DeliveryExecutionView是只读投影，来自queue/receipt/gap routing，不用消息文本裁决；阶段和实际执行状态分离，技术批准置工程详情。真实心跳缺失不推断停机。

## 删除现有 K1

用户最新指示：不重新建需求。复用现有正式DELETE_REQUIREMENT/RequirementRetirementStore，修复精确重放、新建自动复活旧tombstone及活跃Lease拒绝。read-side已按删除事实过滤；native/recovery入口同样拒绝deleted parent。删除是产品事实的正式retirement，不改历史artifact/event或删除dirty worktree。部署验证后root对两个精确ID执行，不直接SQL。

## 验证矩阵

Good：可信停止+合法text草稿+原policy/HEAD+剩余额度→同Task/branch新Run/claim；最终独立同SHA验收。
Base：旧Task缺policy/普通clean transient/progress仍遵循原执行契约，所有旧digest不变。
Bad：dirty→transient→同Run换模型、伪造CoderProgress、HEAD漂移/ignored规范误改、live锁、缺停机证明、重复admission/新run重放、预算不足→无模型调用。

测试先覆盖mutation inventory、安全capture、receipt模型/私有store、Codex失败与fallback、runner预算、新Worker、公开 Start → Reply → Approve 交付组合；UI queue/wait/heartbeat/API/DOM；删除正向、跨project、stale、活跃claim、重放和复活负例。仅增量，无全量。
