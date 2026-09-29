# 验证记录

## 原问题与复现

原 Task 在首次 deterministic plan context 构建时超限：
`NEW → PLANNING → BLOCKED`、attempt=1、revision=2、无 artifacts、无 Coder 调用。
新增真实 Git/MySQL + fake adapters 回归修复前失败：
`Coder recovery stopped safely: recoverable Coder identity is missing, unsafe or ambiguous`。
新增恢复分支后，同一输入返回 RESTART_APPROVAL_REQUIRED；批准后新 Task 经独立角色完成。

## 增量测试（未运行全量 suite）

使用隔离 ASE_TEST_MYSQL_DSN，所有测试以 --tb=short 运行；未使用生产 DSN 跑测试。

```sh
.venv/bin/pytest -q --tb=short tests/recovery/test_pre_execution_restart.py
# 5 passed：正常、dispatch 后中断、attachment 后中断、后续 Coder 失败、后续 QA 失败。

.venv/bin/pytest -q --tb=short tests/recovery/test_restart_contracts.py tests/recovery/test_store.py tests/recovery/test_execution_records.py tests/recovery/test_verification_snapshot.py tests/recovery/test_delivery_continuation.py tests/recovery/test_remediation_context.py tests/web_console/test_manager.py tests/runtime/test_runtime.py
# 134 passed。

.venv/bin/pytest -q --tb=short tests/recovery/test_native.py::test_native_source_is_verified_read_only_and_rejects_corruption tests/recovery/test_resume.py::test_resume_discovers_approves_and_attaches_pre_candidate_coder_recovery tests/recovery/test_resume.py::test_resume_verifies_failed_candidate_and_delivers_remediation tests/recovery/test_verification_context_budget.py
# 5 passed，含 context-budget 的两个参数用例。

node --test tests/team_view/ui.test.cjs
# 6 passed；包含新增 restart 审批标题、提示和批准按钮断言。
```

共 144 个不同 Python 用例、6 个 JS 用例。最终补充评估归属与目标分支后重跑主正常用例：
1 passed，不重复计数。受影响 16 个 Python 源码/测试文件严格 Mypy 通过；
全部变更 Python 的 Ruff check/format 通过；git diff --check 通过。
Schema 由 generate-repair-schemas.py 同步，新计划/原 allocation wire tests 通过。
未进行浏览器人工视觉验收、真实模型交付或全量测试。

## 存量数据处置

只读查询与文件证据核验确认 K1：

- Requirement：delivery_multi_33d30fe0776a232e31617caa9e702b915dcb4c65。
- 原 Task：task_f887a81a33cfe89bdafd24ea01ab5ca8。
- Native checkpoint：9c82a97b81b596baeccb784c28acb3890fee3d9ffb000e1b97094ee32d777eee。
- 原基线与目标仓库当前 HEAD 均为 acc5f37f8282709472b69c1a9366ba0835dbf84c，工作区干净。
- 符合精确 initial-context failure；没有旧角色上下文/运行/产物/claim/admission/遗留工作区。

本次没有生产写入、没有启动模型、没有审批新计划或重启服务。无需改库/修改旧 journal。
应用新版本并重启后，在原需求点继续，核对新计划摘要后批准。批准前只生成方案不执行。
不得把之前失败的 Continue Operation 当作新计划的审批。

## 风险与回滚

本修复只允许原 Planner allocation 的首次 pre-execution failure，保持原 preparation/base；
不自动 rebase、不修所有未知中断，也不让新 Task 无限重生。128k 是本地估算预算，不保证供应商
调用或后续 QA/Review 一定成功。若新任务再因上下文超限，需处理具体前提，不重复套用旧审批。

代码可 revert 本次修复提交；产生新类型 dispatch 后不让旧服务推进它，保留兼容读取器并前向修复。
不要删除 Task、审批、artifact 或重新计算历史哈希来降级。
