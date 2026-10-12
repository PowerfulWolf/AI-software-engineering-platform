# 同代码版本容量恢复的前端契约

本文件记录 `task/same-source-capacity` 的前端实现范围。它与后端的新用途和可信事实收集同时交付，
不混入仅修复旧知识 claim 的紧急发布。前端不执行生产审批、服务重启、恢复或模型调用。

## 目标与允许路径

输入超限发生在本轮主 Coder 调用开始前时，用户应在原需求看到明确的原因、平台处理方和可用决定。
恢复保持原需求、Task、分支、工作区、代码版本和完整开发进度，不要求产品用户输入 commit、
判断进程停止或理解 lease。准备、精确批准保持暂停、另行继续是三个有审计记录的动作。

本子任务只拥有 `team_view/app.js`、新增的定向前端测试、本文件、`frontend-verification.md`
以及 `docs/user/team-console.md`。后端实现、Schema、核心规范和 task.json 由后端子任务负责。

## 已确认的 v8 线协议

| 动作 | 页面提交与核验 |
| --- | --- |
| PROPOSE_EXECUTION_BASELINE | `purpose=context_capacity_resume`、`input_mode=preserve_draft`；完整 Project/Requirement/checkpoint/Task intent/revision/WorkItem/current source 绑定；**省略 target_base_ref**，由服务根据可信事实选当前执行基线 |
| EXECUTE_EXECUTION_BASELINE | exact plan digest、当前 Project/Requirement/checkpoint/Task、说明 reference、`continuation_mode=pause`；不提交停止、旧执行隔离、提供方修复或项目规范变更确认 |
| RESUME_EXECUTION_BASELINE | 复用独立继续契约，绑定当前完整暂停、binding digest 和 disposition digest；审批不会隐式发起此动作 |

页面须同时看到 `operation_contract_version >= 8` 和既有三项能力才允许新用途的准备与批准。
v7 的代码更新路径继续使用既有 `source_rebind` 语义。wire 中的用途由 plan/binding 明确声明；
不能把保持原版本的操作写成“更新代码与项目规范”。`binding.context_capacity_receipt_sha256`
的持久化及完整关系校验属于后端，前端不自造或提交容量 receipt、停止证明或预算事实。

## 页面状态与动作

| 当前可信状态 | 直接展示 | 允许的主要动作 |
| --- | --- | --- |
| 当前 Coder CONTEXT_CAPACITY 且绑定完整 | 输入超过模型容量、主开发调用未开始、平台需先修复输入准备；原进度保留 | 准备保留进度的恢复方案 |
| 当前精确方案准备成功 | 原分支和代码版本保持、完整合法进度已封存、批准后仍暂停 | 批准保留进度，保持暂停；重新准备为次要动作 |
| 准备 FAILED / INTERRUPTED | 本次失败原因与处理后重新准备提示；不宣称已有可审批方案 | 重新准备保留进度的恢复方案 |
| 当前 Operation QUEUED / RUNNING | 真实排队或执行状态、当前操作与平台进展 | 等待当前结果，无并行重复准备或审批 |
| EXECUTION_BASELINE_PAUSED | 进度已保留、未启动新 Coder | 既有独立“继续原需求” |
| Task/source/checkpoint/receipt/disposition 不完整或不匹配 | 记录不完整，平台恢复记录读取后再核对 | 不提供容量准备或批准 |
| v8 能力缺失或交付控制不可用 | 原因与更新服务/恢复读取的下一步 | 不提交新用途 |

当前卡片位于“当前进展”，操作直接可见。原始方案、receipt 与代码摘要保留在折叠的核对信息中；
需要主动更新仓库代码时可展开独立可选工程操作，不把代码更新混作容量恢复的必要步骤。

## 绑定与旧控件失效

复用 `engineeringBaselineFacts` 的 Task/revision/intent/source 绑定后，容量路径额外要求：
当前工程职责的 Coder 等待、事实 role=coder、Project/Requirement 精确对应、64 位 disposition 摘要，
以及恰好一条 `context-capacity://<sha256>` 引用。方案必须是 preserve_draft、无冲突、
目标等于先前执行基线、准备 source 等于当前 source、receipt 精确一致，且没有原生规范、
隔离、完成输出或提供方失败的混合证明。

点击时重新读取当前已验证快照并重验上述事实、控制能力和当前 Operation；Project 切换、
租约有效、角色阶段变化、旧精确 plan 或 receipt 均拒绝提交。后端继续执行自己的完整可信验证，
前端门禁不代替服务授权。通过真实控件创建的回调也不能因已脱离 DOM 而继续审批。

卡片、标题、说明、核对信息、失败提示和动作使用 keyed viewBlock/viewGroup。无关 Task 心跳
不替换原 DOM，因此焦点、文本选区和展开状态保留；bound/plan/能力变化会替换相应控件。
签名只在内存保存，不写成 DOM 属性。未证实的缺记录状态不得宣称本轮已核验为 no-start。

## 操作记录与兼容

操作用途优先读取 exact intent、已验证 summary purpose、完整 plan/binding。
尚未完成的 EXECUTE 可根据同 Project/Requirement/Task 和 exact plan digest 的原 PROPOSE 显示用途。
带容量用途的 RESUME 仍显示既有继续动作，不能误写为再次准备方案。

后端摘要必须从成功的 `execution_baseline_binding.purpose` 补充 `baseline_purpose`，
否则历史 EXECUTE 的摘要可能误称更新代码；该跨层补点已交后端实现者。

## 存量数据处置与回滚

前端不改已有 Requirement、Task、Operation、审批或角色队列事实。旧容量等待须由后端
对现存可信 receipt 和完整现场验证后，通过新用途生成追加的计划/授权/binding；不得重写旧失败。
用户刷新新服务提供的页面后按“准备 → 批准保持暂停 → 单独继续”操作原需求。
缺事实或旧版本只显示不可用原因，不把缺失记录补成成功。

回滚时撤回该前端变更及配套 v8 功能，刷新页面；保留新旧审计记录，不触发额外操作，
不自动重新提交或恢复执行。后端需保持新用途记录可读，不能仅把新持久化用途降级为 source_rebind。
