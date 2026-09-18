# T052 设计

## Data flow

`JointExecutionPlan → ProductionJointBackend.integrate → IntegrationEvidence → JointDeliveryService → JointJournal → Console read projection`

命令执行器的启动失败/超时异常在 production backend 边界转换为稳定的失败 `CommandResult`。普通非零退出和零测试成功也转换为失败 evidence；service 只依据 typed return code 决定 `BLOCKED`，不读取原始异常。

## Recovery contract

`BLOCKED` 且带 `integration` evidence 的 Requirement 在下一次 `resume` 时追加一个显式 `PLANNING` checkpoint，保留旧 plan/evidence 在历史记录中但当前 plan 置空。Journal 只允许这个精确前置条件下的 plan supersession。Planner 重新产生完整计划，验证成功后清除当前 integration evidence，保留已完成 child 并重新进入 `INTEGRATING`。

## Validation matrix

| Case | Expected result |
| --- | --- |
| executable missing / PATH unavailable | failed command evidence, parent BLOCKED |
| timeout | failed command evidence with stable timeout summary, parent BLOCKED |
| pytest returns nonzero | normal command evidence, parent BLOCKED |
| all checks return zero and execute tests | integration evidence, parent DONE |
| blocked integration resumed | plan supersession checkpoint, bounded Planner call, no child rerun |
| ordinary plan mutation | journal rejects it |
