# T018 Verification

## 结果

- `uv run --offline pytest -q`：303 passed；
- `uv run --offline ruff check .`：通过；
- `uv run --offline ruff format --check .`：198 files 通过；
- `uv run --offline mypy src tests`：96 source files 通过；
- `uv build --offline --out-dir /tmp/ase-dist-t018`：成功生成 sdist 与 wheel；
- `git diff --check`：通过。

## 关键反例

- AgentProfile 携带 `model` 或 project path 时，Pydantic/JSON Schema 拒绝；模型只能通过
  ModelPolicy + RunDemand 在 AgentRun 级别选择；
- 同一 Agent 即使在不同 attempt，也不能同时担任同一 Task 的 Coder 与 QA/Reviewer；跨 Task
  复用只受未来 Scheduler 的 capacity/Lease 聚合约束；
- WAITING_HUMAN、WAITING_DEPENDENCY、RETRY_SCHEDULED 缺少原因或 retry 时间时拒绝，且等待不
  占用 active Lease；
- `ProjectWorkspaceManifest` 使用旧 `agents/` layout、路径/Schema/digest 不一致时 fail closed，
  不自动删除或改写已有 sidecar；
- `ProjectId`、`RunId`、`ContextId` 统一从 `domain/identity.py` 导出，避免 context/store、
  agent/runtime 和 project registry 出现正则不一致。

## 边界

T018 只建立组织 Workforce 的事实模型和 sidecar/文档契约；T019 才实现 PortfolioScheduler 的
优先级、能力、capacity、Lease expiry 与 ModelRouter 的 deterministic route；T020/T021 负责
ProjectProfile、native-rule discovery 和 SpecCompiler 冲突处理；T022 才把这些事实自动绑定到
Runtime。当前单 Task 仍严格串行，不引入 DAG、消息队列、向量库、共享会话或自动 merge。
