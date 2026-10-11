# K1 独立规范同步的正式路径研究

## 结论与当前边界

冻结 K1 要求有维护权限的独立操作者同步组织规范，并留下由 QA/Reviewer 核验的真实记录。
Coder 不得写 Trellis，不能扩大 Coder allowlist。**现有正式 KnowledgeResolution 知识答复
路径可承载真实维护记录及规范正文，不因缺少专名 SpecSyncRecord 就必须增加平台功能。**
既有路径具备有界正文、URI/hash、精确人工批准、不可变存储、后续必需 Context 和人工审计；
独立 QA/Reviewer 可结合受控 Git 只读工具核验真实维护版本。

前提是平台真实生成且当前正在等待人工的 exact knowledge gap；下一同 Task、同角色、同
冻结 snapshot 的真实 Run 才接收答复。不能主动伪造 gap、把 Coder 答复当 QA/Review 来源，
或将手工 JSON、fixture、聊天直接宣称生产验收。未实证上述前提，不声称本项已经完成。

本次只做只读研究与文档，不操作审批、运行、存量数据、角色工作区或重启，不开发新 API，
不重建需求、重置 Task、修改冻结产物或 native rules。

## 冻结来源与原文

通过当前 Repository sidecar 的 `FileProjectDeliveryCheckpointStore(..., read_only=True)` 精确
读取该 repository child delivery 的 checkpoint，再按其中 ID 使用 Product/Design/Plan typed getters；没有搜索
全部 Requirement JSON 正文。以下是 child projected stages 的来源链，不能与 joint Requirement 冻结源混同，更不表示替换或重新批准了 joint 源：

| 类型 | 身份与摘要 |
|---|---|
| Repository delivery | `delivery_dc5cf0aee44e5ffe0cb600557204e0d0` |
| Checkpoint | `77d71506cb8be1e217c07bcabee9c30cc67111185470e41c5306a0fc88739469` |
| Product | `product_spec_9f12797c2176d4d9a90db043`；`b0a6c738ab320571f1225242aad53963e80a77c20c8706e48c3c8cad95466fd4` |
| TechnicalDesign | `technical_design_bbe968e8fda3605a1912df8c`；`357a5f175411972bb9871c6de9dcbb44969d850a39e4d58468ed2e6065472262` |
| ExecutionPlan | `execution_plan_950185c6a217681bc2f6e0be`；`b10d114f3571d31ef14d0665f4b85e0f758e2ee3c76cb33728493b3d310da9b5` |

`product.acceptance_criteria[27]`：

> ac_011_003：Designer/Planner 明确最终源码、Schema、tests 和 docs 的精确 write_paths；Coder
> 不修改 .trellis/spec/、平台权限或安全策略。需沉淀的 Trellis 契约由具备维护权限的操作者独立
> 同步并留下可核验记录。

verification：

> 将实际 diff 与批准 allowlist 对照，检查角色权限负例和契约同步记录；自然语言需求或设计不能
> 扩大机器权限。

精确 test IDs 为 `K1-CONTRACTS-WRITE-ALLOWLIST`、`K1-CONTRACTS-AUTHORIZED-SPEC-SYNC`。

`design.acceptance_mappings[27].verification_strategy` 的相关原文：

> 同步记录契约测试验证独立维护主体、职责、URI/hash、对应版本，并拒绝缺失记录、伪造主体、
> 摘要漂移及 Coder 自行同步。独立 QA/Review 另须检查实际候选 diff、
> docs/architecture/learning-collection.md、docs/development/learning-collection-verification.md、
> docs/operations/learning-collection.md 以及维护操作者同步后的
> .trellis/spec/core/project-learning.md 和真实外置记录；fixture 只能证明验证逻辑，不能证明
> 真实规范已同步。实际记录缺失须标记未完成，不能由设计或 Coder 补造。

映射的执行命令为 `python -m pytest -q tests/learning/test_guards.py -k ac_011_003`。原设计要求
真实 WorkspacePolicy/PolicyBoundToolRegistry 拒写、目标 bytes 不变和 QA/Reviewer 不扩权；
document inspection 不能替代这些执行证据。

`plan.work_graph.packages[7].checkpoints[3]`：

