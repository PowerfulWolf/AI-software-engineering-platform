# Implementation

- `RepositoryProfile.discover` 在 Git linked worktree 无法读取本地 revision 时接受调用方已验证的
  `revision`，并把它绑定到 `VcsInfo` / `source_revision`。
- `ProductionJointBackend.prepare` 传入 `DirectoryUnit.base_revision`。
- `ProductionJointBackend.delivery_runtime` 对 legacy `unknown` profile 调用
  `ProductionProjectDeliveryBackend.task_source_revision`，校验精确 Task/repository 绑定和
  durable `base_ref`，再构建 frozen backend。
- `ProductionProjectDeliveryBackend` 对 legacy `unknown` profile 仅允许与已封存 frozen revision
  配对；具体冲突仍拒绝。
- 增加 RepositoryProfile、Task source revision 和完整 delivery runtime fallback regression；
  更新 multi-directory / production-host spec。
- `rebind_native_rule_sources` 接受受控的 `source_revision`，恢复 allocation 绑定
  successor Task.base_ref；补充真实 linked-worktree 回归。
- 放宽仅针对未启动 successor 的 `retry_interrupted_stage` 门禁，保留 Task 事件/候选安全检查；
  补充父级累计 delivering 次数回归。
- 修正 `StageBlockage` 的审批语义和 child finding 事实，避免 Manager 以 ProductSpec 摘要
  推断恢复授权。
