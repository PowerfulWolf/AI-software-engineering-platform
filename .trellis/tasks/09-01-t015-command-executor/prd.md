# T015 — 受控命令执行器

## Goal

为 Coder/QA/Reviewer 后续接入真实 worktree 提供一个最小、可替换、fail-closed 的命令执行
端口。执行器必须在调用前检查角色命令 allowlist、固定 cwd、环境变量白名单和超时，并以
typed result 返回可引用的 stdout/stderr，而不是让 Agent 或 CLI 直接拼接 shell 命令。

## Requirements

- 提供 `CommandExecutor` Protocol 和本地 `SubprocessCommandExecutor` 实现；
- 只接受已 tokenized 的 argv，复用 `WorkspacePolicy.authorize_command`，禁止 shell=True、
  shell 控制 token、命令字符串拼接和 cwd 越过绑定 worktree；
- 默认只传递最小环境（PATH、LANG、LC_ALL、必要的显式 allowlist），不复制宿主机 secrets；
- 使用固定 timeout，超时时终止进程并返回稳定的 `CommandTimedOut`；启动失败返回稳定错误；
- 命令的非零退出是可观察的 `CommandResult`，不伪造 PASS；stdout/stderr 有最大字节上限；
- 先以 fake/fixture subprocess 测试，再保留未来 RuntimeSession/QA 集成的 typed seam；
- 不引入 shell、容器、队列、DAG 或新的数据库。

## Acceptance Criteria

- [x] 正常命令、非零退出、超时、未授权命令、shell token、cwd 越界和环境泄漏均有测试；
- [x] `CommandResult` 能安全序列化，包含 argv、cwd、returncode、stdout、stderr、duration；
- [x] 所有 subprocess 调用固定 `shell=False`、明确 cwd、最小 env 和 timeout；
- [x] 相关 docs、AGENTS、`.trellis/spec/` 写出 signatures、错误矩阵和接入边界；
- [x] 全量测试、Ruff、strict Mypy、build、diff check 通过。

## Contract Impact

新增 `src/ai_software_engineer/execution.py` 和 `tests/execution/`；不改变既有 Task、Agent、
Artifact 或 Evaluation wire Schema。

## Rollback

删除 execution module、tests、docs/spec 和本任务记录；既有 Git policy、RuntimeSession、
AgentAdapter 与持久化格式不受影响。
