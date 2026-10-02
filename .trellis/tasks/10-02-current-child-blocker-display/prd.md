# 当前角色阻塞展示

基线：06441d58021126fa9e1f1c0f915fac083ac5ed77。

生产 K1 的当前 Coder 已 BLOCKED，有明确 provider-route dirty-worktree 原因；但需求顶部优先显示泛化的 Manager 建议。正在运行的 Continue 也可能遮住该操作开始之后新产生的终态阻塞。

范围 / 允许路径：team_view/app.js、tests/team_view/{delivery-status,knowledge-gap,ui}.test.cjs、本任务、任务索引、live-team-view.md。只改只读展示，不修改 SQL、审批、verdict 或任务 checkpoint。

验收：优先展示同一 native delivery 最新阻塞的真实原因；当前操作请求之后的新终态失败仍显示已阻塞及准确角色；操作开始之前的旧阻塞不得遮住正在准备的新恢复。知识等待、租约中断、精确审批及活动 successor 保持其现有事实优先级。多仓和独立验证历史不能混淆。

验证：先写定向 Node 回归，RED 后修复，仅运行 delivery-status / UI / knowledge-gap 增量。独立 QA、Review。

存量数据处置：无需改库；原 Manager 建议保留在不可变记录中。静态资源刷新即应用新展示，活跃 Coder 不重启。回滚到基线 app.js，保留事实。
