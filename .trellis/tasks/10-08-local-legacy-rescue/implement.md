# 实施记录

## 调研

- 先读 AGENTS、core specs、恢复思考指南、legacy-execution-rescue 和 execution-baseline。
- 并行研究：旧执行归属/安全隔离、native 工具生命周期、Console/UI/Schema 消费者。

## 验证

- 本机执行调查与旧隔离模型：`pytest -q tests/manager/test_legacy_local_execution.py tests/manager/test_legacy_containment.py`，61 passed。
- 公共同需求恢复闭环：`pytest -q tests/manager/test_legacy_rescue_delivery.py`，5 个真实 Git/MySQL 隔离场景通过；覆盖无整机重启、活动执行/扫描不完整拒绝、later boot、消费前崩溃重放、消费后幂等重放，并保持原 Task/UNKNOWN/现场。
- Console HTTP 等待语义与不可读 OS 身份：`pytest -q tests/manager/test_legacy_containment.py tests/web_console/test_legacy_rescue_acceptance.py`，50 passed。
- 静态 Schema 合同：`pytest -q tests/contracts/test_local_legacy_rescue_schema.py`，5 passed；Schema 生成脚本重复运行字节不变。
- 改动 Python 文件 Ruff、format、strict mypy 和 `git diff --check` 通过；独立复核确认旧 wire/digest、精确工程授权、扫描安全边界、崩溃重放和 UI 等待结果没有未解决阻塞。

## 存量数据处置

没有数据库迁移，也没有改写已有 Requirement、Task、Run、审批、事件或工作区。部署后先按受控服务重启加载新代码；原 K1 仍保持 UNKNOWN，用户在原需求中点击准备恢复方案，查看本机检查结果后仅在真实可确认时提交对应的工程确认。方案通过后仍沿用同一 Task、分支和草稿，并重新经过 Coder、QA、Review；旧结果不会被补造。回滚必须保留新写入的 immutable rescue facts，并继续使用能读取这些记录的兼容版本。
