# 上游角色运行预算与当前执行提示

目标：已批准继续的 Planner 知识评估再次把旧 Manager 暂停说明当作缺少运行前提，产生 gap 848af72f。诊断端虽已加入预算，producer/knowledge payload 仍只传 attempts，缺少有效 policy；_attempt 清掉 coordination 却保留 Manager 的历史 next_action。

范围：multi_directory/service.py producer payload/attempt cursor、knowledge/agents.py 的知识评估指令、增量测试和规范。复用现有 typed StageBudget。不得修改 ProductScope/批准、冻结知识、retry counts、Lease、verdict 或持久化历史。

验收：三个上游角色都收到与当前执行窗口一致的 stage_budget；计数包含本轮预留，达到工作上限不否定已经通过 guard 的当前调用；预算不授予新范围/恢复权。重新预留时过期 Manager cursor 替换为当前执行提示，非 Manager 的设计/计划拒绝反馈保持。原 checkpoint 和 backend.client 的完整冻结输入不被 payload copy 改写；真正的外部能力/业务缺口仍可进入 HUMAN。

验证：Stage retry 实际服务链的第二次 producer 调用必须包含 capacity=1、window=1200、当前预留，并清除旧提示；三角色 payload、knowledge consultation、已有 frozen rules/artifacts 与 Manager receipts 增量回归。全量不运行。

存量数据处置：已通过正式知识确认接口核验原冻结 checkpoint、生产配置及本轮成功调用，批准 requirement-only resolution 52429d8a；原 gap、timeout、Manager advice 和 HumanActionEvent 均保留。空闲部署后正式 Continue；不删除 gap、重置预算或修改旧源。后续角色的新源码基线只经精确恢复/重规划绑定。

回滚：revert 修复并在空闲时重构 Host；保留全部既有记录和配置，无表迁移。
