# T025：任意目标项目串行交付验证

## 阶段快照

- 日期：2026-09-01
- 纳入任务：T025 Cross-language target-project E2E
- feature/integration commit：`dff64ab`

## 形成的能力

- 新增 Python、Java/Maven、Go modules、TypeScript/npm 四组极小离线 fixture；本地未安装的
  runtime 只跳过命令 probe，不跳过 ProjectProfile、sidecar、typed tool 和串行交付断言。
- E2E 真实调用 `ProjectWorkspaceRegistry`、`RuntimeWorkspaceBinder`、`PolicyBoundToolRegistry`、
  `RunEvidenceSession`、`FileContextStore`、`FileArtifactStore` 和 `SerialOrchestrator`，证明
  目标代码目录保持干净，平台元数据写入外置 workspace。
- 每种语言都验证 `PLANNING → IMPLEMENTING → QA → REVIEW → DONE`、candidate SHA 贯穿 QA/Review、
  四角色独立 producer、context/artifact 可持久化回放。

## 验证证据

- `tests/e2e`：4 passed（optional runtime probe 按环境条件执行）
- T025 targeted Ruff/Mypy/git diff：passed
- 完整 M6 基线：370 tests（T023/T024 + T025）

## 已知限制与下一步

这些 fixture 验证的是跨语言协议和隔离边界，不替代真实业务仓库的验收；T026 将提供可重算的
只读 projection/read API，T027 将把这些 durable facts 展示为本地 dashboard。
