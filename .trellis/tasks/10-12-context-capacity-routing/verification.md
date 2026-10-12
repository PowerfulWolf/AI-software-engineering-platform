# 增量验证

基线 `7ef2425427a122aeb4a9282d9fd32da063c8ee25`。使用主仓已锁定 `.venv`
解释器运行、`PYTHONPATH=src` 指向本隔离工作树。未运行全量测试，未操作生产数据库或服务。

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/orchestration/test_context_capacity_wait.py \
  tests/domain/test_delivery_disposition.py \
  tests/orchestration/test_retry.py \
  tests/orchestration/test_execution_retry_budget.py \
  tests/orchestration/test_platform_contract_wait.py \
  tests/orchestration/test_baseline_history_inputs.py \
  tests/orchestration/test_execution_baseline_blocked.py
```

结果：123 passed。包含三角色的 Context / final-input failure、新旧入口、当前执行基线
source、原 QA/Review、真实额度耗尽、故障重试和完整嵌入 Schema 同步。

在显式 `ASE_TEST_MYSQL_DSN` 隔离测试库中串行运行：

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/work_queue/test_worker_mysql.py -k context_capacity
PYTHONPATH=src .venv/bin/python -m pytest -q \
  'tests/manager/test_production_backend.py::test_host_records_isolated_delivery_without_polluting_project[1-False]'
```

分别 1 passed。Worker 用真实 claim 验证 `WAITING_DEPENDENCY`、released Lease、保留
IMPLEMENTING/attempt/history、无 Coder provider launch 和重读仍等待；Planner
初始化超限仍无角色 claim，以准确 `CONTEXT_CAPACITY` 终止。

`tests/manager/test_context_capacity_failure_code.py` 与 public unified entry 增量模块
另有 19 项通过，封存/重读 capacity checkpoint 保持独立分类。
10 个变更 Python 文件的 Ruff check、Ruff format --check 和 strict mypy 均通过。

## 存量数据处置与限制

新分类不会重新开启已 BLOCKED K1；旧 `BUDGET_EXHAUSTED` 封存记录保持原 bytes。
待独立 no-start receipt/source reader 接入后，在同一 Requirement 准备精确恢复计划，
核验完整 Context、retained patch、最新 baseline，批准 successor，再走新真实 claim、
Coder、独立 QA 和 Review。无直接 SQL 修改、历史删除或重复 Requirement。

本子任务仅提供分类与等待；最终输入容量 receipt、存量 successor 恢复和中文 UI 投影
由主任务集成验证，不将此测试结果称为 K1 实际交付或浏览器视觉验收。

## 回滚

空闲时回滚本代码；一旦持久化 `CONTEXT_CAPACITY`，须保留兼容枚举 reader，优先
前向修复。不得删除 queue wait/history、重新使用旧 Lease 或直接重置终态 Task。
