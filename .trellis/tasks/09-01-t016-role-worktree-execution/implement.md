# T016 实施记录

## 交付

- 新增 `RoleWorktreeSession` 与不可变 `RoleWorktreeBinding`，通过注入的 `GitWorkspace` 创建
  role worktree，并把同角色 `AgentDefinition.permissions` 绑定到 T015 executor。
- Coder 保留 manager 创建的 attempt branch，QA/Reviewer 复用 candidate SHA 的 detached
  worktree；命令 cwd 只能是 manager 返回的 worktree root。
- `inspect`/`close` 委托 Git manager，dirty worktree 抛 `DirtyWorktree` 并保留现场，clean
  worktree 才移除；T015 `CommandExecutorSettings` 在 session 构造阶段先验证，避免非法配置
  留下 attempt branch，path-bound executor 的意外初始化失败仍尝试清理并保留原始异常。
- 用真实临时 Git fixture 覆盖 cwd、branch/detached candidate、role mismatch、dirty/clean
  cleanup 与初始化失败，且同步架构、Git、Runtime、AGENTS 和 core/Python runtime spec。

## 已知限制与后续接入

- T016 仍是 application composition seam；`RuntimeSession` 尚未自动创建 role worktree，也不
  自动把模型自由文本变成命令。后续 Coder/QA/Reviewer service 需要显式构造 `WorktreeSpec`、
  调用 binding.executor，并把 `CommandResult` 保存为 evidence。
- 单机 subprocess 不是完整 OS sandbox；未来若允许不可信 Agent 直接执行任意代码，需要单独
  的容器/OS 资源隔离 ADR，不能由本 session 假设已解决。
