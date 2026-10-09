# 验证记录

## 原问题
- 在线 GET /api/v1/team?project_id=project_ai-project_034252eb3595 连续503 TEAM_UNAVAILABLE，4.946/4.419s。
- 最小旧处理报告key重開与非exclude_none嵌套dump两个新增回归先红，工程history报同样KnowledgeError RECORD_NOT_FOUND。
- 相同现存两份报告、独立调查、frozenproof完整；新增None字段使key漂移，并非证据被删除。
- 前端独立Team被挂起Operations拖住、失败清空history、Knowledge无deadline、late UPDATE重开已关闭详情、独立Status headers/body无deadline均先红再绿。

## 增量验证
- `.venv/bin/python -m pytest -q tests/domain/test_delivery_disposition.py tests/team_view/test_engineering_history.py tests/manager/test_delivery_wait.py`：87 passed（独立missingproof反例和standalone Schema测试随后单独通过）。
- `.venv/bin/python -m pytest -q tests/domain/test_delivery_disposition.py tests/team_view/test_snapshot_schema.py`：30 passed，含standalone事实Schema精确模型parity。9份embedded DeliveryFailureFacts Schema逐份与当前模型相等。
- reader相关新/既有增量：107 passed、7 MySQL cases未执行。范围包括test_joint_history_snapshot、test_task_read_snapshot、live非MySQL、retirement/journal-reuse/design-budget以及既有routecache、deletedverification/product projection。完整命令：`.venv/bin/pytest -q tests/team_view/test_task_read_snapshot.py tests/team_view/test_joint_history_snapshot.py tests/team_view/test_live.py tests/team_view/test_design_budget.py tests/team_view/test_deleted_verifications.py tests/team_view/test_run_attempt_cache.py tests/team_view/test_accepted_artifact_history.py tests/team_view/test_execution_history.py tests/manager/test_joint_journal_read_reuse.py tests/manager/test_requirement_retirement.py -m 'not mysql'`。
- `node --check src/ai_software_engineer/team_view/app.js`；`node --test tests/team_view/readiness.test.cjs tests/team_view/engineering-wait.test.cjs tests/team_view/operation-capabilities.test.cjs tests/team_view/ui.test.cjs`：最终102 passed。
- `NODE_PATH=/tmp/ase-rescue-ui-test-deps/node_modules node --test tests/team_view/browser/legacy-rescue.test.cjs tests/team_view/browser/polling-state.test.cjs tests/team_view/browser/async-boundaries.test.cjs`：31 passed，随后新增关闭late-edit真实Chrome定向1 passed；独立Status deadline新/相关7 passed。
- 8个修改Python文件 Ruff、format check、strict Mypy passed；git diff --check passed。未跑全量test。

## 真实存量只读核验
用正确self-iteration-ai config/runtime.env，只构造ProductionTeamReader与拒绝写入的SetupConsole，在隔离ASGITransport执行真实GET，不构造TeamHost/Worker，不启动服务或模型。
- patched GET200、原K1可见、完整2 requests/25tasks/约1.99MB wire。
- 当前Project全部4,931个JSON SHA清单读前读后完全一致。SQL使用原reader READ ONLY事务，零改库。
- 服务PID/生命周期未操作，运行实例仍需用户受控重启载入代码与冻结前端资源。

## 独占顺序性能
同机器、同一份真实完整facts；wire除as_of外精确相等。

| 指标 | 修复前HEAD reader | 修复后首次 | 再次独立读取 |
| --- | ---: | ---: | ---: |
| 秒 | 5.4852 | 3.1388 | 2.9230 |
| 历史JSON读取次数 | 557 | 225 | 225 |
| 历史读取bytes | 623760450 | 253531912 | 253531912 |
| Evaluation读取次数 | 8028 | 223 | 223 |

首次时间减少42.8%，历史字节减少59.4%，evaluation解码减少97.2%。每轮仍完整校验约253MB历史，无跨请求缓存。约3秒是当前实测，不承诺任意规模瞬时读。并行hash/HTTP压力下的10.37s样本排除出同比基准。

## 独立审查
console_read_review提供2个medium findings（用户关闭+晚到编辑、独立Status deadline），均回归修复；最终未发现剩余正确性/授权/完整history问题。

## 存量数据处置与回滚
无需SQL迁移、补证据、改原报告、改hash/文件名、重建需求或自动审批。原Task/队列/工作区/预算/QA Review结论均保留。用户受控重启后刷新原Project，随后自行决定既有恢复审批和基线更新。回滚本次代码将恢复慢读/旧报告错误，但不会删除业务事实。
