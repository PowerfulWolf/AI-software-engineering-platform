# 跨层契约

1. 完整相对路径是文件身份，删除 NativeRecoveryEntry 按 basename 猜测迁移的提案逻辑；历史 RecoveryPathRebinding 保留只读兼容，原有模型不改写。
2. `is_protected_rule_path(path)` 统一检测路径任一 `.trellis` segment；`WorkspacePolicy.authorize_write` 硬拒绝，生产 Task/role 编译去除明确的规范路径。宽 glob 不能覆盖硬拒绝。Codex Coder prompt 明确规范只读与 docs 沉淀。
3. `authorize_capture(path)` 是专用只读历史校验：检查旧 read/write allowlist、显式 deny 和 containment，但不授予执行写权限。只有 `capture_legacy_changes` / `verify_legacy_capture` 使用它；普通 capture/seed/candidate 仍调用硬 write policy。
4. `RecoveryPlan.quarantined_paths: tuple[RelativePath, ...] | None` additive、absence 保持历史 digest。非空时必须等于 capture 中所有受保护路径、sorted/unique、`input_mode=coder_reapply`、target policy 不含明确受保护路径。Native facts 从完整现场重新发现、双读校验，授权服务验证 audit capture。普通 plan 不能包含受保护 capture。
5. Native proposal 自历史已授予 allowlist 只读封存全部改动，明确隔离 `.trellis` 后以 current target policy 继续。scope supplement 不能批准新的受保护路径；历史本已误授权且 changed 的规范路径只进入审计。
6. RecoverySeedService 的 reapply 路径保持干净新 worktree；Context 要求完整旧补丁，并强调隔离路径禁止重用、知识改动放在已授权 docs。Task 范围使用 target policy。审批 facts 显示隔离路径和模式。

## 验证矩阵

Good: 新 learning_collection/audit.py 与既有 knowledge/audit.py 并存，计划保留新路径；legacy 规范改动保留完整 patch，新 Task 在相同 Requirement 串行完成。
Base: 无规范改动的旧 plan/approval digest 保持；普通 recovery capture/seed 不变。
Bad: 未授予或显式 deny 的规范路径、漏隔离/伪造隔离/非 reapply/target 明确允许规范、stale source/target、patch 截断、typed Trellis 写入或接受含规范改动的结果均拒绝。
