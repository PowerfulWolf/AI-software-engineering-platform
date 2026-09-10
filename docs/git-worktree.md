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
- 不直接执行 `git add`/`git commit`；完成时返回 provisional implementation-report，未完成时返回
  `coder-progress`；
- 平台提交前必须检查 source revision、实际 dirty inventory、reported paths 和变更文件 allowlist；
- 不允许改 `.trellis/spec/`、状态数据库、artifact 历史和 CI 配置（除非 Task 显式批准并由人类升级）。

### QA

- 从 Coder commit 创建干净 worktree；
- Codex 进程使用 `workspace-write`，允许 pytest、Ruff、编译器在这个一次性 worktree 中创建被
  Git 忽略的 cache/build scratch；这只是进程沙箱能力，不是候选代码写权限；
- QA 的角色 `write_paths` 仍为空。运行后 HEAD 必须等于候选 SHA，且 `git status --porcelain`
  必须为空；任何 tracked 或 untracked Git-visible 改动都按 `POLICY_VIOLATION` 失败并保留证据；
- QA 不提交、不合并测试改动。需要新增或保留测试时，作为 finding 路由给 Coder 在下一候选中实现。

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
2. 四类终态 artifact、可选 coder-progress lineage 与测试 evidence；
3. 人类可以审阅并手动 merge 的建议。

未来若开启自动 merge，必须额外满足 protected branch、签名、CI 绿灯、review 独立性和回滚点等门禁。

## CandidateCommit Skill

`CandidateCommitSkill` 是平台/Project Manager 持有的最小 Git 权限 seam，Coder 模型本身不持有
Git 元数据写权限：

```python
CandidateCommitSkill.changed_paths() -> tuple[str, ...]
CandidateCommitSkill.finalize(request: CandidateCommitRequest) -> CandidateCommitResult
```

`finalize` 只接受精确 `task_id`、输入 full SHA、排序且非空的 reported paths 与该 Run 的
`AgentPermissions`。实现必须保证 HEAD 等于输入 SHA、reported paths 等于 tracked/untracked dirty
inventory、每条路径通过 `WorkspacePolicy`，然后以固定身份、禁用 hooks/fsmonitor/GPG 的参数创建
一个提交。提交后 worktree 必须 clean，`base..candidate` 的路径集合必须仍与请求完全一致。

任一 revision/path/policy 漂移都抛 `CandidateCommitRejected`，保留现场且不允许进入 QA。
`coder-progress` 不调用本 Skill：它要求 HEAD 不变，并保留与 Artifact 完全一致的授权 dirty paths，
由下一次 Coder Run 继续。这样“保存进度”和“宣布候选完成”是两个不同的机器边界。

## 7. 清理与恢复

- worktree 删除前运行 `git status --porcelain`；非空变更必须先保存为 evidence 或阻塞；
- 进程中断时保留 worktree，重启后通过 task event 找回；
- 删除只针对 `worktrees/<task-id>/` 的明确路径，不使用宽泛 glob；
- 无法确定候选 commit 是否对应 artifact 时，停止清理并进入 `BLOCKED`。

`inspect` 通过 Git 返回精确 HEAD，并合并 staged、unstaged 和 untracked changed paths。`remove` 只接受 layout 与 Git common directory 都属于当前 manager 的 `WorktreeRef`；dirty 时抛出带 `changed_paths` 的 `DirtyWorktree`，clean 时调用 `git worktree remove`，但保留 Coder branch 和 candidate commit。

## RoleWorktreeSession 组合层

T016 的 `RoleWorktreeSession` 将 `WorktreeSpec`、同角色 `AgentDefinition` 和 T015
`SubprocessCommandExecutor` 组合为一个 `RoleWorktreeBinding`。`open` 先由注入的
`GitWorkspace` 创建 worktree，再把 `agent.permissions` 绑定到具体 root；role mismatch 在
创建前拒绝，避免将 Coder 权限错配给 QA/Reviewer。调用方只能通过 binding 的 executor 运行
tokenized argv，仍受命令、环境、cwd、timeout 和输出边界约束。

`inspect(binding)` 返回 manager 的 Git snapshot，`close(binding)` 只委托受保护的
`GitWorkspace.remove`：dirty worktree 抛 `DirtyWorktree` 并保留 evidence，clean worktree
才移除；Coder branch 和 candidate commit 不被清理。session 不修改 Task/Artifact 状态，也不
负责决定命令是否使 QA PASS 或 Reviewer APPROVE。

## Dispatch 绑定与严格恢复

T032 的 `DispatchRoleWorktreeCoordinator` 不接受调用方临时指定 Agent/model。它从已通过完整性校验的
`DispatchCommitRecord` 找到每个 role 的 Assignment、TaskLease 与 ModelSelection，再与即将执行的
`AgentDefinition` 比较 agent ID、role、provider、model、task 和 attempt；任何漂移都在 checkout 前
拒绝。

```python
coder = coordinator.open_coder(dispatch, resolved_definitions)
# Coder 返回 intended diff，平台 finalizer 校验并形成 immutable full SHA 后：
verification = coordinator.open_verifiers(
    dispatch,
    candidate_revision,
    resolved_definitions,
)
assert verification.qa.worktree.head_revision == verification.reviewer.worktree.head_revision
```

Coder 必须从 Task `base_ref` 的 full commit SHA 创建 branch worktree；Codex sandbox 不获得原仓库
`.git` 写权限，candidate 由平台对 exact diff/report/path policy 校验后封装。QA/Reviewer 必须从同一个 full
candidate SHA 创建两个独立 detached worktree。`recover=True` 不做 checkout/reset/clean，而是要求
现有路径、Git common-dir、role/attempt layout、branch/detached 状态和 HEAD 全部吻合；dirty 文件作为
中断 evidence 保留。恢复检查失败时上层进入人工处理，不能悄悄创建另一份环境继续。

T044 第一阶段增加只读 Python 接口 `GitWorktreeManager.capture_changes/verify_capture`，用于识别
中断 Coder 留下的既有文本文件修改，绑定原 HEAD、分支、patch、文件摘要与暂存区摘要。
它不保存或应用补丁，不修改旧工作树，也不恢复终态 Task。新增/删除/二进制/越权或敏感改动等
不支持的情况明确拒绝；细节见 [恢复契约](../.trellis/spec/core/delivery-recovery.md)。生产恢复入口、
授权后的新执行和基线更新仍需后续实现，不能用捕获成功代替候选提交及独立 QA/Review。

T044 C2 增加 `seed_changes(capture, target, source_permissions, target_permissions, ...)`，
在原改动和双方权限校验后，将文本修改三方应用到另一个新 Task 的干净 Coder worktree。
新基线必须包含旧基线；冲突先在临时暂存区检出，不污染目标文件。旧 worktree 不变，
应用后只返回改动捕获，不提交代码、不生成 verdict。它目前仅由临时 Git 测试验证；
生产授权、Task/dispatch、恢复入口及 provider 接续仍需接入，不能直接拿它恢复旧终态 Task。
