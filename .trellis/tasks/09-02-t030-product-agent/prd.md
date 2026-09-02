# T030 PRD：Product Agent 与确认循环

## Goal

在 PREPARED project context 中让 Product Agent 与用户澄清需求，持久化 ProjectRequest 决策并产出
ProductSpec；用户可以 APPROVE 或 REQUEST_CHANGES，且只有 exact APPROVED version 解锁 Designer。

## Acceptance Criteria

- [ ] Product role 成为 organization AgentProfile 可声明的正式角色，并有最小权限/Context routing；
- [ ] 每轮对话输入与决定写入 immutable record，不依赖模型会话记忆；
- [ ] ProductSpec requirements/acceptance IDs 完整且通过 Schema；
- [ ] Product Agent 无权创建 APPROVED record；用户请求修改生成新 version + supersedes；
- [ ] replay/invalid output/provider failure 不重复决定、不误解锁设计；
- [ ] fake adapter 离线覆盖澄清、ready、changes、approve 路径。

## Out of Scope

- Solution Designer、Planner、concrete delivery dispatch。
