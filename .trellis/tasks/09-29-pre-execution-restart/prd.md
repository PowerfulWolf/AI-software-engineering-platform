# Coder 启动前上下文阻塞恢复

## 目标与范围

修复初始 Task 在内部 PLANNING 编译上下文超限后，被误路由到缺少历史身份的 Coder 恢复。
保留旧 Task、事件、Product/Design/Plan 和精确审批；增加显式批准的新 Task 接续。
不放宽中断 Coder、候选验证、独立 QA/Review 或终态守卫，不执行真实需求。

## 验收

- 真实 Git/MySQL、fake role adapter 复现 NEW → PLANNING → BLOCKED、零模型调用。
- Continue 返回稳定的 pre_execution_restart 精确审批，不再索取虚构的 Coder Run。
- 无审批、错误摘要、事实漂移不能派发；重启/重放不能重复执行。
- 审批后新 Task 经 Coder、QA、Reviewer 接回原联合需求；旧 Task/事件不变。
- 仅执行受影响增量测试；同步 Schema、Console 和存量恢复说明。

## 允许路径与回滚

src/ai_software_engineer/{recovery,manager,web_console,team_view}、runtime.py、schemas、tests 对应目录、
scripts/generate-repair-schemas.py、docs/{operations/delivery-recovery,architecture/contracts}.md、.trellis。
回滚本次提交；已批准的新分支事实不可删除，旧版本不得执行新的 continuation_kind。
