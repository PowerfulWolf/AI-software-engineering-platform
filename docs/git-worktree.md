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

`GitWorktreeManager(repository, worktree_root)` 在第一次创建前验证 repository 必须是 Git root，且 `worktree_root` 不能等于或位于 main checkout 内。每个 Task target 在创建前还会解析已有 symlink parents，解析结果必须仍位于 configured root 内。这样创建 worktree 本身不会让 main checkout 出现未跟踪目录，也不能通过预置 symlink 把 role worktree 引到根外。

## 2. 分支命名

```text
ai/<task-id>/attempt-<n>
```

Task ID 只允许 `[a-z0-9_-]`，长度受限，避免路径注入。分支从 Task 的 `base_ref` 创建；重试从最新有效候选 commit 创建新 attempt，不复用已污染的工作树。

source ref 会先解析为完整 commit SHA。已有 target path 或 Coder branch 都视为旧 attempt evidence，返回 `WorktreeAlreadyExists`，不会自动复用、覆盖或 force-delete。

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

## 4. 可执行接口与机器 Policy

```python
worktree = git_workspace.create(
    WorktreeSpec(
        task_id=task.id,
        role=role,
        attempt=task.attempts,
        source_revision=candidate_sha,
    )
)
snapshot = git_workspace.inspect(worktree)

policy = WorkspacePolicy(
    worktree.path,
    agent.permissions,
    denied_paths=task.constraints.denied_paths if task.constraints else (),
)
safe_path = policy.authorize_write("src/package/service.py")
safe_argv = policy.authorize_command(("pytest", "tests/unit", "-q"))
```

- runtime path 只能是 canonical repository-relative POSIX path；absolute、空段、`.`、`..`、backslash、控制字符、glob 和任何 `.git` segment 都拒绝；
- policy 绑定实际 worktree root，解析已存在的 symlink parent 后必须仍位于 root 内且不能指向 `.git`；
- Task `denied_paths` 优先于 role read/write allowlist；Reviewer 的空 write allowlist 默认拒绝全部写入；
- command allowlist 以完整 token prefix 匹配：允许 `git diff` 不等于允许 `git push`；argv 为空、含 shell 控制 token/换行/`$()`/backtick 时拒绝；
- policy 只授权，不执行。后续 command executor 仍必须固定 cwd/env/timeout/network/resource policy，并把拒绝写成 evidence。

## 5. Git 自身的执行安全

平台内部 Git adapter 使用参数数组、明确 cwd、固定 timeout、最小环境和 `shell=False`，并在每次 invocation 覆盖：

```text
-c core.hooksPath=/dev/null
-c core.fsmonitor=false
```

因此 repository 自带的 `post-checkout` 等 hook 和 fsmonitor 不会运行。inspection 的 diff 同时使用 `--no-ext-diff --no-textconv`。

checkout filter 是更隐蔽的外部执行入口。v0.1 若发现 repository-local `filter.*.clean/smudge/process`，在 `worktree add` 前返回 `UnsafeRepositoryConfiguration`；未来只能在有 OS/container sandbox、网络和资源限制、filter allowlist 与 evidence 后放开。Git policy 不能替代完整进程沙箱。

## 6. 合并门禁

v0.1 不自动 merge。交付物是：

1. `base_ref`、candidate commit SHA 和统一 diff；
2. 四类 artifact 与测试 evidence；
3. 人类可以审阅并手动 merge 的建议。

未来若开启自动 merge，必须额外满足 protected branch、签名、CI 绿灯、review 独立性和回滚点等门禁。

## 7. 清理与恢复

- worktree 删除前运行 `git status --porcelain`；非空变更必须先保存为 evidence 或阻塞；
- 进程中断时保留 worktree，重启后通过 task event 找回；
- 删除只针对 `worktrees/<task-id>/` 的明确路径，不使用宽泛 glob；
- 无法确定候选 commit 是否对应 artifact 时，停止清理并进入 `BLOCKED`。

`inspect` 通过 Git 返回精确 HEAD，并合并 staged、unstaged 和 untracked changed paths。`remove` 只接受 layout 与 Git common directory 都属于当前 manager 的 `WorktreeRef`；dirty 时抛出带 `changed_paths` 的 `DirtyWorktree`，clean 时调用 `git worktree remove`，但保留 Coder branch 和 candidate commit。
