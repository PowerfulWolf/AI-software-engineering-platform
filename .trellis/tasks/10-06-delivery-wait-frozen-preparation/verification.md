# 验证与交付

## 复现与修复

新增公共 Host 回归在旧代码明确失败于 `_PreparationCheckpointDrift`：临时真实 Git 中原批准
Task 等在 Coder preflight，主分支升级并新增 AGENTS；点击相同 typed 工程调查入口时，尚未
检查环境就因准备摘要变化拒绝。隔离 MySQL fixture 中没有真实业务模型调用。

调查改为读取原 sealed preparation，并显式保留最新 execution-baseline binding 的
`require_task` intent 校验。队列的精确 source 继续传给真实注册 executor discovery；通用
执行 drift guard、scope、角色、accepted Plan、原批准与恢复决定边界不变。

## 增量检查

```sh
.venv/bin/pytest -q --tb=short tests/manager/test_production_execution_baseline.py tests/manager/test_sealed_preparation.py tests/manager/test_delivery_wait.py
.venv/bin/pytest -q --tb=short tests/manager/test_production_execution_baseline.py -k 'changed_checkout or missing_preparation or corrupt_preparation'
.venv/bin/ruff check src/ai_software_engineer/manager/production_backend.py tests/manager/test_production_execution_baseline.py
.venv/bin/ruff format --check src/ai_software_engineer/manager/production_backend.py tests/manager/test_production_execution_baseline.py
.venv/bin/mypy --follow-imports=silent src/ai_software_engineer/manager/production_backend.py tests/manager/test_production_execution_baseline.py
```

相关三个文件 44 tests 通过（180.37秒）；补充封存 receipt/source 断言后只复跑新增三个场景，
3 tests 通过（6.48秒）。
Ruff、格式检查、改动文件 strict Mypy 通过。没有运行全项目测试。
独立只读 Reviewer 确认 frozen facts 方向、显式 binding intent 校验与 queued source 守卫正确，
没有放宽执行基线或恢复权限。

## 存量数据处置与限制

本轮未提交生产调查、批准、继续或基线更新，没有生产 SQL 或数据库修复。
原需求/Task/source、原批准及失败 Operation 保留。用户重新调查后才产生新 immutable proof；
真实环境缺项不由修复自动变成通过。不保证当前环境已就绪或需求已经继续。
最新版 main 的原生规范与原冻结规范不同，不能用 source-only 基线更新绕过该授权变化。

## 部署前检查与回滚

只读公共 Operations 显示零 QUEUED/RUNNING。可信服务脚本发现用户实际运行的是开发 checkout
的 ASE（PID 10149），因此装载以实际 managed executable 为准，不能沿用旧 PID 94152 假定。
回退本次提交并在操作空闲时可信重启即可；不回退数据库、需求或审计历史。
