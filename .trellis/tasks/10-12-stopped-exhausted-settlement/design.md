# 契约

StoppedFailureBudgetSettlement 绑定原 Task 完整快照、原等待工作项、调查 proof、invocation/start/outcome/capture/stop、完整inventory与capture摘要，以及合法 BLOCKED StateEvent。

StoppedBudgetSettlementService.try_settle 在已有 Task process lock 内获取 MySQL idle authority fence；先校验并原子封存记录，再在同 cursor 中写 Task/event/queue。replay 在 SQL 前重新验证原现场；SQL 后只接受完全相同 terminal Task/event/CLOSED item 和 settlement queue event。不存在跨连接持锁调用 append_event。

只接受 Coder 非临时 FAILED/no artifact、原 stop failed/no output/cause=None、原输入和完整本机 inventory 不变、普通 work budget exhausted、唯一未关闭工作项且无后继接受；任何不满足留在旧等待。此收尾不授权新执行。

DeliveryWaitHandling 新可选 budget_settlement_sha256，仅 BUDGET_EXHAUSTED 且无 resolution/collection failure 合法；None 省略，旧wire/hash不变。Host 仅同步已合法终态的 delivery cursor，恢复方案审批仍沿原入口。
