# 历史 Git worktree 恢复使用 successor Task 的封存基线

## 问题

旧版准备在 Git linked worktree 中无法读取外置 gitdir，合法地将
`RepositoryProfile.source_revision` 记录为 `unknown`。恢复时却把这个不可执行值传给
frozen delivery backend，导致已拥有 successor Task `base_ref` 的交付再次阻塞。

## 目标

让新准备显式封存 intake 的 Git revision；让历史恢复仅在 Task 与 repository 精确绑定、
`base_ref` 是可验证 Git revision 时使用该 durable fact。平台继续保留提供方失败后的 dirty
worktree，不能借恢复之名 reset、rebase、覆盖或跳过独立 QA/Review。

## 范围

- `RepositoryProfile.discover(..., revision=...)` 的 linked worktree 适配；
- `ProductionJointBackend.delivery_runtime()` 的历史 profile 兼容；
- Manager backend 的精确 Task source revision 读取；
- 未启动 successor 的父级累计 delivering 次数不得阻止平台启动恢复；
- Manager 阻塞输入不得把 ProductSpec 摘要当作恢复审批，且必须携带 child 的结构化失败事实；
- 规范、contract regression 和存量恢复操作说明。
