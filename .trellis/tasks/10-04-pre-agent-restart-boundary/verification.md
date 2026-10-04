# 增量验证

只运行受影响增量测试，未运行全量。

- 前一轮 restart/continuation/semantic branch 共 70 项通过；新增 receipt/lock 三项因 fixture 初始化缺少参数失败，补齐后单独重跑 3 项通过。
- `test_worktree_collision_with_bootstrap_queue_restarts_on_unused_branch`：真实 Git/MySQL 测试通过（约 29 秒）；原 ACTIVE claim 拒绝，正常 reaper 后成功选择 recovery-2，fake Coder → QA → Reviewer → 联合 DONE，旧 Task/events 与保留工作区内容不变。
- `test_terminal_coder_preparation_drift_offers_exact_recovery`：通过，确认不 replay 原交付。
- 普通 Coder recovery 的占用分支追加 fixture 验证 recovery、recovery-2、recovery-3 与旧 ref 保留；单项重跑通过（约 23 秒）。

类型检查：四个变更源文件通过。扩大到测试模块暴露既有测试类型错误（直接给方法赋 Mock，以及 test_resume 的旧变量类型）；本次新增 Mock 改为 patch.object，不扩大修改无关测试。提交前 Ruff、format（8 文件）、源文件 mypy（4 文件）与 diff 检查通过。

真实 K1 尚未交付，以上 fake verdict 只属于独立测试数据库，不能作为生产验收。加载修复后通过正常 resume 生成最新计划并代用户精确批准，真实 QA/Review 仍必须独立执行。

回滚：平台空闲时回退 follow-up 提交并重启 Console；不删除任何旧计划、审批、Task/events/claim 或代码分支。
