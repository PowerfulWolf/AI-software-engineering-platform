# T048 — 建设 Agent 主动知识检索与知识缺口闭环

## Goal

把当前“人工选择文档并在 Requirement 准备时静态注入”的知识库，扩展为 Agent 在执行过程中可以
主动、受控、可审计地检索和引用组织知识的能力。当知识不足、冲突或无法验证时，Agent 不得猜测，
而应产生结构化 `KnowledgeGap`，由 Manager 路由补充、澄清、研究或人工处理。与此同时，把 Trellis
工作纪律绑定到对应角色，并用可重复评测证明知识确实提高了交付准确性，而不是仅增加上下文长度。

T048 建立检索、缺口、角色 Skill 和评测四个闭环。导入文档后的异步解析、索引构建和增量加载属于
T049；T048 先定义稳定检索接口，并允许使用现有已验证 Markdown 文档的有界确定性词法检索 adapter，
不得等待 T049 才能验证端到端契约。

## Requirements

### 1. Knowledge Retrieval Skill

- 提供 typed、policy-bound 的 `search_knowledge` 与 `read_knowledge` Skill；Agent 不能直接遍历
  Team/Project sidecar，也不能传入服务端绝对路径；
- 查询必须绑定 `run_id`、`task_id`、`role`、`team_id`、`project_id`、允许的 Repository 范围、
  当前 Requirement 的 frozen knowledge selection 和 exact document digests；
- 搜索范围固定为当前 Team 通用知识、当前 Project 背景知识、当前 Repository 原生规则和适用的
  active Specs；禁止跨 Project 搜索；
- 搜索结果返回稳定 `document_id`、scope、title、section/chunk identity、source URI、document SHA、
  relevance facts 和有界片段；读取必须引用搜索返回的 exact identity；
- 所有查询、命中、未命中、读取与拒绝结果都写入 Run Evidence，并进入 Context Manifest；下游
  Artifact 必须能引用实际使用过的知识来源；
- T048 的 baseline adapter 采用确定性、有界、无需模型的 Markdown 标题分段和词法检索；检索接口
  不绑定具体 BM25、MySQL Full-Text、向量库或 embedding 实现，T049 可替换 adapter；
- 检索是补充 Context 的受控操作，不能改变 Requirement 已冻结的知识选择、Spec activation、
  Task 权限或 source revision。

### 2. Knowledge Gap Closure

- 定义不可变、Schema 校验的 `KnowledgeGap` Artifact，至少包含问题、所需决策、已尝试查询、使用过的
  scope/filter、未命中或冲突证据、影响范围、风险和 `BLOCKING/NON_BLOCKING` 等级；
- Agent 在缺少决定性事实、知识相互冲突、文档过期或来源无法验证时必须报告 Gap，不得把猜测写成事实；
- Manager 通过 policy-bound Skill 将 Gap 路由为：用户澄清、Product 补充业务事实、Designer 补充
  技术事实、受控 Research、接受明确风险继续，或 `WAITING_HUMAN/WAITING_DEPENDENCY`；
- Gap 的解答必须形成带来源、审批和 lineage 的 `KnowledgeResolution`；它只影响当前 Requirement 时
  进入 Requirement Artifact，拟复用到后续需求时必须走现有 Learning 的人工审批发布路径；
- 解决 Gap 后的新 Run 必须引用原 Gap、Resolution 和旧 Run，保留历史，不依赖恢复模型会话；
- 相同 Gap/Resolution 重放幂等；正文变化必须生成新版本，不能覆盖首次证据。

### 3. Trellis Skill 与角色绑定

- 建立 Team-owned、版本化的 Workflow Skill Registry，把 Trellis 工作纪律作为 typed Skill/gate，
  而不是只放在 Prompt 中；Skill 的输入、输出、版本、证据和失败行为必须可审计；
- Manager 负责 session/task start、复杂度 gate、恢复和 finish-work gate；Product 负责知识检索与需求
  事实确认；Designer 负责 before-dev 与架构规范检查；Planner 负责复杂任务拆解、依赖、风险和测试矩阵；
  Coder 负责 before-dev、实现检查和可复用规范建议；QA 负责验收矩阵与测试缺口；Reviewer 负责
  code/spec review；重复故障由 Manager/Reviewer 触发 break-loop；
- 每个 Skill 只能使用该角色允许的最小 ports、工具和工作区；Skill 不能授予 ambient shell、store、
  状态写入、模型路由或审批权限；
- 必须区分“执行性 Skill”和“Skill 设计建议”。Learning 发布的 Skill proposal 不得自动安装或执行；
- Skill gate 未完成、证据缺失或版本漂移时，不得静默推进下一阶段；是否阻塞由显式策略决定；
- 重试或被打回时从 durable Artifact、Spec、Skill evidence 和 checkpoint 继续，而不是从零依赖聊天历史。

### 4. Knowledge Effectiveness Evaluation

- 建立 Good/Base/Bad 的离线评测集，覆盖“知识中有答案”“知识未启用”“跨 Project 相似文档”
  “知识无答案”“知识冲突”“知识已替换/退休”“Spec 与背景知识语义不同”等场景；
- 同一需求分别在知识可用和不可用条件下运行可比较评测，至少统计引用正确率、虚构率、Gap 召回率、
  跨范围泄漏率、验收覆盖率、QA/Review 驳回率和额外 token/延迟；
