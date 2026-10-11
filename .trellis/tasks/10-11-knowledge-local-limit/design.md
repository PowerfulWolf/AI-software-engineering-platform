# Typed wait resolution

`KnowledgePreparationLocalLimit` 携完整已封存 KnowledgeInvocationOutcome，在 journal 首次失败与 replay 均恢复同 typed 错误。RetryingOrchestrator 通过 Worker failure-control 写 KNOWLEDGE_PREPARATION_LIMIT 非终态等待及 knowledge-preparation://outcome SHA；不在旧 claim 内重调模型。

`KnowledgePreparationRetryEvidence` 绑定 binding、phase、完整原 QueueClaim、intent/outcome SHA、所有独立 execution-record SHA、root intent SHA、initial/current/next/max timeout 与扩窗序号。没有真实 native local-limit STOP 的结果不获此证据。

DeliveryWaitService 在 Task process lock 内读取 exact lane/outcome/independent records，并核验历史 claim 的不可变身份、step、scope、source、当前无主 invocation、窗口链和工作额度。调查与 resolution optional 字段 None 时从所有 nested wire 排除，保持历史 digest。

MySqlRoleQueue.resolve_wait 在既有事务 fence 中消费精确证据，核验旧 claim、无 ACTIVE lease、Task snapshot/revision/source 与当前 WAITING；增加一次 Task attempt，关闭旧 item，创建同角色/source/checkpoint 的新 item 与 step，写完整 WAIT_RESOLVED。重放返回同新 item，不重复扣。

新 Context builder 从当前真实 claim 对应的 parent WAIT_RESOLVED 解析 timeout；递归验证至多 512 个工作祖先且每个 parent 精确读取最多两条匹配 next ID 的事件，同 role/checkpoint/source 的 provider 后继保留已消费窗口，不查询当前设置替换。扩窗本身最多两轮。第一版完整重做该角色知识两阶段，旧成功或失败调用仅保留审计，不能跨 claim 借用产物。

local-limit-intents 索引只定位已封存 outcome；collector 重新读取 lane intent/outcome 与独立 completion。索引失败保留真实停止和结果，same Run replay 只能幂等补索引，不能重启模型。

requirement_id 保留知识 binding 的原 scope；delivery_requirement_id 显式记录 collector 验证后的 native 父交付身份，None 从 nested wire 省略。既有 task_continue_* QA/Reviewer 必须具有同 Task/team/project/repository/role/source/snapshot 的独立历史 gap 与 snapshot 才能兼容 Task scope，不能只凭命名接受父需求。runtime、collector、history 复用 shared scope resolver。history 的父身份 keyword 只作用知识记录，不改变 preflight 的原 native scope。

## Good / Base / Bad

Good：真实知识 native timeout 后 exact 自动工程 admission 或人工决定，在原 Task 新 claim 扩窗继续。Base：旧 Task 无 policy，人工工程 exact proof 后消费。Bad：只有 pending admission 或无真实 STOP，把 provider transient 额度当本地工作额度，或当前 cfg 放大旧窗口。
