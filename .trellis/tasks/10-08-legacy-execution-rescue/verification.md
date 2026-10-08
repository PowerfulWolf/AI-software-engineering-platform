# 遗留执行完整现场救援：交付与验证

## 完成行为

旧 K1 的原 Coder 调用只有真实启动记录，最终结果、原进程停止记录和执行前完整现场没有
持久化。重复调查或审批已有报告无法创造这些事实。新版提供原需求详情中的“保留进度的
恢复方案”，使用新的整机启动观察、明确人工工程补证据及完整当前合法草稿继续原 Task。

救援保留原需求、分支、工作区、冻结范围、权限、预算和全部失败历史。原 Run 仍为未知，
不补造 outcome/stop/receipt/progress，不退款或虚构供应商故障。恢复本身不改源文件、HEAD、
index 或 branch；下一轮使用原 Task 剩余工作额度，建立真实新的 WorkItem/Run/Context/claim，
仍须由不同 Agent 执行 Coder、QA、Review，并验证相同 candidate SHA。

工程确认要求原执行一直在当前同一电脑本地运行、未迁移或远程执行、原执行后已完成整机
重启且时间依据可信。服务重启、lease 到期、PID 不存在均不满足。平台自动工程 policy 不能
替代这次人工补证据。公开操作、静态 Schema、历史展示与权限能力均绑定精确方案。

## 存量数据处置

本任务未执行生产审批、恢复、继续、重建或删除需求，未重启服务/电脑，未写生产数据库、
平台记录或业务工作区。无需表结构迁移或直接改库。现存原需求和所有审计记录保持原值。

只读定位：原 Task `task_dc5cf0aee44e5ffe0cb600557204e0d0`、未知原 Run
`run_9b76fb2865144f2abb6407923320ec4e`，原执行开始于
`2026-10-06T14:30:21.294710Z`；当次检查电脑启动于 9 月 26 日，早于原执行。
因此不能把当前服务重启当成可安全继续的依据。

用户加载修复后操作原来的 K1：

1. 保存其他工作，在服务空闲时更新代码，重启原执行所在的整台电脑，再启动 ASE。
2. 刷新原 K1 需求详情，在 Coder 等待处理区域点击“准备保留进度的恢复方案”。
3. 平台通过核验后，阅读电脑启动时间及草稿保留说明；仅在同机、本地、无迁移、原执行后
   整机重启等全部事实属实时勾选工程确认。
4. 点击“批准保留进度并继续原需求”，在执行记录查看新的 Coder、QA、Review 结果。
5. 若尚未批准的方案过期，重新准备；若绑定已保存但队列尚未消费，重新准备找回原方案，
   重试原决定。现场发生变化时保留所有文件并检查具体拒绝原因，不能清空工作区绕过。

更完整的步骤和失败说明见 `docs/user/legacy-execution-rescue.md`。

## 增量验证

所有真实 MySQL 验证仅使用测试钩子提供的隔离 fixture，未访问或输出生产凭据。
未运行全项目测试。

```sh
.venv/bin/python -m pytest tests/manager/test_legacy_containment.py tests/manager/test_legacy_snapshot.py tests/manager/test_execution_baseline.py tests/manager/test_execution_baseline_reservation.py tests/manager/test_execution_baseline_invocations.py tests/web_console/test_transport.py tests/team_view/test_engineering_history.py -q
.venv/bin/python -m pytest tests/manager/test_legacy_rescue_delivery.py tests/web_console/test_legacy_rescue_acceptance.py tests/manager/test_execution_baseline_invocations.py tests/manager/test_execution_baseline_reservation.py -q --tb=short -x
.venv/bin/python -m pytest tests/work_queue/test_baseline_history.py -q
.venv/bin/python -m pytest tests/work_queue/test_execution_contracts.py -q
NODE_PATH=/Users/zhangjunshuai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules node --test tests/team_view/browser/legacy-rescue.test.cjs tests/team_view/browser/engineering-wait.test.cjs tests/team_view/browser/operation-capabilities.test.cjs
.venv/bin/python scripts/sync-legacy-rescue-schemas.py
node --check src/ai_software_engineer/team_view/app.js
git diff --check
```

- 管理领域、快照、原基线/调用/预算、HTTP 兼容及历史读侧：89 passed。
- 公共 Console → Host → MySQL → native fixture、HTTP 与原 invocation/reservation：
  最终 23 passed，包含完整历史 `_invocations` 遍历；最后补查发现的继承基线读侧缺口已修复。
- 新队列历史边界：14 passed，覆盖真实父链、scope/allocation、source/digest 拒绝及两轮
  reserved/in-place 消费的旧历史与最近 epoch。原执行协议检查：6 passed。
- 真实浏览器：8 passed，涵盖可见操作、必须确认、旧契约/撤销能力、过期 closure 与重提。
- 相关 CJS 行为检查此前 36 passed；新增 Schema 静态验证此前 3 passed。
- 21 个变更 Python 文件 Ruff lint / format check 通过；14 个生产模块 strict mypy 通过。
- 五个相关静态 Schema 同步脚本已确认二次执行不再修改文件。`role-queue-execution` 中
  既有等待处置字段的缺漏一并补齐，仅增加字段和四个定义，不改变运行时模型或旧事实。

独立只读 reviewer 已复核领域、公开授权入口、UI、完整现场、crash replay、历史父链与
最近 epoch，未发现剩余 must-fix。浏览器操作全部发生在隔离 fixture。

公共 fixture 同时验证完整现场不变、原 UNKNOWN 没有 outcome/receipt、下一普通工作额度
且无 transient 退款、唯一 binding/consumption、人工证据事件、完整处理历史、不同角色 claim
及同 candidate SHA。覆盖 binding 已写而 SQL 未提交后再次整机启动的精确重试边界。

## 限制与回滚

这是特定旧版本机 native Coder 的工程救援，不是对所有 provider 的通用中断恢复。
同步 Responses 停止事实在 receipt 前仍存在内存窗口，是独立后续问题；本路径拒绝不确定的
远程/非 native/fallback 执行。未通过真实隔离、完整合法现场和预算校验时不会启动下一轮。
现有 K1 尚未恢复或交付，后续需要用户完成上述路径。

尚未写入新版救援事实时，可在服务空闲并停止后回滚代码至任务基线 `9a4c485`。
已写入新版 purpose、证据、批准或绑定时，保留能读取这些事实的版本并向前修复；不能部署
无法读取新增事实的旧服务，不能删除记录或工作现场来回滚。
