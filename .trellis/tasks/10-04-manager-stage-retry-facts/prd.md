# Manager 重试诊断的预算事实

目标：新 K1 的 Designer 首次达到 600 秒本地时限后，持久事实显示 work=0/5、transient=0/5、capacity=1/3、next_window=1200；Manager 输入却只有 advertised RETRY_STAGE，没有具体预算，返回 WAITING_HUMAN 要求交付负责人核实额度，造成可安全自动继续的生产任务额外暂停。

范围：manager/stage_coordination.py 的 typed StageBlockage 输入、Manager prompt、相应离线增量测试和组织规范。复用 multi_directory.budget.stage_budget，不另算额度，不改变审批、状态机、代码恢复或 verdict 权限。

验收：Product/Designer/Planner 输入携带机器计算的 StageBudget；本地窗口增长、工作/故障/容量耗尽与 advertised actions 一致；非上游阶段没有假造预算；有预算的原授权未完成 producer 可选 RETRY_STAGE，无预算或非 retryable 原因仍不可重试；存量 advice/context 不改写，input digest 变化不重置 Manager episode 计数。

验证：现有真实 JointDeliveryService + ProductionStageCoordinator + fake model 的 timeout→retry→design fixture，模型只在收到可核验预算时选择 RETRY_STAGE；受影响 stage coordination 增量测试、Ruff、生产文件 mypy、diff check。全量测试不运行。

存量数据处置：保留新需求 delivery_multi_74df2af872dd99c7b3369341c6a663c707aebb97 的首次 timeout 与 manager_run_701b57087e1f4574880053cfc66c6712。已按 GET 投影核验预算，通过 operation_d3a52e7f0abe098677ec9a5f3abc0917 正式继续，不改数据库或旧批准。部署等待当前操作结束；不静默改变其冻结源或角色工作区。新增源码基线必须通过既有精确恢复/重规划入口绑定，不能直接改 sealed source_revision。

回滚：revert 本修复，空闲时重构 Host；保留全部 Operation、checkpoint、context、Manager 和角色执行历史。
