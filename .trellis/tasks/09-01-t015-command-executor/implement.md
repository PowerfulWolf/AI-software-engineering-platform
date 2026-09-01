# T015 实施记录

## 交付

- 新增 `CommandExecutor` Protocol 与 `SubprocessCommandExecutor`，统一承接后续 Coder/QA/Reviewer
  在 role worktree 中的命令执行；调用方只能传入已 tokenized 的 argv。
- 执行前复用 `WorkspacePolicy.authorize_command`，cwd 固定到构造时绑定的 worktree，始终使用
  `shell=False`；超时时终止整个进程组，避免后台 descendant 泄漏。
- 子进程默认只获得 `PATH`、`LANG=C`、`LC_ALL=C`，额外变量必须显式加入 allowlist；stdout/stderr
  有界收集并带截断标记，非零退出以 typed `CommandResult` 返回。
- 补充正常退出、非零退出、输出截断、环境隔离、策略拒绝、超时/descendant 终止和启动失败测试，
  并同步 README、runtime/architecture 文档、AGENTS 与 Python runtime spec。

## 已知限制与后续接入

- T015 只提供可替换执行 seam，尚未让 `RuntimeSession` 自动执行任意 Agent 生成命令；后续任务应
  在 Coder/QA application service 中显式构造 executor，并把 `CommandResult` 转成 evidence。
- 当前边界仍是单机 subprocess；不引入 shell、容器 sandbox、队列、复杂 DAG、向量库或新数据库。
