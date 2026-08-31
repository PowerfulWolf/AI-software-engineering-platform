# Git / worktree 隔离策略

## 1. 目录布局

主仓库之外的运行目录统一放在平台配置的 `worktrees/`：

```text
worktrees/<task-id>/
├── coder-attempt-01/       # 可写候选
├── qa-attempt-01/          # 从候选 commit 创建，可写测试目录
└── reviewer-attempt-01/    # 从同一候选 commit 创建，只读
```

运行结束后保留 commit、diff 和关键日志；worktree 可按保留策略清理，但清理前必须确认 artifact 已持久化。

## 2. 分支命名

```text
ai/<task-id>/attempt-<n>
```

Task ID 只允许 `[a-z0-9_-]`，长度受限，避免路径注入。分支从 Task 的 `base_ref` 创建；重试从最新有效候选 commit 创建新 attempt，不复用已污染的工作树。

## 3. 角色隔离

### Orchestrator

- 不在主 checkout 修改业务文件；
- 只执行 `git rev-parse`、`git show`、`git diff`、`git worktree add/remove` 等 allowlist 命令；
- 不接受 Agent 返回的任意 Git 命令。

### Coder

- 仅能写 Task policy 的 `write_paths`；
- 提交前必须检查 `git diff --check`、状态和变更文件 allowlist；
- 不允许改 `.trellis/spec/`、状态数据库、artifact 历史和 CI 配置（除非 Task 显式批准并由人类升级）。

### QA

- 从 Coder commit 创建干净 worktree；
- 测试写入限定在 `tests/` 或 Task 指定的 QA 路径；
- QA 结束后导出测试 diff，默认不并入候选分支。若某个测试必须保留，作为人类可见的独立 patch 提议。

### Reviewer

- 使用同一候选 commit 的只读 worktree；
- 禁止任何写操作和自动修复；
- Review 结束后由 Orchestrator 决定是否回到 Coder。

## 4. 合并门禁

v0.1 不自动 merge。交付物是：

1. `base_ref`、candidate commit SHA 和统一 diff；
2. 四类 artifact 与测试 evidence；
3. 人类可以审阅并手动 merge 的建议。

未来若开启自动 merge，必须额外满足 protected branch、签名、CI 绿灯、review 独立性和回滚点等门禁。

## 5. 清理与恢复

- worktree 删除前运行 `git status --porcelain`；非空变更必须先保存为 evidence 或阻塞；
- 进程中断时保留 worktree，重启后通过 task event 找回；
- 删除只针对 `worktrees/<task-id>/` 的明确路径，不使用宽泛 glob；
- 无法确定候选 commit 是否对应 artifact 时，停止清理并进入 `BLOCKED`。
