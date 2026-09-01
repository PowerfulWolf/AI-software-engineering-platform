# T024 — Coder/QA/Reviewer typed tool protocol

## Goal

让 Agent 通过可校验的结构化 tool request 调用文件读写和命令执行。工具 registry 绑定一个
AgentRun、角色 worktree 和 `WorkspacePolicy`，不暴露自由文本 shell，也不提供 verdict、artifact
或 Task 状态写接口。

## Acceptance criteria

- [x] `read_file`、`write_file`、`run_command` 使用 Pydantic/JSON Schema typed payload；argv 不可表达 shell source；
- [x] 每次请求带 `run_id`、`role`、`operation_id`，绑定 registry 拒绝 identity mismatch；
- [x] Coder 只能写 AgentPermissions 允许的代码/测试路径；QA 即使被错误配置为宽权限也只能写 `tests/`；Reviewer 无仓库写能力；
- [x] policy、路径、shell interpreter、超时和文件错误返回 typed fail-closed rejection；命令退出码仍由 `CommandResult` 证据表达，不伪造 PASS；
- [x] 文件写入使用同目录临时文件和原子替换；结果携带 SHA-256 与截断信息；
- [x] fake command backend 覆盖离线集成，positive/negative/boundary tests 通过。

## Out of scope

真实模型 provider tool-calling 适配、任意 Git 写命令、Verdict/artifact store mutation、容器沙箱和复杂 DAG。
