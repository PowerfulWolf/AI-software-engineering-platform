# 设计

读侧保持交付状态与执行事实分离。`Task.status` 保持 durable checkpoint；由非终态 RUNNING/LEASED + LEASE_EXPIRED 明确派生“执行中断”。父需求以已校验 successor 的阶段及 blocker 投影，清除已被该 successor 取代的历史 coordination。

Manager 提示优先使用当前 Operation、当前 blocked presentation 与 exact approval；单独的 PROPOSE_RECOVERY 建议不构成审批事实。历史 advice 仍在 journal 中。

测试矩阵：valid lease → 正常阶段；expired lease → 中断且成员不执行；CLOSED 历史 expired → 不阻塞；新 active successor → 隐藏旧 advice；当前知识等待 → 保持等待；exact approval → 真实待审批；无/旧审批 → 不冒充待审批。

执行租约根因与非终态恢复方案在独立诊断后补充。规范落点为 live-team-view.md、persistent-work-queue.md、delivery-recovery.md；不在未证实前放宽重试或 invocation admission。

## 已证实根因与受控恢复

pmset 日志证实 08:49:43 Idle Sleep → 08:50:57 Wake，共 74 秒。最后心跳 08:49:37，过期 08:50:37。Worker fail-closed 正确；不修改 TTL 或允许过期续租。macOS 服务以 `caffeinate -i` 绑定服务进程，退出自动释放。

新增 `RecoveryInterruptionPlan`、一次性 `RecoveryInterruptionInvocation` 和 exact `RecoveryAuthorization`。只支持 recovery 的首次 Coder：Task IMPLEMENTING/attempt=1、无后续 route/candidate/accepted artifact、原 invocation 存在、精确 seed 未改变、旧 claim 已过期且没有新 claim。计划绑定 Task/event/dispatch/seed/invocation/claim digest；scope、权限、原批准、源/目标事实不变。

提案和执行均取得 Task 排他锁以证明旧进程已停止。审批后只允许原 WorkItem 原生 reclaim 后的下一 generation；新 Worker 的实际 claim、run、context 写入独立一次性 receipt，旧 invocation 保留。不得退款或伪造 provider TIMEOUT；此为队列的同一逻辑工作项失租约重派，Task 预算和 attempt 不重置。单个原 plan 最多一次此恢复，第二次不确定中断仍 fail-closed。

审批前、claim 前、provider admission 前重验，任何 dirty 内容、Task/event、route、scope、授权或 claim 漂移拒绝。新调用仍通过 Coder→QA→Reviewer；不生成任何角色 verdict。
