# 活动角色提示补充修复（2026-10-04）

真实 K1 恢复 Task 已处于 IMPLEMENTING，Coder item 为 RUNNING 且租约有效；父需求已正确展示 DELIVERING，但 next_action 仍沿用“请继续交付以恢复当前流程”。前端按当前任务隐藏继续按钮，提示却仍引导用户再次继续。

先写三角色增量回归，3 failed，复现原提示。`_with_execution_state` 只在非终态、无 blocker、角色与 Task 当前阶段匹配且 RUNNING + LEASE_VALID 时投影“正在执行，请等待当前执行完成”。知识等待/失效租约保持优先，UNKNOWN、仅 LEASED、错阶段和终态不能被猜测为执行中。只改变 TaskView/RequestView 文案，不改持久事实或 liveness，也不宣称发生模型调用。

增量：`pytest -q tests/team_view/test_live.py -k 'valid_current_role_lease or active_child_task_supersedes or current_queue_wait_overrides'`，7 passed / 26 deselected。Ruff、两文件 format、reader 源文件 mypy、diff check 通过。未跑全量。

存量处置：无需改库；空闲加载读侧修复后立即按现有队列事实重算。当前 K1 Coder 仍执行，暂不重启或更新目标基线。回滚提交并在空闲时重启，无需撤销审批或恢复数据。
