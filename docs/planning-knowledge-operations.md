# 规划与知识运行说明

本轮任务使用完整名称区分历史编号：`09-17-t047-planner-agent-evolution`、
`09-18-t048-active-knowledge-closure`、`09-18-t049-incremental-knowledge-indexing`。
历史“Delivery 统一恢复”也使用 T047 编号，其记录保留，不代表本轮 Planner 任务。

## 规划

Manager 的确定性 PlanningGate 根据已批准 Product 与 Design 的结构化事实决定 SIMPLE/COMPLEX。
简单需求生成最小串行计划，不调用 Planner 模型；复杂需求产生有界工作包、依赖、风险、检查点和
验收测试矩阵。计划不分配 Agent、模型或 Lease。Manager 在实际派发时重新检查当前容量和依赖。
联合批准计划投影到各仓库后保留原工作图，不重新降级为简单计划。

被拒绝的计划与反馈保持不可变；下一版本必须精确引用前一版本及摘要，版本连续，不能弱化 Design
要求的测试等级。使用 `ase request resume <requirement_id>` 从 PLANNING checkpoint 继续；
预算终局耗尽或终态 Task 按已有显式恢复流程处理，不能直接清除失败记录。

## 知识导入与检索

上传、替换接口返回 HTTP 202 和 KnowledgeIndexJob。页面展示 QUEUED、PROCESSING、READY、FAILED、
RETIRED 以及失败原因和重试入口。服务内 Indexer 确定性解析、分段并发布完整索引，不调用模型。
导入后等待 READY，再显式选择供未来需求使用；选择变更不需要重启。已准备的 Requirement 保留原快照。

管理接口：

- Team：`GET /api/v1/admin/team/knowledge/index`；
- Project：`GET /api/v1/admin/projects/<project_id>/knowledge/index`；
- 重试：向相应 `/knowledge/index/<job_id>/retry` 发送 POST。

失败替换保留旧文档；新缓存验证并发布后才切换 selection 和退休旧文档。退休立即排除未来查询，
历史快照仍可按 exact digest 重放。Team 与各 Project 独立索引，单一作用域失败不阻止其他作用域。
相同内容及 parser/index 版本复用缓存；版本升级在完整新 generation 可用之前继续服务旧 generation。

Product、Designer、Planner 的生产入口以及 Delivery 各角色使用同一个受控知识接口。
检索绑定 Team、Project、Repository、Requirement、role、run、revision 和 frozen snapshot。
跨 Project、未选择、摘要漂移或未经同一 Run 搜索命中的读取被拒绝并留证据。
Delivery consultation 在最终 AgentRequest 构造前写入受预算约束的 Context，后续 Artifact 引用该 Context。
模型调用的实际 provider/model、usage 和耗时单独持久化。

## 知识缺口恢复

缺少决定性事实时，Requirement 进入 WAITING_HUMAN 并记录 exact gap ID；Task 保持最近 checkpoint。
Console 的需求详情提供“知识缺口”表单。展开当前事项，填写解答与事实来源/决策依据，再点击
“批准解答”。成功后显示“解答已批准 · 待继续”；重新打开页面仍展示原解答和来源，不需重复填写。
批准不会自动恢复交付，下一步由用户点击需求的“继续交付”。如再次出现不同问题，仅新问题需要解答。
历史 WAITING_HUMAN Operation 是当时的结果，不代表已保存的批准失效。

等价的本机管理 API 操作步骤：

1. 读取 `GET /api/v1/admin/projects/<project_id>/requirements/<requirement_id>/knowledge-gaps`，
   返回 `{gap, resolution?, is_current}` 列表，核对当前 Requirement 的 gap ID、问题、来源与风险。
   `resolution` 存在即已批准；只处理 `is_current=true` 且尚无 resolution 的事项。
2. 准备批准正文及来源。每个来源包含 `uri`、`content` 和该 content UTF-8 字节的 SHA-256。
   不允许密钥或敏感值进入解答。
3. 通过可信本机 Console 向同级 `/knowledge-resolutions` 发送 POST：

   ```json
   {
     "gap_id": "<当前 gap 的 64 位 SHA-256>",
     "answer": "人工确认的准确事实",
     "sources": [{"uri": "<可追溯来源>", "content": "来源正文", "sha256": "<正文 SHA-256>"}],
     "approval_reference": "<人工批准依据>",
     "disposition": "REQUIREMENT_ONLY"
   }
   ```

4. 对当前 exact gap 的批准成功返回 201。点击“继续交付”或执行 `ase request resume <requirement_id>`；
   平台保留旧 Gap、run、Context 和事件，用新 Context/run 恢复，不改变原知识选择或批准。
5. 如需复用到未来需求，将 disposition 设为 `PROPOSE_LEARNING`，再在“学习改进”独立审批发布。
   Resolution 批准只生成 proposal，不直接激活 Spec 或安装 Skill。

首次恢复必须使用原候选 revision。首次恢复链已持久化后，后续 QA 驳回产生新候选时可复用同一
Requirement 的已批准事实，并记录对首次恢复摘要的引用；不能把新候选伪装成原中断 Run。
人工解答同时进入标准 Evaluation HumanActionEvent，因此恢复成功仍保留“人工干预”归因。

生产 T046 Worker 已注入 QueueKnowledgeWaitPort，以真实 exact claim/token 释放 Lease 并进入等待。
重启后会验证已持久化的 Gap、route 和人工批准 Resolution，再恢复原 WorkItem；不伪造 claim，
不改写 Task checkpoint。只有进入 Worker 的 Task 才移交旧派发容量，详见
[T046 运维说明](t046-worker-operations.md)。

## 存量数据处置

本轮开发没有修改业务数据库、生产 Task、Operation、知识选择或审批。

- 旧计划和 approved Context 不迁移、不改写。旧计划 extension 缺失时仍保持原字节和 hash；
  新计划发布执行更严格的修订与覆盖校验。
- 首次启用知识 gate 时，针对既有非 NEW Task，持久化一次性 admission，记录已经封存的 legacy
  Artifact ID 与 digest。只对这些 exact artifacts 保留原生恢复路径；不补造 consultation 或改写旧
  Context。新产物及从 NEW 启用的 Task 必须具有知识证据。普通独立 QA/Review、候选和验收校验仍执行。
  因而“Artifact 已封存、状态事件未写入”的旧断点可用同一个 resume 命令恢复。
- 旧知识文档启动时按 manifest 验证并排入缺失的索引工作；正常 tick 从 READY 缓存及当前 selection
  重建被失败导入阻断的索引指针。保留原文、失败 jobs 和历史 Requirement。
- 如果此前竞态已覆盖用户意图，人工在对应 Team/Project 页面重新保存真实选择；平台不能推测授权范围。
- 原本已 BLOCKED/FAILED 的终态不被直接复位，仍需现有恢复计划与 exact 人工批准。

## 验证与回滚

运行 Python contract/fixture 全套、隔离 MySQL 集成测试、严格 Mypy、Ruff 和
`node --test tests/team_view/ui.test.cjs`。知识效果评测使用实际检索/consultation 的确定性 fixture，
包含启用/禁用对照和 Learning 后的后续需求回归；不等同于真实模型质量测量。

回滚前停止接收新工作并停止索引写入，再回退本轮代码和 Schema；保留所有外置 immutable artifacts、
Context、admissions、knowledge records、index 数据库、文档和选择。需要时使用 baseline 检索 adapter。
不要删除历史、清空表、重置审批或自动 merge 候选以实现回滚。本轮代码已合并到当前 `main`，
但尚未推送或部署；回滚时应回退对应合并提交并保留外置事实。
