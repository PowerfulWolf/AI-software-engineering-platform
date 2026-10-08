# 增量验证与交付限制

本轮基线为 `967c1fb`，修改平台代码和隔离 fixture，未访问生产 ASE 的写 API、审批、恢复、继续需求、
重启服务或修改生产数据库。Python 检查通过 `.venv/bin/python`、`.venv/bin/ruff` 运行。

## 验证

- `pytest -q tests/manager/test_wait_fact_collection.py tests/manager/test_team_host.py
  tests/manager/test_delivery_wait.py tests/manager/test_engineering_authority.py
  tests/team_view/test_engineering_history.py tests/orchestration/test_capture_reconciliation.py
  tests/contracts/test_continuation_schema.py tests/orchestration/test_continuation_store.py
  tests/orchestration/test_continuation_store_v2.py tests/agents/test_codex_cli.py`：223 passed。
  后续 parent/child composition 和 scope 补强单独重跑 Host/collector，见本文件最终结果。
- `pytest -q tests/contracts/test_json_schema_contracts.py tests/web_console/test_manager.py
  tests/web_console/test_transport.py`：174 passed，有两条既有依赖 deprecation warning。
- `pytest -q tests/work_queue/test_wait_resolution_mysql.py`：20 passed，隔离 MySQL fixture。
- `pytest -q tests/manager/test_production_continuation.py
  tests/manager/test_production_continuation_v2.py`：11 passed，包含真实 native stop/continuation
  场景。最初的失败是 fixture 的 TechnicalDesign 缺少结构化 source inspection，触发正确的
  `WAIT_ENGINEERING / VERIFICATION_ENTRYPOINTS_REQUIRED` preflight；补齐 fixture 后没有绕过门禁。
- Host/collector parent-child scope 与现有 receipt 增量选择：37 passed；未访问真实服务或生产数据库。
- `node --test tests/team_view/engineering-wait.test.cjs tests/team_view/operation-progress.test.cjs
  tests/team_view/delivery-status.test.cjs tests/team_view/requirement-detail.test.cjs`：49 passed；
  其中 engineering-wait 最新为 22 passed，覆盖收集失败时不再显示“检查通过”的回归。
- 使用现有缓存的 `NODE_PATH` 执行
  `node --test tests/team_view/browser/engineering-wait.test.cjs
  tests/team_view/browser/requirement-detail.test.cjs`：7 passed。浏览器全部拦截 fixture API，
  不访问真实业务平台；无 `NODE_PATH` 的子代理尝试缺 Playwright，由 Root 正确配置后已通过。
- 最新浏览器工程等待回归：3 passed；浏览器 fixture 仅调用本地页面与拦截的测试 API。
- Mypy：15 个修改的生产 Python 模块通过。Ruff check/format、JSON Schema 生成与
  `git diff --check` 通过。遵照用户要求，未跑全量 test。

测试核验自动授权不伪造人工主体、冻结权限不追溯、原调用/claim/完整库存精确绑定、失去 ownership
后的真实 stop 封存、完整 route final 找回、未知因果拒绝、幂等账本和预算、父产品需求与 native
child 的不同身份、完整历史超过 8 条、中文说明与陈旧 proof/处理建议失效，以及平台收集失败时
保留证据与当前处理结论不矛盾。

## 存量数据处置

无需数据库迁移。所有旧 Task、Run、审批、故障、源码现场和摘要保持原样。用户等当前操作与角色执行
自然结束，在服务空闲时加载新版本、刷新前端，进入**原需求**详情点击“让平台处理中断”。

若原最终结果已封存，平台找回验证后重放，不再调模型。若新版本已有真实 start/stop 与完整现场，
平台可以补封可信 receipt，再依原 Task 冻结授权处理。旧 Task 没有新自动能力但完整证明成立时，
页面给出明确的精确工程决定，产品权限无法替代工程职责。

当前旧第 6 轮曾显示结果未知、停止记录缺失和现场未核验。本轮没有改动或再次调查它，不能承诺
加载新版本即可自动恢复。如果真实旧资料根本没有封存，平台保留 `PLATFORM_ATTENTION` 和具体
中文处理报告，产品用户不用填写 hash，也不应反复点击调查。平台维护者需要修复缺失记录的
执行/封存能力；不能为了让状态变绿而补造停止、timeout、provider failure 或恢复授权。

## 真实限制与回滚

本轮覆盖已封存原 final 但 invocation outcome 未写入，以及原 start/真实 stop 已封存而完整
receipt 未写入的窗口。尚未实现独立 orphan-process 监督；Host SIGKILL 后只有 start、没有
可信 stop 的窗口仍需平台维护。处理完成也不等于需求交付，仍需真实新 claim 和独立同 SHA QA/Review。

回滚时先等待服务空闲并停止，再撤销本轮代码提交、重启和刷新。保留新增 immutable ledger 与其
兼容读能力，不删除 sidecar、草稿或审计，也不 reset 旧 Task/预算。当前需求尚未由用户验收。
