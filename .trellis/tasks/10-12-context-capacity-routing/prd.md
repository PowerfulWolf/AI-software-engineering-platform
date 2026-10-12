# 交付角色上下文容量失败路由

最终 provider 输入在序列化指令、输出 Schema 和 Context 后可能超过冻结输入容量。
该失败发生在交付角色模型启动前，不能归因于业务实现失败或重试额度耗尽。

目标：`ContextBudgetExceeded` 独立归类为 `CONTEXT_CAPACITY`。有工程授权和真实
WorkItem claim 的 Coder/QA/Reviewer 通过既有 owner fence 进入工程依赖等待，释放
Lease，保留 Task 当前交付 checkpoint、草稿、候选和历史。不得生成 invocation、
verdict 或退款。兼容无工程控制端口的旧入口仍可终止，但保留准确分类。

验收：三角色的调用前 Context 失败不调用角色 adapter；最终输入预检失败不启动模型；
wait 保留原 Task/事件和预算，不跳过 QA/Review；真实隔离 MySQL 的 claim 被释放，
重新调用仍等待。所有内嵌 `DeliveryFailureFacts` Schema 接受同一分类。

存量数据：本任务不改写已经 BLOCKED 的 K1。其恢复需要独立的 no-start capacity
receipt、完整旧补丁和当前基线核验，并走新精确方案/审批/真实 claim。
