# Design

新 intake 已在 `DirectoryUnit.base_revision` 中取得 Git adapter 的提交事实，准备 profile 时
显式传入该 revision。若本地 `.git` 是 linked-worktree 指针，profile 不跨越目标目录读取
外置 gitdir，而是绑定已验证的显式 revision。

恢复历史 child 时先读取 immutable preparation/profile。具体 revision 为 `unknown` 时，读取
MySQL 中该 child successor Task，要求 Task 的 `repository` 与当前 child `repository_root`
规范化后完全相等，并要求 `base_ref` 符合 durable Git revision。随后由 frozen backend 的
既有 Git guard 验证提交存在。任何具体冲突 revision、缺 Task、错误仓库或非 Git base 都拒绝。

这条兼容路径只修复 runtime 装配，不改变旧的 Run、Task、checkpoint、dirty worktree、
recovery approval、candidate 或 QA/Review verdict。
