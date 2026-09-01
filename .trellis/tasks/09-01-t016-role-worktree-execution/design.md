# T016 设计

## Boundary

```text
AgentDefinition + WorktreeSpec
            │ same role / machine policy
            ▼
     RoleWorktreeSession
       ├── GitWorkspace.create
       └── SubprocessCommandExecutor(worktree.path, permissions)
            │
            ├── binding.executor.run(tokenized argv)
            └── session.close(binding) → inspect/remove guard
```

`RoleWorktreeSession` 只负责组合和生命周期，不迁移 Task 状态、不写 Artifact、不解释命令
returncode，也不替 Agent 生成命令。`CommandResult` 由上层转成 evidence；QA/Reviewer 决定
verdict 的契约不变。

## Role and cleanup policy

- `WorktreeSpec` 自身拒绝 orchestrator；session 额外要求 `spec.role == agent.role`，避免把
  Coder 权限错配给 QA/Reviewer；
- Coder worktree 保留 manager 分配的 attempt branch，QA/Reviewer 使用 T006 detached
  candidate；session 不重写 branch/ref；
- `close` 委托 `GitWorkspace.remove`。dirty snapshot 由 Git 层转为 `DirtyWorktree`，不 force
  delete；clean worktree 才删除，Coder branch/commit 仍由 Git 保留；
- session 构造阶段先验证 T015 `CommandExecutorSettings`，因此非法环境名、timeout、output
  limit 不会创建任何 worktree/branch；若 path-bound executor 在 `open` 后意外初始化失败，
  只尝试删除这一轮刚创建且尚未交给调用方的 clean worktree，原始错误继续抛出并在清理失败
  时追加 note。

## Good / Base / Bad

- **Good**：同角色 Coder binding 在独立 branch 中运行命令；QA binding detached 到 candidate
  SHA；命令输出中的 cwd 等于 manager worktree，clean 后关闭；
- **Base**：真实 Git fixture + Python 标准库短命令验证组合 seam，无 provider、网络或数据库；
- **Bad**：用 Reviewer Agent 打开 Coder spec、把 main checkout 直接传给 executor、忽略
  `DirtyWorktree` 强制删除，或把模型输出的 shell 字符串交给 binding。
