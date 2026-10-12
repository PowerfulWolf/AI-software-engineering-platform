# 本轮实际入口增量验证（2026-10-12）

独立tree基线88128c3；实际fault_retirement.py/CLI/scripts/OSseam/schema，旧未消费foundation
module/test不提交。所有真实操作只针对测试创建的隔离Host/controller，未维护生产PID802。

- `pytest -q -p no:cacheprovider tests/web_console/test_fault_retirement.py
  tests/execution/test_owned_session_inspection.py tests/web_console/test_service_lifecycle.py`：
  **57 passed，11.23秒**，含25项真实维护/负向/故障注入。
- 最后添加Schema/intent/ACK链后，`pytest ... test_fault_retirement.py -k
  'schema_parity or actual_host_and_supervisor_retirement'`：**6 passed，3.13秒**；包含5项Schema
  parity及实际Host+supervisor全流程重验。
- strict mypy六文件（fault_retirement/owned_sessions/test_fault_retirement/maintenance CLI/
  lifecycle CLI/schema generator）：Success no issues found。
- Ruff check六文件：All checks passed。format check、git diff --check通过。
- 独立reviewer实际11项OS边界PASS；inspectionworker实际marker→production app四项PASS，
  包含normalenv不可覆盖及坏marker拒绝，未mock marker gate。由root合并该独立commit。
- 普通service script start/stop及跨checkout restart：**2 passed，26.50秒**。

命令使用主维护目录`.venv/bin`工具，`PYTHONPATH=src`、`PYTHONDONTWRITEBYTECODE=1`，
pytest无cache。真实boot/PID/executable/lsof隔离测试按需获准require_escalated。
只跑增量，无全量测试。无需SQL迁移，原K1Task/Operation/审批/verdict/草稿不变。

故障注入覆盖rename/chmod后、signalACK前、完整hash、receipt、marker前；同plan可重试且
exactHost只signal一次。Livewriter、坏lsof/probe/access、错birth/confirm/config/bytes/frozen、
同size日志篡改、链接/marker/receipt损坏均拒绝。真实Darwin/bin/sh脚本kernel/bin/bash和lsof
rc1闭文件语义先实际观察再收敛版本化门，未忽略失败或输出截断。

生产CLI与恢复说明见docs operations。大完整log初次hash耗时，inspection启动publication等待
120s。unknown旧子执行保留且需求不继续；回滚必须保留marker和只读兼容reader。