> 独立维护操作者同步 .trellis/spec/core/project-learning.md，记录主体、职责、精确 URI/hash 与
> 对应版本；真实外置同步记录必须由 QA/Review 核验。同步契约 fixture 不证明实际同步，缺失或
> 不可读取时保持未完成。

上述 child Product/design 的 S2 为
`project://repository_c78e1680f621ff06c808aa9559666412444fbd7b/.trellis/spec/core/project-learning.md`，
冻结正文 SHA 为 `f128304cf7a214a9307bc41609269f4433684382954ceb12d0ad7141b45126e8`。当前
仓库规范仍写 `Collection is currently explicit, not automatically invoked at every accepted role
checkpoint.`；不能在真实实现和接线验收之前提前改成“自动采集已完成”。

**字段与版本含义：**上述冻结 Product/design/plan 未声明名为 `SpecSyncRecord` 的正式类型，
也没有要求组织规范必须和业务 candidate 位于同一个 Git commit。原文确实要求主体、职责、
精确 URI/hash 与对应版本及真实外置记录。实际维护记录应显式绑定 candidate SHA 和独立维护
spec revision，供同一 candidate 的 QA/Reviewer 核验；不能声称外部 spec bytes 原本存在于
candidate checkout，不能让“对应版本”变成无法核查的自由文本。

## 已有正式路径与边界

| 接缝 | 已有能力 | 边界 |
|---|---|---|
| `ApproveKnowledgeResolution` / `approve_resolution` | 公开 typed POST 接收 exact gap、答复、有界来源及批准引用；主体固定 `human:local-console` | 只接受未退休 Requirement 当前 `WAITING_HUMAN` 的 exact gap，不是任意资料发布器 |
| `KnowledgeResolutionSource` / `KnowledgeGapService.resolve` | `uri`、`sha256`、完整 `content`；校验正文摘要、gap/run lineage与精确批准，封存不可变记录 | URI与自称主体不证明实际维护发生，仍需独立验源 |
| `KnowledgeRunContextBuilder` | 同 Team/Project/Requirement/Task/role/snapshot 的批准答复进入新 `knowledge.resolutions` | QA答复不自动覆盖Reviewer；不改冻结snapshot或旧Context |
| `append_knowledge_context` | 完整答复、source正文与批准信息参与新Context identity；预算不足fail closed | 不热注入运行中的角色，不截断必需来源 |
| `KnowledgeHumanActionRecorder` / production `EngineeringHumanActionRecorder` | 已接线真实Task/case的 `CLARIFY_REQUIREMENTS` 和resolution URI审计 | 不批准代码、不生成角色测试/verdict；诚实影响ADR |
| Delivery role受控 `git show` | 在自己的candidate worktree读取共享Git object database中的精确维护commit、规范和维护记录 | commit必须真实可读；不扩大fetch/checkout或任意宿主路径访问权限 |
| `Evidence` / `RunEvidenceSession` | 独立角色可封存实际只读命令与测试结果并引用真实文件摘要 | 不冒用AgentRun制造维护产物，不把引用形状当来源验证 |
| Project/Team规范上传与工程恢复服务 | 各自已有有界来源或保留进度职责 | 不等于目标仓库的实际规范同步，不用修改知识选择或伪装执行恢复来供证 |

正式入口：
`POST /api/v1/admin/projects/{project_id}/requirements/{requirement_id}/knowledge-resolutions`。
`LocalConsoleAdministration.resolve_knowledge_gap` 调用 `approve_resolution`，从真实gap取得
previous_run_id，不接受调用者自填approved_by，并保存独立
`KnowledgeHumanActionEvent(APPROVE_KNOWLEDGE_RESOLUTION)`。之后真实运行自动桥接评价审计。

可信本机批准不使source自称“维护者”自动可信。独立角色仍需核对用户授予的维护职责、可信
人工批准和真实维护发布事实；Git author字符串本身不是不可伪造的身份认证。不能用新手写
receipt或测试fixture代替真实授权与发布。若采用签名，必须确有已配置信任链，不能只声称有。

## 优先采用既有路径的时序

1. Coder按原allowlist完成真实candidate；可以说明规范维护前提，不写Trellis、不编造维护
   收据。当前执行自然结束，不热改它的Context或worktree。
2. 独立QA真实知识咨询发现缺少同步事实时，由现有gap流程等待人工。只能使用真实当前gap，
   不手写gap/journal；没有gap时先核对实际咨询和路由，不承诺一定出现按钮，不改Task状态。
