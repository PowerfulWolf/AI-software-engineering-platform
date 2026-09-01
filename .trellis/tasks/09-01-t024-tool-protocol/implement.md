# T024 实现记录

- 新增 `tools.models`：`ReadFileRequest`、`WriteFileRequest`、`RunCommandRequest` 及对应 typed
  results/rejection；`TOOL_REQUEST_ADAPTER`/`TOOL_RESULT_ADAPTER` 提供 wire validation。
- 新增 `PolicyBoundToolRegistry`：固定 workspace root/run/role，复用 `WorkspacePolicy` 和
  `SubprocessCommandExecutor`；无 `exec(text)`、shell 或 verdict mutation 方法。
- 文件读取为 UTF-8 bounded payload，写入使用 fsync + 同目录原子替换；结果带 SHA-256。
- QA/Reviewer hard safety 独立于 AgentPermissions，防止错误配置越权；shell interpreter 直接拒绝。
- 新增 `schemas/tool-request.schema.json` 和 `schemas/tool-result.schema.json`，以及 8 个离线测试。
