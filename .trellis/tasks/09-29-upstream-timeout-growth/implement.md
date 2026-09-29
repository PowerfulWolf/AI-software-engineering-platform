# 实施与验证

1. 增量测试：`tests/agents/test_structured_models.py`、`tests/manager/test_stage_retry_budget.py`、`tests/manager/test_design_retry_budget.py`；先红后绿。
2. 实现 typed 超时分流、checkpoint 容量计数及有界时限、读侧预算和引导。
3. 同步 `schemas/team-snapshot.schema.json` 与 `.trellis/spec/core/execution-retry-policy.md`。
4. 运行上述增量测试、相关浏览器测试、Ruff 与类型检查；不运行全量 suite。

## 验证记录

- `.venv/bin/pytest -q tests/agents/test_structured_models.py tests/agents/test_model_diagnostics.py tests/manager/test_stage_retry_budget.py tests/manager/test_design_retry_budget.py tests/knowledge/test_consultation.py tests/team_view/test_design_budget.py tests/web_console/test_manager.py tests/contracts/test_json_schema_contracts.py -k 'not mysql'`：219 passed。
- `node --test tests/team_view/knowledge-gap.test.cjs`：25 passed。
- 受影响源文件 `.venv/bin/mypy`：通过；Ruff check/format：通过。
- `node --test tests/team_view/browser/design-budget.test.cjs`：环境缺少 Playwright 包，无法启动；已用无浏览器 DOM 测试覆盖时间预算呈现和重试隐藏，真实浏览器几何仍待验证。
- 存量 Requirement/Task/Operation 未修改；当前 `K1` 阻塞的 durable 原因是交付 Context 输入预算超限，非本任务的模型执行时间超限。
