# T016 — role worktree 与命令执行生命周期

## Goal

把 T006 的 manager-owned Git worktree 和 T015 的 fail-closed `CommandExecutor` 组合成一个
供 Coder/QA/Reviewer application service 使用的最小 typed seam。每个 binding 必须由
`WorktreeSpec` 与同角色 `AgentDefinition` 创建，命令只能在该 worktree 中运行，清理必须沿用
dirty-worktree 保护。

## Requirements

- 新增 `RoleWorktreeSession`，通过注入的 `GitWorkspace` 创建、检查和关闭 role worktree；
- `open(spec, agent)` 拒绝 orchestrator worktree 和 role/permissions 不匹配，构造
  `SubprocessCommandExecutor` 时复用 Agent 的权限、环境、timeout 和输出上限策略；
- 返回不可变 `RoleWorktreeBinding(worktree, executor)`，上层通过 executor 运行 tokenized argv，
  结果仍是 T015 `CommandResult`；
- `close(binding)` 只调用 manager 的受保护 remove；dirty worktree 抛 `DirtyWorktree` 并保留
  现场，clean worktree 才能删除；
- executor settings 在创建任何 worktree/branch 前通过 T015 typed 配置校验；如果 path-bound
  executor 在 `open` 后意外初始化失败，尽力清理刚创建的 clean worktree，并保留原始错误；不
  自动清理已有 dirty worktree；
- 用真实临时 Git fixture 覆盖 Coder 写入、QA detached candidate、固定 cwd、role mismatch、
  dirty cleanup 和 clean cleanup；
- 不修改 Task/Agent/Artifact wire Schema，不把模型自由文本变成命令，不引入队列、容器、DAG
  或自动 merge。

## Acceptance Criteria

- [x] `RoleWorktreeSession` 与 `RoleWorktreeBinding` 有完整 typed signatures 和稳定错误；
- [x] Coder/QA/Reviewer 只能绑定同角色 AgentDefinition，Orchestrator 被拒绝；
- [x] 命令在 manager 返回的 worktree root 中执行，cwd/env/timeout 约束由 T015 executor 继续生效；
- [x] dirty worktree 关闭失败且现场保留，clean worktree 可安全移除；
- [x] 文档、AGENTS、`.trellis/spec/` 记录生命周期边界和 Good/Base/Bad；
- [x] 全量测试、Ruff、strict Mypy、build、diff check 通过。

## Contract Impact

新增 `src/ai_software_engineer/role_workspace.py`、`tests/role_workspace/` 及文档/spec；不改变
既有 JSON Schema 和 RuntimeSession 默认装配。

## Rollback

删除 role workspace 组合模块、测试、文档/spec 和本任务记录；T006 GitWorkspace 与 T015
SubprocessCommandExecutor 保持可独立使用。
