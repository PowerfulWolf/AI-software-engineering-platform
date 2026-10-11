# 设计

## 最小变更

`knowledge_phase_timeout(role, timeout_seconds)` 继续作为 Native context 与 structured
client 的唯一知识窗口 seam，直接返回调用方已准入的有限窗口，不另设 Delivery 上限。
不创造额外重试、不重新解释本地窗口为 provider outage，也不改变原 Task 的冻结策略。

`CODER_KNOWLEDGE_FAILURE_REASONS` 增加应用编排器已经真实生成的精确字符串
`TRANSIENT_INFRA: coder knowledge preparation reached local time limit`。
不使用 substring、前缀匹配或任意 TIMEOUT 接纳；其余来源与停止/现场验证代码保持不变。

真实 route 保存的是封存前 provisional artifact；`SerialOrchestrator._invoke` 随后写入
带平台校验摘要与时间的 immutable accepted artifact。`read_terminal_workspace_snapshot`
已通过独立 reader 验证二者来源和封存，成功进度比较应使用 `artifact_digest`，仅排除循环
integrity 元数据。显式要求 `accepted_progress` 为 `CoderProgressArtifact`，并继续检查原
run/source、停止、重复 source reader；正文/Task/Context/producer 等变化仍拒绝。

## 可信事实边界

已接纳进度必须来自成功 Coder route，且 `checkpoint_sequence` 对齐前一 execution attempt。
事件尾序列严格为 `IMPLEMENTING → CONTINUE_REQUIRED → QUEUED → IMPLEMENTING → BLOCKED`，
前一 attempt 与当前 attempt 相邻，四项全部保持 Task/source/artifact 身份。无 candidate，
当前 terminal summary 必须与 blocked reason 对齐。后续 provider route、活跃 claim/worker、
完整现场漂移继续由既有独立 gate 拒绝；新增原因本身从不构成执行授权。

## 测试策略

先调整窗口契约测试并新增本地原因测试，运行纯离线非 MySQL 目标获得红测；再实现。
加入精确原因和事件/route/progress/source/candidate 负向矩阵，避免放宽来源判断。
MySQL 仅扩充既有参数用例，以 typed `StructuredModelError(TIMEOUT,
timeout_kind="local_execution_limit")` 触发生产编排的真实历史原因，不手造 route 或停止记录。
旧参数 fixture 的 `finish_change` 占位步骤在现代 slice gate 下非法；仅该用例 wrapper 从
真实 `request.work_slice` 继承已完成与完整剩余步骤，不造完成事实。公开入口每次接纳一个
串行 Worker 结果后，用有界 `entry.resume` 进入下一轮；不把 DELIVERING 映射为 BLOCKED。
历史 terminal 知识失败参数的源 Host 使用公开 product-only `LocalOperatorPrincipal`，从首次
dispatch 自然生成无 engineering_policy 的冻结来源；默认双职责新任务仍按当前规则等待。
恢复使用新的可信工程主体 Host，经正式精确审批入口，不修改源 Task/dispatch 的权限或策略。

root 负责共享 spec 同步、独立审核、提交、部署及原 Requirement 后续公开流程操作。
