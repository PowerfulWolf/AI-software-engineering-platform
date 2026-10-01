# 契约设计

`NativeRecoveryEntry.pending_knowledge_wait(path) -> NativeRecoveryExecution | None` 只读检查已派发 recovery 的唯一当前队列知识等待；当前无知识等待返回 None，缺失或不匹配 durable proof 拒绝。`resume_execution` 首次捕获和重启使用同一验证；Controller 在 interruption 路径前接回该等待。

队列绑定原 dispatch SHA，step boundary 绑定当前 Task revision/role/attempt/source revision。Gap 验证 Task/Team/Project/Requirement/Repository/role/revision，route digest 精确对应 wait_reason，context 和 manifest 绑定原知识 run。不得选择第一个历史 gap 或将任意 IMPLEMENTING 当作可恢复中断。非知识等待不触发新执行。

读投影保留 Task IMPLEMENTING checkpoint，但 blocker/next_action 从当前 WAITING_HUMAN 或 WAITING_DEPENDENCY 队列投影；Requirement 呈现同一等待状态，清旧 coordination。GET 无写入。

Good：批准 recovery 的 Coder 在知识准备暂停，接回同 Task，批准答案后原队列新 claim 执行。Base：现有 QA/Review wait 保持。Bad：旧 gap、跨 Project、错 route/step/revision、活跃租约、未知 Task 均不得接管。
