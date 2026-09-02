# T027 PRD：本地 Agent 工作可视化 dashboard

目标：让人类从 durable read projection 观察 Task、Run、Agent capacity 和人工阻塞，而不把 UI
变成第二个状态写入者。验收：renderer 接受 `ProjectionSnapshot` 或 `ReadOnlyProjectionApi`，
输出稳定 JSON/自包含 HTML，包含四个只读视图，安全显示不可信文本，并有合法、空集合、阻塞和
注入防护测试。
