# T034 PRD：Production Team Host 与真实交付闭环

## Goal

让用户安装并配置一次平台后，仅提供目标 Git 项目绝对目录和自然语言需求，即可启动组织拥有的
Project Manager 团队。Product、Designer、Planner、Coder、QA、Reviewer 使用 GPT-5.5 和受控工具，
在外置 sidecar 与隔离 worktree 中完成可恢复、可审计的真实代码交付。

## What I already know

- T032 已完成 provider-neutral 的统一接单 facade、durable checkpoint、dispatch 和跨语言 fake-team E2E；
- 当前 `ase project ...` 因缺少 application-host 绑定而 fail closed；
- 用户选择 GPT-5.5 为主模型，并希望在该账号额度不可用后切换到有免费额度的 Qwen/DeepSeek V4；
- 用户要求正式运行使用 MySQL；本地存在一个已停止、属于其他项目的 MySQL 8.0
  容器，不应默认复用其数据卷；
- 官方 OpenAI 文档建议 GPT-5.5 的 Agent/tool workflow 使用 Responses API；
- T033 Reporter 保持暂停，本任务不得依赖或实现 Reporter；
- v0.1 继续保持单 Task 串行 `Coder → QA → Reviewer`，不自动 merge/deploy。

## Assumptions

- production host 使用 MySQL 8.0；SQLite 仅保留为离线测试与兼容后端；
- 默认模型别名为 `gpt-5.5`，默认 reasoning effort 为 `medium`；Qwen/DeepSeek 是显式
  provider fallback，不改变组织 Agent 身份；
- 当前 ChatGPT/Codex 登录额度通过 Codex CLI provider 使用；OpenAI/Qwen/DeepSeek 的 HTTP API
  provider 分别只从自己的环境变量读取凭据；
- API secret 只从环境变量读取，不写入配置、sidecar、日志或 artifact；
- 没有真实 API key 时可以完成 deterministic/contract 实现，但 live acceptance 必须由有效凭据执行。

## Requirements

- 提供可被 CLI 自动加载的 production team composition，不再要求调用方手写
  `configure_project_entry(...)`；
- 提供 MySQL `TaskRepository` 和 dispatch authority production adapter，保持现有领域 Protocol 与
  JSON artifact/event contract；连接信息仅从环境/配置读取；
- 提供项目独立的 Docker Compose MySQL 开发入口，但不得自动复用、启动或修改其他项目的容器；
- 使用 GPT-5.5 Responses API，保持 provider transport 可注入并使用结构化输出；
- 提供 provider-neutral Responses/Codex execution seam；支持 `gpt-5.5`、`qwen3.8-max`/
  `qwen3.7-plus`、`deepseek-v4-pro`/`deepseek-v4-flash` 的显式 ModelPolicy；
- 只允许 quota exhausted、typed rate limit 或临时 provider unavailable 触发有界 fallback；认证错误、
  policy violation、invalid artifact 和业务/规范冲突不得通过换模型掩盖；
- 每次 provider/model fallback 必须持久化选择原因、顺序、attempt 和 evidence；
- Product、Designer、Planner 产出已有 typed artifact，Project Manager 只通过现有 Skill/service 推进；
- Coder 只在其隔离 worktree 和允许路径内读写，并通过 typed tool registry 执行命令；
- QA 与 Reviewer 使用不同组织 Agent、独立只读/受限 worktree，并验证同一 candidate SHA；
- 所有失败都形成稳定、脱敏、可恢复的 checkpoint/evidence；
- `ase project start/reply/approve/status/resume` 保持面向用户的唯一主入口；
- 目标项目根目录不得写入平台数据库、日志、上下文、模型配置或 Agent 记忆。

## Acceptance Criteria

- [ ] 安装后只需设置必要环境变量，即可运行 `ase project start PROJECT --requirement TEXT`；
- [ ] MySQL 8.0 中 Task 快照、StateEvent 和 dispatch fence 保持原子、幂等和可恢复；
- [ ] Docker MySQL 停止、连接失败、认证失败和 schema 不兼容均 fail closed；
- [ ] 缺失/无效配置、API key、模型访问、网络失败均返回稳定错误且不泄露 secret；
- [ ] GPT‑5.5 主路由额度不可用时，可按显式策略切换 Qwen/DeepSeek，并能从事实回放切换原因；
- [ ] 非 fallback 错误不会触发静默换模型；所有 provider 都必须满足同一 artifact/tool policy；
- [ ] Product clarification/approval 可以跨进程恢复；
- [ ] Designer、Planner、dispatch 和串行交付均使用 durable lineage；
- [ ] Coder 在隔离 worktree 中形成真实 candidate commit，QA/Reviewer 校验同一 SHA；
- [ ] 至少一个临时真实 Git 项目完成离线 scripted-provider E2E；
- [ ] 提供 opt-in live GPT-5.5 smoke/acceptance 命令，不让 CI 默认消费真实 API；
- [ ] 全量 tests、Ruff、Mypy、offline build 和 `git diff --check` 通过；
- [ ] README 清楚区分“一次配置”和“每个需求只传项目目录 + 需求”。

## Definition of Done

- 生产 composition、Responses transport、角色工具循环与恢复契约均有 Good/Base/Bad 测试；
- CLI 不默选 fake Agent，不允许模型响应绕过 artifact/schema/policy；
- 新增环境变量、接口、错误矩阵和测试点同步写入 `.trellis/spec/` 与 `docs/`；
- live 验收若因缺少用户 API key 未运行，必须明确记录，不能伪报真实模型已通过。

## Out of Scope

- T033 Reporter；
- 自动 merge、自动部署和保护分支写入；
- 单 Task DAG、消息队列、分布式 worker、向量库；
- PostgreSQL；
- Web UI 聊天入口。

## Open Questions

- live GPT-5.5 验收优先使用本机已登录 Codex；若改用 HTTP Responses API，需要可访问
  `gpt-5.5` 的 OpenAI API key；Qwen/DeepSeek live fallback 分别需要对应 API key。实现和离线验收
  不以这些 secret 为前置条件。

## Technical Notes

- 模型 ID：`gpt-5.5`；Agent/tool flow 使用 Responses API；
- Qwen 默认候选：`qwen3.8-max`（高能力）、`qwen3.7-plus`（平衡）；DeepSeek 默认候选：
  `deepseek-v4-pro`（复杂 Agent）、`deepseek-v4-flash`（轻量任务）；
- reasoning effort 先以 `medium` 为默认基线，再由后续 evaluation 决定角色差异；
- production relational state 写入 MySQL；artifact/context/evidence 等不可变正文仍写入外置
  organization/project workspace，目标 Git checkout 保持干净。
