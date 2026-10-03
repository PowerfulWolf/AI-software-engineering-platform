# 实施记录

- 在 `domain.branch` 集中定义受保留的 successor purpose 后缀和稳定根名解析。
- 将语义分支测试改为覆盖重复 `recovery`、混合 purpose、业务 slug 以及 `None`。
- 同步 `.trellis/spec/core/branch-naming.md` 和 `docs/architecture/git-worktree.md`。
- 既有长分支不重命名；平台重启后仅影响新的 successor 生成。
