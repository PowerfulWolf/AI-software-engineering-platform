# 设计

1. 单独 PreExecutionRestartPlan，不制造 RecoverySource/CapturedChanges 或历史 Run/Context。
2. 只接纳精确两条事件、attempt=1/revision=2、无 artifact 的初始上下文超限。
   通过只读 SQL 和已校验 journal/原批准链建立来源；拒绝存在角色运行/上下文/产物的矛盾事实。
3. 计划摘要绑定旧 checkpoint/Task/dispatch/events、批准链、父需求、目标 preparation/base、
   当前生产 context budget。相同事实返回同一计划；旧审批不能授权漂移后的计划。
4. 独立记录精确人工批准，使用 MySQL commit_continuation 创建 NEW successor，
   continuation_kind=pre_execution_restart；原三角色权限/调度/验收不变。
5. 原生 journal 在启动前接入新 dispatch；重启从该新 checkpoint 正常继续，
   重建上下文时验证新计划/批准/dispatch 并保留冻结父上下文。
6. 初版仅恢复原始 Planner dispatch 的首次 pre-execution failure，避免无限新建 Task。
   新 Task 再次失败按真实阶段分类；再次 pre-execution 失败需修复前提，不自动套用旧批准。

## 相关规范与模式

delivery-recovery、production-team-host、multi-directory-delivery、web-console；
verification_snapshot 的只读一致事务，remediation 的 fenced successor，store 的 immutable record。

## Good / Base / Bad

Good：修复 context policy 后精确批准，原需求 DONE，历史 BLOCKED 保留。
Base：未批准重复 Continue 无副作用。Bad：错误失败原因/已运行 Coder/审批漂移均拒绝。
