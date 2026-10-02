# 实施与增量验证

当前 native delivery 的最新终态 child blocker 优先于泛化 Manager 建议。RUNNING Continue 只在 child.last_activity 晚于 requested_at 时让新失败覆盖活动展示；旧失败保持新恢复准备状态。知识等待、租约中断、精确审批、finalization 和已完成阶段使用原边界。

新失败的流程定位在 Task 状态 fallback 之后，Coder/QA/Reviewer 对应实现/测试/评审；没有实际角色时保留聚合 fallback。整个 blocked 流程没有 current 动画。

验证：
- 首次定向 RED：10 passed / 2 failed，复现 generic advice 遮具体原因及 RUNNING 掩盖新的终态失败。
- 独立 QA/Reviewer 发现父仍 DELIVERING 时 QA/Review 的 failed gate 正确但实现仍 current；新增三角色参数化与空队列用例，先复现两项失败，再修复。
- 最终 `node --test tests/team_view/delivery-status.test.cjs tests/team_view/ui.test.cjs tests/team_view/knowledge-gap.test.cjs`：48 passed / 0 failed / 0 skipped；独立 QA 48 passed。
- node --check 和 git diff --check 通过。
- 未修改 HEAD 夹具也有三项知识诊断失败，原因是模拟 Element 缺少 querySelector；补齐支持后恢复对真实异步诊断的检查。UI 回归明确切换到进行中分组，避免错误地在阻塞中0分组寻找活动卡。
- 通过 CUA 原生 Chrome 界面实测 K1 正在实现、Manager 处理中，旧审批提示消失。浏览器扩展认证不可用，原生界面可操作；不是外部 Playwright 绕过。

## 存量数据处置

无需改库。Task/Operation/审批/旧 Manager 建议及原工作区原样保留。新脚本普通页面刷新即生效，不重启活跃 Coder。回滚到 06441d5 的 app.js，不清理 sidecar 或重放 consumed approval。

K1 交付另由原生 ASE 推进，本任务通过不等于 K1 通过 QA/Review。