3. 有维护权限的独立操作者在自己的维护checkout核对candidate，实际更新组织规范并发布
   独立commit，封存真实维护记录。Coder/QA/Reviewer工作区保持隔离，不手动cherry-pick。
   维护commit须已存在于注册Repository共享Git对象库；正常发布/fetch由授权维护者执行。
4. 通过既有知识答复表单提交实际维护记录和新规范正文；source包含精确URI、有界完整content
   及正确SHA。答复和真实发布记录明确ac_011_003、维护主体/职责、candidate SHA、维护commit、
   前后正文SHA与发布引用，不能只放一个无法核查的自称记录。正式入口封存答复与人工批准。
5. 下一真实claim的同角色Run自动取得完整新knowledge.resolutions section，按新Context
   identity与预算校验封存。保留原S2的URI/hash与冻结snapshot，不覆盖source_revision、
   机器policy、旧manifest或知识选择。外部维护版本与业务candidate必须分别声明。
6. QA独立核对candidate diff、源码/Schema/tests/docs、维护身份/授权、真实维护记录和新规范。
   用受控 `git show <maintenance-sha>:<spec-path>` 和真实记录路径读取并核对答复正文/hash。
   按冻结要求独立跑增量测试，在自己的报告引用证据。维护者或Manager不写QA/verdict。
7. Reviewer若同样缺事实，需其真实咨询产生的独立current gap与正式答复；QA resolution不会
   自动传播给Reviewer。可以引用同一真实维护发布，但gap/批准/Context/独立验证都有真实lineage。

上述路径继续同一Requirement，无需重批Product/Design/Plan。candidate因正常反馈改变时，
独立角色须核对维护记录与新candidate的绑定；现有resolution不包含自动拒绝candidate漂移
的专用结构化字段，不能默认为旧答复自动适用。实际是否可完成需由真实gap和独立结果证明。

## 既有路径被实证阻断后的窄限制

真实QA/Reviewer未产生gap，或下一Run不再匹配原Task/role/snapshot时，现有入口不能当作
主动外部资料发布器。记录实际拒绝与阻断位置后，再评估复用知识发布、必需Context和审计的
候选绑定入口。**本轮不开发服务，不把专名类型缺失直接认定为必须新功能。**

专门入口若后续确有必要，其最低契约应验证可信独立维护职责、精确scope、candidate与维护
commit、固定规范路径、前后SHA、有界真实正文和不可变审计；主体不得取上传JSON自称角色，
不可读/漂移须拒绝。它不能成为第二套恢复系统、任意路径读取器或角色扩权。当前K1优先由
既有正式来源和独立受控验证完成这些检查。

## 产品用户交互

用户需要直接看到“组织规范待同步”“处理方：工程维护者”“维护完成后继续测试与评审”。
知识答复处说明需要哪些真实材料，提交结果就近呈现；工程身份与摘要放工程参考，普通产品
用户不用理解lease、补丁hash或角色worktree。

先复用当前真实知识答复入口，不宣称已有“登记规范同步”按钮；无current gap时不能让用户
寻找不存在的入口。若实际UI把工程维护操作交给无权产品用户，或未说明责任方与下一步，
应作为有界交互缺陷修复，不能只让用户重复“调查”或静默隐藏失败。

## 增量核验、存量与回滚

- 真实来源：精确维护commit、正文/SHA/发布、独立维护职责和candidate；fixture只证明契约。
- 正式答复：真实当前gap、可信精确批准、完整有界source；旧gap或不同Task/role/snapshot
  不当可用来源，不能主动造gap或补人类verdict。
- Context/audit：下一真实同角色Run收到新section，原snapshot/manifest/native规则bytes不变；
  预算不足fail closed，人工干预保留，运行中的角色不受热修改。
- 独立验收：真实diff、规范来源与权限负例均由QA/Reviewer分别核验；缺事实保持未完成。
- 存量：沿现有checkpoint保留全部进度与历史，使用原需求正式gap/resolution/继续路径；
  不改SQL、不重建需求、不绕过范围与执行批准。

本次仅修改本Markdown，没有生产POST、审批、发布或数据库mutation，无需迁移或服务重启。
撤回本文即可回滚。后续操作由根agent按用户授权监管；本文不是ac_011_003已通过的证据。
