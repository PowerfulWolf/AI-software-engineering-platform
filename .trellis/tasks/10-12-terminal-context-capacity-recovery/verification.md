# Verification

## 增量验证

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q --tb=line \
  tests/recovery/test_context_capacity_input.py \
  tests/recovery/test_context_capacity_source.py \
  tests/recovery/test_context_capacity_entry.py \
  tests/recovery/test_context_capacity_sql.py \
  tests/recovery/test_context_capacity_plan.py \
  tests/recovery/test_context_capacity_workspace.py \
  tests/recovery/test_models.py tests/recovery/test_authorization.py \
  tests/recovery/test_terminal_baseline_context.py tests/recovery/test_baseline_wire.py \
  tests/recovery/test_restart_contracts.py tests/recovery/test_reapply.py \
  tests/recovery/test_terminal_baseline.py tests/recovery/test_terminal_baseline_sql.py \
  tests/manager/test_context_capacity_receipt.py
```

最新结果：186 passed in 77.97s。未跑全量；测试未连接生产或共享测试 MySQL。SQL 验证使用 fake
connection 与真实封存的 Git baseline，检查 consistent READ ONLY、结束 claim、全部 CLOSED、
typed/shadow columns、基线消费与 finally rollback/close。真实文件 store 的 no-start 负例拒绝
invocation start/outcome/provider route，原 attempt 1 历史仍保留。

- strict mypy：6 个变更 recovery 模块和窄 Schema 同步脚本共 7 文件通过。
- Ruff：增量 recovery 模块、4 个新测试和脚本通过；`git diff --check` 通过。
- Scope/receipt public routing、完整 retained patch、exact approval/new Task、不触碰旧任务和
  原批准、普通 Run 缺失与旧 Schema guard 回归均包含在以上增量。
- 初始 pure Source 测试在实现前真实红测：新模型/reader不存在导致失败；补实现后转绿。
- 独立 review 指出的 nullable baseline 有双层红→绿回归；artifact 与孤立 continuation
  receipts/admissions 的 7 个真实 no-start 负例先失败，再补 guard 后通过。
- follow-up strict mypy：5 个变更源模块和 receipt Schema 生成器共 6 文件通过；Ruff、
  `git diff --check` 均通过。普通 source validator 无默认变化，fake SQL 检查完整原 events 返回，
  legacy terminal 最后错源、精确原 Plan 引用和 queue acceptance 对齐后才能通过。

## 存量数据处置与限制

本任务没有写线上 ASE/数据库、重启服务、恢复工作区、封存 receipt、审批或调用模型。
主协调方授权后只读核验原 K1，完整 source gate 已通过：

- config `/Users/zhangjunshuai/workspace/code/.ase/config/self-iteration-ai.json`；只在内存读取
  同目录 `runtime.env`，不输出凭证。
- `RecoveryScope.delivery_id=delivery_dc5cf0aee44e5ffe0cb600557204e0d0` 为实际 native child，
  parent Requirement 仍为 `delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`。
- Repository `repository_c78e1680f621ff06c808aa9559666412444fbd7b`；目标真实 root 为
  `/Users/zhangjunshuai/workspace/code/ai-workspace/AI-software-engineering-platform`，不借维护 checkout。
- 原 Task `task_recovery_5536cf4e59ca28db0213bd719d50860d`、revision 3、attempt 2 保持 terminal；
  最后 exact legacy capacity event 原 source 为 `176997764f8b0d3a43c0b4daee5ee6424e9aae71`，
  其原 Plan ID 与 revision 2 plan_validated 相同。原 Context 与 latest baseline 证明真实 input
  source 为 `7ef2425427a122aeb4a9282d9fd32da063c8ee25`，原事件不改。
- latest binding `5cf552ecfda1df1bb122e664ab0c156e457d0d1eb936d5734ba652d96ca1538a`，
  完整 patch 604438 bytes、SHA `c085ce5563e49e446c861eb4771cc3634af2f8ad0ebb27181175d9cbf80211f5`。
  Context 255325 tokens 超过历史可用输入 252000；无本次 invocation/capture/route/outcome/产物。
- checkout 当前已正常清理；`require_clean_coder` 的精确 branch/SHA/manager-owned removal marker
  验证通过。只读 discover PASS，`failed_run_id=None`，没有重建或补造 capture/旧 Run。

部署后由主协调方在原需求公开继续入口准备
精确方案，核对收据/保留补丁、批准后再执行。原 Task 仍 terminal，不 reset、不退款；原需求
identity 保持不变。独立只读 reviewer 已复核 Schema parity、no-start、唯一 legacy source/Plan
compatibility（其独立 54 项测试通过），最终 clean-removal diff 等待最后确认；集成后的公开
proposal、精确批准和实际需求运行由主协调方另外记录。

## 回滚

受控暂停 ASE 新调度并保存所有计划、批准、收据后，反向提交本修复并按受控维护流程部署。
旧版本不能解释新 capacity 源；保留 append-only 记录，不能删除新记录或改库绕过批准。
