# 精确回收事实的最小展示例外

`requestRecoveryDecision(request)` 继续使用原 canControlCurrentTeam、当前 Project、capability、
无 active Operation、当前 checkpoint 与 unconsumed exact approval 校验。仅在活动调度过滤
中，不再把 `step.status === RETRY_SCHEDULED && interruptedStep(step)` 当正在派发的工作。

`interruptedStep` 要求读侧核验的 LEASE_EXPIRED，RETRY_SCHEDULED 还要求 lease_expired
原因。Python `queue_reader.read_role_queue` 已校验同 Task/role/repository/attempt 的当前
assignment/lease、EXPIRED claim、真实 expiry 与 `lease_expired:<exact lease id>` 全等；
浏览器不会从字符串单独授予权限，也不会虚构 RoleQueueView 尚不存在的 lease_id。

READY、普通 RETRY_SCHEDULED、当前 RUNNING/LEASED 和 Task QUEUED/CONTINUE_REQUIRED 继续
阻止旧审批展示。尤其新有效 claim 替代旧计划后又过期，仍显示当前执行中断，并重新进行
当前中断调查/方案准备；不能直接采用先前恢复审批。

初版对所有 interruptedStep 放开过滤时，真实增量暴露上述新 RUNNING claim 过期会让旧
coder_recovery 审批重新显示；因此最小实现收窄到已回收 RETRY_SCHEDULED。保留此失败
断言及 RUNNING/LEASED 过期反向矩阵作为安全边界。

该修复只决定可见的待工程确认，不提交批准、不写入事实、不执行重试。已保存数据无需
改库，更新前端后从相同读侧事实重算；实际继续仍通过原精确审批入口。回滚该例外即可。
