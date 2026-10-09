# 验证与存量数据处置

## 根因与复现

生产错误为 `new progress does not match the bound execution source`。第一条救援 PAUSE 绑定精确撤销旧已接纳进度；第二条源码更新 PAUSE 绑定没有新进度需要撤销，字段为空。旧代码只读取最后一条绑定的撤销字段，因而重新选中了旧进度。真实 K1 另有四条已被此进度 supersedes 的祖先，仅排除最新 ID 仍会复活祖先。

修改前 `uv run pytest -q tests/manager/test_paused_baseline_service.py` 在连续两条真实封存绑定后稳定复现同一英文错误。公共 Host 回归用测试进程中的 HEAD 原版 resolver 内存回放，走 continue→service→collector 得到同一错误；未回退共享代码或改生产现场。

## 修复

- Stored resolver 从完整校验的绑定链派生累计精确撤销 ID，领域解析重新校验 Task、前驱和最新绑定。
- 产物选择器在排序前过滤精确撤销点及其同 Task/同 kind 显式 supersedes 祖先，完整历史继续用于校验和传递排序。
- collector、工作区准入、runner、继续请求复核、阻塞及终态候选重建共享该规则。
- 新进度沿用最近精确撤销 checkpoint 作为 supersedes，而不把旧 checkpoint 当本次执行输入；旧 QA/Review finding 继续传给 Coder。
- 未经撤销的真正错误源版本仍拒绝，显示中文；历史英文失败仅做展示映射，不重写 Operation。
- 没有 Schema、SQL、审批、Task/base_ref、权限或额度变更。

## 增量验证

1. `uv run pytest -q tests/orchestration/test_baseline_exclusion.py tests/orchestration/test_artifact_ordering.py tests/manager/test_paused_baseline_service.py tests/manager/test_execution_baseline.py tests/manager/test_execution_baseline_context.py tests/orchestration/test_execution_baseline_blocked.py tests/contracts/test_baseline_pause_schema.py`：43 passed，131.24 秒。
2. runtime worker 的 runner/retry/terminal/backend 相关非 MySQL 增量：53 passed，28.41 秒；加固后的新输入回归 7 passed，0.56 秒。
3. 隔离测试 MySQL 中 `tests/manager/test_legacy_rescue_delivery.py` 六个 public Host 参数分批全部通过，包含首轮真实进度→UNKNOWN→两次 PAUSE→明确继续→独立同 SHA QA/Review；`test_execution_baseline_invocations.py` 八项通过。曾出现一次 QueueNotFound，原参数及新参数串行复跑均通过；未改生产 SQL。
4. `node --test tests/team_view/engineering-wait.test.cjs tests/team_view/operation-capabilities.test.cjs`：54 passed；`baseline-progress-failure.test.cjs`：1 passed；`node --check .../app.js` 通过。
5. 修改范围 13 个 Python 文件 Ruff/check-format 和 strict mypy 全部通过，`git diff --check` 通过。
6. 独立只读 reviewer 复核所有关键 diff，无阻断发现；另独立执行输入/终态/paused 20 passed，排除/排序 19 passed。

未运行全量测试。补充核验 `tests/team_view/product-execution.test.cjs` 时发现四项既有失败；将 HEAD 的原 app.js 放入隔离临时回放也同样失败，原测试文件未修改。这四项分别涉及上游 active operation、delivery queue/retry、typed unknown execution 与 native bootstrap 的旧断言，不能将全量状态称为全部通过。

## 存量数据处置

仅使用正确 self-iteration-ai 配置，文件 store `read_only=True` 与 MySQL READ ONLY consistent snapshot；未构造 Host/Runtime/可初始化数据库的 Queue 或 Repository。没有 API POST、审批、服务重启、模型调用或工作区写操作。

真实 K1 `task_dc5cf0aee44e5ffe0cb600557204e0d0`：

- 两条 PAUSE 绑定均通过完整 plan/start/authority/patch/原生规范校验；最新 `c19b6dcf…` 使用源/base `a764c5f9…`。
- Task IMPLEMENTING，revision 17，attempt/work_attempt 7；唯一未关闭 Coder WorkItem WAITING_HUMAN，EXECUTION_BASELINE_PAUSED，精确绑定最新方案。
- 两条 binding 均无 baseline-continuations 授权；SQL release=0；ACTIVE claims=0。
- Coder HEAD、完整 inventory 与最新 binding 精确一致，staged index 为空。
- 用修复代码只读调用 Stored resolver 与真实 runner 的 `_current_coder_input`，结果一致：source/base `a764c5f9…`、active_progress=None；五个历史 progress 都没有复活。
- 20 个目标 baseline/artifact JSON 前后 SHA 相同；Task payload SHA `041081c414d0d7d528ce043500bcb3873d8dd1c8d7cfc54f540cb39b1e8342dc`、WorkItem payload SHA `d793b1c9c1c5e460880c5a5b39ba155774e4e225230a1a5ccd00163c2f07dcb1` 前后相同。

因此无需改库、重建需求、重新准备/批准基线或增加额度。用户在服务空闲时加载修复版本并受控重启，刷新原 K1，重新点击最新暂停绑定的“继续原需求”。精确现场核验、继续授权与 claim 仍由原公开路径处理。

## 风险与回滚

此修复锁定连续基线更新的历史输入选择，不能保证整个 ASE 全量测试或所有后续交付阶段均无问题。相关权限/Schema/历史完整性检查不放宽。无存量迁移，可在服务空闲时回退至 53d0eb4；回退会重新引入本次继续失败，绑定/进度和审计历史始终保留。

## 复盘

根因类别为隐式“最后一条绑定足够”的假设、变更传播遗漏和测试组合缺口。此前多轮公开流程只使用 timeout capture，没有真正已接纳 checkpoint；真实存量五轮 supersedes 又暴露了只过滤单 ID 的第二层问题。现在通过共同 selector、完整链领域结果和 public checkpoint组合回归防止重复。相关同类运行输入、准入、请求复核和终态候选点已一起检查，规范与恢复思考指南已更新；仓库没有对应 src/templates 规范模板。
