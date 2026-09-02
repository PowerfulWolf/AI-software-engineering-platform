# T026–T027：只读投影与 Agent 工作可视化

## 阶段快照

- 日期：2026-09-01
- 纳入任务：T026 RunProjection/read API、T027 visualization dashboard
- feature/integration commit：`0d6f3ed`

## 形成的能力

- `ProjectionFacts → RunProjectionBuilder → ProjectionSnapshot` 从已验证 durable facts 重算
  Task、Run、Agent、Lease 与 source-addressable timeline；重复/冲突事实 fail closed。
- `ReadOnlyProjectionApi` 提供 transport-neutral GET-only 列表、详情、过滤、分页；不写 Task、
  verdict 或状态。
- `DashboardRenderer` 以零新增依赖输出稳定 JSON 或可直接打开的 HTML，包含 Task board、Run
  timeline、Agent detail/capacity、Human inbox；恶意文本通过 escaped JSON + textContent 安全渲染。

## 验证证据

- T026 projection/read API：7 passed；
- T027 visualization：2 passed；
- 当前全量测试：380 passed；
- targeted Ruff/Mypy：passed。

## 已知限制与下一步

v0.1 仍使用静态本地 renderer，不引入 HTTP/SSE、前端构建链、事件总线或向量库；Agent 总容量、
成本和 HumanActionEvent 未被事实支持时保持 unknown。下一步是将 projection 接入真实本地 read
server，并在不改变只读边界的前提下支持增量刷新。
