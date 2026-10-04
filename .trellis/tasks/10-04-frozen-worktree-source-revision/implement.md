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
