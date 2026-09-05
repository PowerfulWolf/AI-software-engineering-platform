# T034 Production Team Host 与真实项目交付闭环

## 阶段目标

把 T032 的 provider-neutral 统一入口装配成可以直接运行的组织团队。平台管理员只做一次 Team Host
配置；之后用户提交目标 Git 项目绝对目录和需求，由 Project Manager 自动完成 prepare、Product
确认、设计、规划、分配和串行 `Coder → QA → Reviewer` 交付。

## 已完成

- 新增 `OrganizationTeamHost` production composition root；`ase project ...` 在未注入测试 provider
  时自动从 `ASE_CONFIG`、默认配置与环境变量惰性装配，不再要求业务调用方写 Python 注入代码；
- 新增 secret-free `ProductionConfig` 及 JSON Schema。配置只保存环境变量名，DSN/API key 不落入
  配置、Artifact 或错误正文；
- 新增 MySQL 8.0 `TaskRepository` 和 dispatch authority，实现 InnoDB 行锁、CAS、事件 exact replay、
  Assignment/Lease/dispatch bundle 原子提交；Docker Compose 提供独立本地数据库；
- 新增 Codex CLI 与 Responses-compatible provider。默认 route 使用已登录 Codex CLI 的 GPT-5.5；
  Qwen/DeepSeek 是显式、默认关闭的 fallback 模板；
- 新增 Product、Designer、Planner structured model clients，以及绑定 dispatch-owned AgentDefinition、
  Context、Artifact、worktree 和 tool policy 的 Coder/QA/Reviewer adapters；
- fallback 只接受 quota、rate limit、timeout、temporary unavailable 等 typed transient failure。每个
  delivery route attempt 都持久化 provider/model、完整 AgentRequest digest、result 和内容摘要；changed
  replay、篡改和非连续 attempt fail closed；
- Coder 在 frozen base SHA 的 branch worktree 中提交 candidate；QA/Reviewer 在同一 candidate SHA 的
  两个独立 detached worktree 中验证。目标项目主 checkout 不变，平台不自动 merge 或 deploy；
- 新增 `scripts/smoke-live-gpt55.sh`、正常使用文档、可执行 Trellis contract 和 production config
  contract tests。

## 核心不变量

1. Knowledge、ProjectProfile、规范、checkpoint、模型尝试和交付证据属于组织，不依赖某个 Agent 会话。
2. ProductSpec 必须由人类批准；Coder 不能裁判自己，QA 与 Reviewer 必须是独立 Agent 和独立 worktree。
3. Agent 通过可验证 typed Artifact 协作；自由文本、provider 成功码或 Coder 自报 verdict 都不是事实。
4. 模型 fallback 不改变组织成员身份，也不能掩盖鉴权、契约、策略或业务冲突。
5. production 失败保留 durable checkpoint 和取证现场；不会回退 fake Agent、无限重试或自动放宽 sandbox。

## 验证与验收

- 完整 pytest（含本地 MySQL 集成）：`651 passed`；
- Ruff lint/format、strict Mypy、`uv lock --check`、offline sdist/wheel build、`git diff --check` 通过；
- offline scripted-provider E2E 使用真实 MySQL、真实 Git commit 和隔离 worktree 到达 `DONE`，且目标项目
  主 checkout 零改动；
- live GPT-5.5 structured Product output 通过真实 provider 验证；完整 live run 已实际推进 Product、人工
  approval、Designer、Planner 和 dispatch；
- live 调用暴露并修复了两个 provider compatibility 问题：Codex CLI 不允许同时指定 approval 与
  sandbox flag，以及 GPT-5.5 strict structured output 要求 object properties 全部进入 `required` 且
  `$ref` 不能携带 default sibling。

当前 Codex desktop 任务本身已运行在 macOS sandbox 内，内层 Coder 的 Codex CLI workspace sandbox
因此被操作系统以 `sandbox_apply: Operation not permitted` 拒绝。没有为通过验收而切换
`danger-full-access`；这次环境受限运行不记作完整 live DONE。普通本地终端可显式运行
`ASE_RUN_LIVE_TESTS=1 scripts/smoke-live-gpt55.sh` 完成宿主验收，脚本始终保留现场且不 merge。

## 当前边界与后续入口

- T033 Reporter 继续暂停；当前交付结果是 typed JSON、candidate commit、Artifact 和 Evidence；
- production v0.1 每个 delivery role 的 Task attempt budget 为 1，尚无持久后台调度循环；
- Product/Designer/Planner 的 accepted Artifact 可恢复，但上游 model attempt 尚无独立 durable ledger，
  provider 返回与 stage artifact 落盘之间仍存在可能重复计费的 crash window；
- 当前是 Codex sandbox + policy + worktree 隔离，不是容器级强隔离；需要时另立 container runner；
- PostgreSQL repository adapter、模型政策版本化、HTTP/SSE 和多实例协调留给后续任务；
- 单 Task 内仍固定串行 `Coder → QA → Reviewer`，不引入复杂 DAG、向量库或分布式消息队列。

本记录随 T034 集成提交归档；精确提交可通过
`git log -- docs/archive/2026-09-05-t034-production-team-host.md` 查询。
