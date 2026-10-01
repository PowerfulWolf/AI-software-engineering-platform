# 设计

`accepted_scope_progress(sidecar, task, events, source_revision)` 从已验证 StateEvent 序列
选择最新 exact progress acceptance，读取 sealed artifact、其 producer Run 的完整连续
route history 和 Context。所有身份、attempt、revision、artifact digest 和 acceptance
event 必须一致。最新接纳事实不合法时 fail closed，不能倒退尝试旧事实。

NativeRecoverySource.accepted_progress 仅作为 RecoveryScopeRequest 的身份依据；
RecoverySource.failed_run_id/failed_context_id、实际 worktree capture、恢复模型和双审批
完全不变。后续失败执行可以改变 dirty bytes，绝不能用旧progress的changed_files覆盖
真实dirty inventory。已有 pre-provider continuation source 特例仍执行原 stopped gate。
