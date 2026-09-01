# Verification

## 结果

- `UV_CACHE_DIR=/tmp/ase-uv-cache PYTEST_ADDOPTS='-p no:cacheprovider' uv run pytest -q`：243 passed；
  包含 Task create/show/events、稳定错误处理和 handoff 非终态拒绝测试。
- `uv run ruff check .`、`uv run ruff format --check .`：通过。
- `uv run mypy src tests`：strict mode 通过，共检查 80 个 source files。
- `uv build`、`git diff --check`：通过（本任务未改变 wire Schema）。

## 关键反例

- `task create` 拒绝非 `NEW` 或已有 attempt 的快照；重复 ID 由 SQLite repository 拒绝。
- 缺失 Task、Evaluation Case 或非终态 Handoff 输出退出码 2，stderr 只有稳定错误行，不打印 traceback。
- Evaluation report 只能通过 TraceBuilder/Engine 重算；handoff build 只能读取 `DONE/BLOCKED`，不执行 merge。

## 边界

T013 提供离线事实消费 CLI，没有添加 `ase task run` 或新的 Agent。真实执行仍由应用层装配
`RetryingOrchestrator`、`AgentAdapter`、ContextStore 和 Git workspace，保持 v0.1 串行边界。
