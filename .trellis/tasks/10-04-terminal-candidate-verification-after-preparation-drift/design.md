# 设计

`DeliveryResumeController.resume` 先判断终态是否已经有候选 revision。候选存在时先读取当前
候选验证 ledger：有 completion 就交给现有 completion continuation；没有 completion 或没有当前
计划则保持候选分支，生成 fresh verification plan，不再调用旧的 `retry_interrupted_stage`。

候选不存在时保持原有顺序，继续由 native retry、pre-execution restart 或 Coder recovery 分类。
该分支只改变恢复入口的调用顺序，不扩大 Agent 权限，也不改变验证计划的审批和候选事实校验。