- 知识中有答案时，Agent 的关键决策必须引用正确来源；无答案时必须产生 Gap，不能编造；
- Project A 的 Agent 读取 Project B 知识、读取未选择/已退休文档或绕过 exact digest，评测必须失败；
- 新知识或 Spec 只作用于新建/重新准备的 Requirement，不静默重解释已批准 Context；
- 同类 QA/Review 失败发布为知识或 Spec 后，回归用例必须证明后续需求能检索并避免同类问题；
- 评测报告本身是可重放 Artifact，绑定模型路由、Context、知识快照、Skill 版本和 source revision。

## Acceptance Criteria

- [x] 每个允许检索的 Agent 可通过同一 typed 接口搜索/读取当前作用域内知识，并返回 exact citations；
- [x] baseline 词法检索 adapter 不依赖 T049、模型或外部向量服务即可跑通契约测试；
- [x] 未选中、已退休、跨 Project、digest 漂移和越权读取全部 fail closed，并留下拒绝证据；
- [x] Agent 对未知或冲突信息产生 `KnowledgeGap`，Manager 能路由并用 `KnowledgeResolution` 恢复；
- [x] Gap 解决方案可以只属于当前 Requirement，也可以经人工批准进入未来 Project Knowledge/Spec；
- [x] Trellis Workflow Skills 按角色绑定，执行证据进入 Context/Artifact lineage；
- [x] Coder、QA、Reviewer 不能通过 Workflow Skill 扩大自身权限或跳过独立验证；
- [x] 评测能稳定区分正确引用、无答案报告、虚构和跨范围泄漏；
- [x] 至少一个端到端 fixture 证明：Agent 主动检索知识、引用来源、完成任务并通过 QA/Review；
- [x] 至少一个端到端 fixture 证明：知识不足时安全停下，补充并批准知识后从 durable checkpoint 继续；
- [x] Python models、JSON Schemas、`.trellis/spec/`、README/运行文档和测试保持同步。

## Decision (ADR-lite)

**Context**：当前 Knowledge Selection 能安全地把人工选择的文档注入 Requirement，但 Agent 没有运行时
检索工具，也没有“我不知道”的结构化表达。把所有文档一次性塞入 Prompt 会浪费 token，并在文档增长后
降低相关性；允许 Agent 直接访问 sidecar 又会破坏 Project 隔离、审计和 frozen baseline。

**Decision**：在 Knowledge Plane 提供小接口的深模块：检索、读取、Gap 和 Resolution。所有操作绑定
exact Requirement knowledge snapshot，并通过 policy-bound Skills 暴露。T048 先提供确定性词法 adapter，
T049 再实现异步增量索引 adapter；调用方和 Artifact contract 不因索引技术变化而改变。Trellis 工作流
同样通过 typed Skills/gates 执行，不把本机某个 `SKILL.md` 路径或自由 Prompt 当作运行契约。

**Consequences**：Agent 能按需获取知识并对未知内容 fail closed；知识命中和质量提升可被评测。代价是
增加 Knowledge Evidence、Gap/Resolution 状态以及角色 Skill 编排；索引时效与异步处理留给 T049。

## Implementation Plan

1. 定义 Knowledge Search/Read、Gap/Resolution、Skill Invocation/Evidence 的 DomainModel 与 Schema；
2. 实现 frozen-snapshot aware 的确定性词法检索 adapter 和 policy-bound registry；
3. 把检索与 Gap 工具接入 Product、Designer、Planner、Coder、QA、Reviewer 的独立 Context/Run；
4. 增加 Manager Gap routing 与 durable recovery；
5. 建立角色 Workflow Skill Registry 和阶段 gates；
6. 建立知识效果离线评测与端到端 fixtures；
7. 更新核心 Spec、README 和运维/诊断文档。

## Out of Scope

- 导入文档后的常驻后台解析、增量 chunk/index 构建与热切换；由 T049 实现；
- 自动把任意自然语言知识转换并激活为强制工程 Spec；
- 无人工批准地安装/修改可执行 Agent Skill；
- 全网搜索、跨 Team/Project 联邦搜索或通用向量数据库平台；
- 让 Agent 自己改变知识选择、Spec activation 或检索权限；
- 用检索结果绕过 Product approval、QA、Reviewer 或 Human Boundary。

## Technical Notes

- 当前知识选择入口：`manager/production_host.py::_knowledge_sources`；
- 当前 Context seam：`context/builder.py::FileContextBuilder`、`orchestration/context.py`；
- 当前 tool registry 只有 `read_file/write_file/run_command`，T048 应新增独立 Knowledge Skill seam，
  不能伪装成 repository file read；
- 当前 Learning 发布入口：`learning.py::ProjectLearningStore`；
- Repository 原生规则发现：`repository_profile.py::_discover_native_rules`；
- 必须遵守 `.trellis/spec/core/{architecture,contracts,python-runtime,team-workspace}.md`。

## 续作验收记录（2026-09-19）

本轮实现和任务相关验证已完成。完整测试结果、独立 QA/Review 引用、存量数据处置、
回滚及验证限制见 `docs/t047-t049-continuation.md`。代码仍保留在原独立 worktree，未提交、合并或部署。
