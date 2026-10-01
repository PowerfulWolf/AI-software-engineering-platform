# 实现与运行记录

- 使用 start / before-dev / diagnosing-bugs 流程定位；首先复现 structured timeout 误分类：
  transcript 含 authentication/401 时预期 TIMEOUT，实际 AUTHENTICATION_ERROR；6参数中5失败。
- 原生 Git/MySQL fixture 复现已接纳 progress 后 attempt2 知识失败，旧发现器报 missing Coder identity。
- 改用真实上一 attempt 的封存 progress 与精确事件证明；不伪造当前 attempt 模型调用。
- structured CLI 使用 JSON 输出，并区分 provider error 事件与模型/工具文字。
- 独立 Reviewer / QA 指出前轮 pre-provider retry 的 freshness 和历史 parent 校验风险，
  核实其与当前真实事实不符后移除整个未发布扩展。保留前轮已持久化计划中的3项 retry_of_* 字段作为只读Schema兼容；所有执行入口明确拒绝此历史分支。
- 独立 QA 用真实 CLI + 本地假403服务证实诊断仅在stdout JSON事件，补上该回归并修复。
- 源数据只读校验成功：task_recovery_7bf274ef749e81bb78aa504df594278c attempt2，
  run_f417cbcdfcda49b0b80ea666085f50ea / ctx_f1ca31e32f3f3cafd71145e0fb43e9f2d49ae9ef94607f69af4019dc26f164a6。

## 存量数据处置

不改库。最新 Task 的 8 文件保留；旧 5 文件 seed 不覆盖新工作。Console 更新后发起
`CONTINUE_DELIVERY`，由平台生成当前完整 capture 的精确恢复计划，再按用户已授权代理审批。
原有 BLOCKED Task、状态事件、审批、模型路由和worktree全部保留。后续新 Task 仍必须独立 QA/Review。

## 验证

- structured模型测试：35 passed（0.25s）。
- 原生progress恢复+完整离线独立角色闭环：单例通过（188.19s），复核185.33s；耗时主要为重复Git/current-facts验证。
- 独立QA恢复契约测试：43 passed（1.20s）。
- 相关 Ruff、MYPYPATH=src 的5文件 Mypy通过；git diff --check通过。
- 最新增加的拒绝反例随 test_native.py 的增量运行核实，结果另补。未运行全量test。

## 回滚

撤销本任务三个平台代码文件的修改并重启服务。不要删除/修改生产审批、Task、Artifacts或工作树；
回滚后只会失去对该特定失败的发现能力，不会改变已生成candidate或verdict。

## 实际平台推进

- Console proposal `operation_2f4e18a62d09ff6af6a92227d5399b52` 成功返回 Coder 恢复审批。
- 新计划 `48183639b355e838eb1d26e265d2f00ad34fd3088e1267a6482372db8fb76c40`，
  source Task 为最新7bf，保留8文件，目标仍为 acc5f37 基线，无新增权限。
- 依据用户代理审批授权提交 exact-plan Continue；等待原生独立角色交付。
- 过程中发现前轮实验 retry 计划已落盘，保留其wire/digest读取兼容，不删除历史；
  current-facts与attached backend两入口显式禁止重新执行该历史分支。
- `test_native.py + test_structured_models.py`：45 passed / 1 fixture failure（219.99s）；
  唯一失败是旧joint fixture没有Manager stub，隔离无关coordinator后该用例单独通过。
  本次新增进度/损坏封存/后续route/漂移/恢复独立角色用例已通过。
- 最新纯增量组合：test_models + test_progress_source + test_structured_models，58 passed / 0.57s。
- Ruff、10文件Mypy通过。没有运行全量tests。
