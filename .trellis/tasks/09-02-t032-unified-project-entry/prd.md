# T032 PRD：统一项目接单入口

## Goal

用户只提供目标项目目录和需求，由 Project Manager Agent 自动 prepare、产品确认、设计、计划、
dispatch，并使用现有串行 Coder→QA→Reviewer 完成交付或返回明确人工阻塞。

## Acceptance Criteria

- [x] 一个 CLI/application entry 接收绝对项目目录与需求，自动发现/重开外置 workspace；
- [x] Product Spec 用户确认是唯一必要业务门禁，内部路径/Runtime 配置不要求手工拼装；
- [x] prepare/approve/design/plan/dispatch/delivery 都有 durable checkpoint，可 resume；
- [x] Python、Java、C++ fixture 至少各一条 fake-agent offline E2E；
- [x] 目标项目保持干净，Coder/QA/Reviewer 使用隔离 worktree 与同一 candidate SHA；
- [x] 冲突、invalid output、失败预算和进程重启返回稳定 checkpoint/handoff；
- [x] 不自动 merge/deploy，不引入 daemon/DAG/vector DB。
