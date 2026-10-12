# Verification

## 增量验证

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q --tb=line \
  tests/recovery/test_context_capacity_input.py \
  tests/recovery/test_context_capacity_source.py \
  tests/recovery/test_context_capacity_entry.py \
  tests/recovery/test_context_capacity_sql.py \
  tests/recovery/test_models.py tests/recovery/test_authorization.py \
  tests/recovery/test_terminal_baseline_context.py tests/recovery/test_baseline_wire.py \
  tests/recovery/test_restart_contracts.py tests/recovery/test_reapply.py
```

结果：105 passed in 25.44s。未跑全量；未连接生产或共享测试 MySQL。SQL 验证使用 fake
connection 与真实封存的 Git baseline，检查 consistent READ ONLY、结束 claim、全部 CLOSED、
typed/shadow columns、基线消费与 finally rollback/close。真实文件 store 的 no-start 负例拒绝
invocation start/outcome/provider route，原 attempt 1 历史仍保留。

- strict mypy：6 个变更 recovery 模块和窄 Schema 同步脚本共 7 文件通过。
- Ruff：增量 recovery 模块、4 个新测试和脚本通过；`git diff --check` 通过。
- Scope/receipt public routing、完整 retained patch、exact approval/new Task、不触碰旧任务和
  原批准、普通 Run 缺失与旧 Schema guard 回归均包含在以上增量。
- 初始 pure Source 测试在实现前真实红测：新模型/reader不存在导致失败；补实现后转绿。

## 存量数据处置与限制

本任务没有操作线上 ASE、数据库、服务或旧 K1。部署后由主协调方在原需求公开继续入口准备
精确方案，核对收据/保留补丁、批准后再执行。原 Task 仍 terminal，不 reset、不退款；原需求
identity 保持不变。独立只读 reviewer 正在检查最终实现，集成后的真实原需求检查另由主协调方记录。

## 回滚

受控暂停 ASE 新调度并保存所有计划、批准、收据后，反向提交本修复并按受控维护流程部署。
旧版本不能解释新 capacity 源；保留 append-only 记录，不能删除新记录或改库绕过批准。
