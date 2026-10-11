# 实施与验证

先添加路由/额度红测，再实现分类、决定和中文匹配；用规范生成器同步 Schema，保留手写 guards。
增量命令使用主仓 `.venv/bin/python`，隔离工作区设置 `PYTHONPATH=src`。

完成 domain disposition、orchestration retry budget、独立 MySQL Worker/public Host、blocker text、
stopped-provider/completed DOM、repair schema regeneration 等明确测试；Ruff、strict Mypy、
`git diff --check` 通过，独立native Agent review无阻断。

## 结果

- 首轮路由红：21 failed / 7 passed；离线完整增量最终164 passed。
- 真实MySQL Worker：7 passed；Coder/QA/Review work1终局、work3工程wait且释放lease，
  重放wait不启动调用；既有typedtransient work1仍新claim重试并独立QA/Review。
- 公开Host：旧AUTH same-source/updated-source和completed-output两路径4 passed；
  真实unknown child work3调查1 passed、work1终局1 passed。
- 无recognized native失败被旧classifier标true，由相邻独立native-cli-unknown-failure任务修复，
  没有在fixture伪造原调用flag。终局路径补合法typed Manager协调stub，不绕过真实Manager claim。
- Node DOM：UI+stopped-provider14 passed；真实Chrome completed-output增量3 passed，
  后者使用新classification，精确proof和审批门保持。
- Schema由三个既有规范生成器同步；15个发布副本仅新增classification枚举。
  恢复原键序并去掉无语义生成噪声，手写guards不变。Root集成settlement字段时再生成。
- 既有plain knowledge-local-limit中文reason曾与测试/RESOURCE映射不符：保留原reason和
  legacy分类，更新精确中文RESOURCE映射；旧英文兼容仍在，不扩大旧恢复proof集合。

## 精确增量命令

```text
python -m pytest -q tests/domain/test_delivery_disposition.py tests/orchestration/test_execution_retry_budget.py tests/orchestration/test_retry.py tests/team_view/test_blocker_text.py tests/team_view/test_snapshot_schema.py tests/contracts/test_nontransient_delivery_schema.py tests/contracts/test_repair_schema_generation.py
python -m pytest -q tests/work_queue/test_worker_mysql.py -k 'nontransient or frozen_policy_retry'
python -m pytest -q tests/manager/test_production_execution_baseline.py -k 'unknown_native_exit or stopped_provider_retry or completed_output'
node --test tests/team_view/ui.test.cjs tests/team_view/stopped-provider-retry.test.cjs
NODE_PATH=/tmp/ase-rescue-ui-test-deps/node_modules node --test tests/team_view/browser/completed-output-rescue.test.cjs
```

Host组合首轮4 passed/2 failed暴露真实native默认true漏门；修复后unknown2分别复跑通过。
最后work1的真实终局清理空worktree是允许行为，断言原repository不变，不要求清理后的空路径存在。

存量数据处置：此任务只修新失败的分类。旧 Task/错误/事件/审批不得改写；Root 提供公开 HANDLE
结案与原 Requirement 的现有精确恢复入口。该入口尚未验证前不得宣称现有 K1 已恢复。
