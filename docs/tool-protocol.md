# Typed Agent Tool Protocol

T024 将 Agent 与目标项目之间的操作收敛为三个 typed tools：`read_file`、`write_file` 和
`run_command`。请求必须带 `run_id`、`role`、`operation_id`；请求中的路径是 repository-relative
path，命令是 tokenized `argv` 数组。不存在自由文本 `exec` 或 `shell` 字段，registry 也会拒绝
`sh`/`bash` 等解释器。

`PolicyBoundToolRegistry` 在创建时绑定一个 `AgentDefinition`、role worktree、可选 run ID 和
`WorkspacePolicy`。调用先做 identity、路径或命令授权，再执行：

| tool | Coder | QA | Reviewer |
|---|---|---|---|
| `read_file` | 允许的 read paths | 允许的 read paths | 允许的 read paths |
| `write_file` | 允许的 write paths（不含 policy/artifact/verdict） | 仅 `tests/**` | 始终拒绝 |
| `run_command` | allowlisted argv | allowlisted argv | allowlisted argv（只读命令） |

成功结果是 immutable typed model；文件结果包含 SHA-256，命令结果保留真实 return code 和
截断标记。拒绝结果为 `ToolRejectedResult`，不得被解释成 PASS/APPROVE。命令超时、启动失败、
路径越权和非 UTF-8 文件均 fail closed。

工具结果目前是内存边界。接入 Runtime 时，application service 必须把请求/结果和拒绝原因交给
T023 EvidenceStore；Agent 仍不能直接写 verdict、artifact、状态数据库或 Trellis 规则。
