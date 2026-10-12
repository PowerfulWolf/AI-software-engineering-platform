# Team 当前摘要与完整详情分开读取

## 问题、目标与边界

部署 9cccb5b 后一次顺序 GET 仍为 12.84 秒、2802572 bytes；2 个需求/25 个任务中，
文档及 timeline/execution_history 合计约 2.69 MB。不用两次单点推断稳定延迟改善或无泄漏。
列表持续读取准确当前状态，打开需求/任务时独立读取完整正文与全部历史，减少未选中正文
装配/传输与前端整历史 JSON 比较。保持独立验收、精确审批和 v0.1 交付硬边界。

本任务先后端契约，再前端整片验收。不更改执行/恢复/预算状态机，不新建需求、不改库，
不建设长期成功缓存、分页索引或后台 worker，不同时重构整体 Console 布局。

## 后端接口与当前事实

新增独立 `TeamSummary v0.1`、`TeamDetail v0.1`（request/task discriminated union）及发布
Schema；只读 `ProductionTeamReader.summary(project_id)`、`detail(TeamDetailQuery)`。
`GET /api/v1/team-summary?project_id=…`；`GET /api/v1/team-details?project_id=…&kind=request|task&id=…`
要求 exact requirement checkpoint，实际 SQL Task 另有 exact Task ID/revision/intent 期望；
预派发记录由原 native checkpoint 定位，不伪造 revision。结果 scope 绑定 Team/Project/
Requirement/resource 和适用 Task 身份。`/api/v1/console` 宣告 `team_read_contract_version=v0.1`。
旧 `/api/v1/team`、`TeamSnapshot v0.2`、现有 Schema 保持。无新能力用旧路径；声明新能力后
新读取错误需真实失败，不能用旧路径遮掩损坏。只接收 typed IDs，不接受路径/source URI。

Summary 保留 Team/Project/Agent 和所有需求/任务卡片。Request 排除 dialogue/documents；Task
排除 documents/timeline/execution_history/runs。未读字段直接不属于新契约，不能用空数组冒充
没有记录；无独立可信计数时省略或明确 unknown。其余当前字段应与完整旧投影一致：

- Request scope、stage/checkpoint、execution/blocker/next_action、失败阶段、知识 gap/route、
  recheck/recovery、预算与 coordination。
- Task owner/source/work_kind、Task ID/revision/intent、plan/status/checkpoint/terminal、
  candidate revision/branch、execution/failure/next_action/assignments。
- 完整当前 role_queue：work ID/status/attempt、lease 观测、wait_disposition 与 digest、
  pending_baseline_continuation。Operation 完整选中 hydration、active completeness 与
  Console readiness 保持独立。分配模型、调用完成和执行器在线仍是不同事实。

禁止 `summary=snapshot().strip()`。在装配处复用 ownership/current 判定并跳过全体正文
pretty serialization、可选旧历史展示和历史 Task 的完整 artifact/run 正文 hydration。
当前状态需要的 complete events/artifacts/receipts/disposition 先核验，不能过早丢 timeline。
原 current successor、跨 Task ownership、角色归属和授权鲜度保持。Summary 只证明其当前
字段，不宣称未读的历史正文已验证；旧 full 与精确选中 detail 保持完整历史契约。
使用短同步 decode/source scope，不增加跨 HTTP cache。

所有读取共用原 worker-owned 并发限额；coalescing key 含 mode/project/kind/resource/expected
identity，只允许完全相同 query join，取消等待者不能提前释放真实同步 worker。Operation/
准备进度独立不被慢 full read 阻塞。未知/删除资源 404、期望版本漂移中文 409、坏记录 503；
读取前后核对 ownership 与版本，无部分成功，不构造 Host、prepare/reconcile 或写事实。

## 完整详情与前端

Requirement detail 保留完整讨论/附件元数据/阶段 documents；Task detail 复用完整 TaskView：
timeline、跨 Task execution_history、history_task_ids、documents/runs。首片不做分页，不限制
8 条/最近 N 条，不截断 QA FAIL/Review REJECT、Coder 输入 lineage、patch 或 Context。

前端 snapshot 仅当前摘要；所有 controls 从 fresh summary 取身份，独立 detail state 仅正文，
不能把旧 header 混回当前 controls。showDetail 精确读取一次，相关 checkpoint/Task identity
变化后失效、提示更新并重读。A→B、Project/Team 切换、关闭用 abort+generation guard；旧响应
不得发布。5 秒摘要 tick 不重取/重建正文，保留展开、选中文本、滚动、草稿和审批 checkbox。
正文标记读取版本；只保留当前 selection 与必要 parent body，离开释放。

Product 批准须等完整对应当前 checkpoint 的 ProductSpec 已读、spec ID/digest 匹配；知识
解答、恢复计划、基线/规范批准仍需完整当前 Operation/body 和 exact digest。失败不能冒充
无产物或启用批准；旧正文只供标记后的历史阅读。DocumentView.sha256 是原事实 digest，
不能当脱敏 content 的字节 SHA。POST 沿用精确 checkpoint/task/work/source/disposition/plan/
authorization，由服务器重新 fence；summary/hash/ETag 均不是执行权威。

## 验收与增量验证

1. Python/发布 Schema 一致；同 fixture 每个 summary current 字段等于旧 full，旧 wire 不变。
2. 增加大正文与多轮历史后 summary 无正文，不调用旧 Task 完整展示 hydration；必要当前
   authority/SQL/queue 观察不减少，不 cache READY。
3. Detail 逐项等于旧 full 的选中资源，覆盖 12+ 轮 QA/Review 返工及完整 Coder lineage。
4. 跨 Project、错 owner、删除、版本漂移、损坏、alias、symlink fail closed；磁盘/SQL 无写。
5. Worker gate 不串 shape/resource，精确 query bounded join，取消不放 worker，结束释放大对象。
6. 前端测试旧服务 fallback、新服务失败关闭、完整 ProductSpec 门禁、乱序导航、关闭回收、
   草稿/checkbox/阅读保留、新 QA 反馈。复用现有 operation-summary-reading、detail-read-freshness、
   task-detail-reading、execution-history、polling-state/readiness 及 Browser fixtures；不跑全量。
7. 空闲部署后顺序测 summary/detail latency/bytes、完整历史等价；必须证明未装配未选中正文，
   不用 payload 变小代替后端成本证明，不设便携机器固定耗时阈值。

## 存量处置、风险、回滚

无 SQL/journal/审批/Task/Operation/receipt/worktree 迁移或重建。空闲受控加载后刷新原需求；
完整记录通过 detail 与原 v0.2 仍可读。回滚新 capability/GET/前端读模式保留旧 full 和全部
durable facts、已发布 capacity reader；不重置预算或审批。

风险：过早省 timeline 会丢当前 disposition；跳过历史会改变 current successor；旧 detail
复活批准；正文未读就批准；只按 Project coalesce 会串响应；多读取并发增加内存；仅 strip
wire 不减少后端成本；原 digest 与脱敏 digest 混同。均须对应负例。
