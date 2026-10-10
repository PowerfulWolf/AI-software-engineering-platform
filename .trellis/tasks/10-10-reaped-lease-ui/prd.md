# 已回收失效调度的恢复审批展示

## 目标与实证

HEAD 的 delivery-status 增量用例已证明：current Task 的 RETRY_SCHEDULED 队列已被读侧
核验为 LEASE_EXPIRED，wait_reason 为实际回收的 lease_expired:<exact lease id>，但当前
checkpoint 的未消费精确审批仍被 requestRecoveryDecision 的“活动调度”过滤吞掉。
这违反 live-team-view.md 的已接受中断与审批保留契约。

## 范围与规则

- 仅修前端展示：当前 Request 的实际 QUEUED/CONTINUE_REQUIRED 与真实调度继续优先。
- 仅已回收 RETRY_SCHEDULED 的活动 role_queue 过滤复用 interruptedStep：Python queue_reader 已校验当前 Task、role、
  repository、attempt、lease/assignment 绑定、EXPIRED 状态、expiry 与 wait_reason 精确匹配。
  浏览器不增加 lease_id，不从字符串单独推断核验或执行授权。
- canControlCurrentTeam、当前 Project、能力、当前 checkpoint、未消费精确审批与活动
  Operation 门禁保持不变；没有新增自动批准、执行、状态写入或重放。
- 普通 provider retry、无关 wait reason、新有效 claim 均不能变成中断审批。
- RUNNING/LEASED 的新 claim 后来过期，仍走当前执行中断路径，不重新显示之前准备的审批。

## 验收与存量数据处置

保留原失败断言，新增普通 retry、无关 wait reason、READY、有效 LEASED/RUNNING 的反向
验证。只跑受影响 Node 增量，不跑全量。无需改库：更新兼容前端资产并刷新后，从原读侧
事实重新计算；实际恢复仍由用户/授权者核对精确方案并点击已有批准入口。

回滚本次活动调度过滤的 interruptedStep 例外即可，原 Task、Operation 和审批 bytes 保留。
