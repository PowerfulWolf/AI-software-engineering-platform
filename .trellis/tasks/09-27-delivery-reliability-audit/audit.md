# 全阶段审查矩阵与证据

本轮沿下列 14 个阶段的公共入口、权威事实和恢复边界审查，并复查相关测试；不是全仓每行穷举，
也不声称不存在未知 bug。测试命令/数字和存量恢复门槛见 verification.md；MySQL 已分批收齐全部 95 项，
不是最后单次全库全绿，失败与补测记录均保留。

| 阶段 | 权威事实 / 职责 | 审查与测试入口 | 当前状态 |
|---|---|---|---|
| 创建/注册/准备 | Project/Repository/Preparation；Manager 校验目录与规则 | repository_workspace、manager/preparation；tests/e2e/test_project_revision_preparation.py | 已审；全部目录 prepare 后才调用模型，native baseline 冻结；本轮无新增缺陷 |
| 知识导入/选择/冻结 | 原文件、manifest、selection、prepared sources | knowledge/documents/index/index_store；tests/knowledge/test_documents.py、test_selection.py、test_index.py | 已审；显式选择、不可变来源、索引 claim/替换锁；D3 修复检索投影的 scope 漏失 |
| Product/人工批准 | 精确 ProductSpec/Approval，Product 不自批 | product/service；tests/product/test_service.py、test_context.py | 已审并修 D4；receipt 前重读事实，READY/TIMEOUT 并发输入回归通过 |
| Design | exact 产品批准、设计覆盖和阻塞声明 | design/service、multi_directory/service；tests/design、tests/manager/test_joint_designer_feedback.py | 已审；调用前后复核、覆盖校验和 receipt 重放；本轮无新增缺陷 |
| Planning | ExecutionPlan、覆盖/预算/能力；preview 不分配 | planning/service/preview；tests/planning/test_complex_planning.py、test_trusted_projection.py | 已审；current input、materialization、CAS、SIMPLE 确定性路径；本轮无新增缺陷 |
| 队列/派发 | WorkItem、Assignment、Lease、ModelSelection | manager/dispatch、work_queue/worker/dispatcher；tests/work_queue | 已审；真实 claim、心跳、事务内 owner fence、等待释放和恢复；MySQL 全部用例分批通过 |
| Agent 上下文/检索 | role/run/task/candidate、manifest、frozen snapshot、预算 | knowledge/runtime/context/skills/agents、context/builder；tests/context、tests/knowledge | 已审并修 D1–D3；不可截断 required 事实，标题和正文同一可见性规则 |
| Coder/候选封装 | exact policy/worktree/diff、候选提交与 implementation | agents、git、orchestration/runner/retry；tests/agents、tests/git、tests/orchestration | 已审；身份、supersedes、artifact 写前 fence；Coder 延续不丢工作目录 |
| QA | 同候选独立报告、真实执行与 NOT_TESTED | knowledge/delivery、role_workspace、manager/production_delivery；tests/manager/test_verifier_worktrees.py | 已审并修 D6；多候选/重启/dirty 真实 Git 通过，新增生产 Host/队列回归到 DONE |
| Reviewer | 独立身份、同候选、只读、完整 evidence | 同上、workforce/runtime；tests/workforce、tests/runtime | 已审并修 D6；不再复用旧候选 adapter，不自批不写业务代码 |
| 等待/环境/修复/重启 | Manager 协调；Task checkpoint 与队列状态分离 | recovery、multi_directory、manager/verification_coordination；tests/recovery/test_prerequisite_repair_mysql.py | 已审并修 D1/D2；8 个原生规则/legacy/新 Host Git+MySQL 组合通过，无重复 Coder |
| 联合回接/集成/交付 | child 候选集、integration evidence、handoff，无自动 merge | multi_directory/service、evaluation/handoff；tests/e2e/test_joint_delivery.py、tests/evaluation/test_handoff.py | 已审；依赖/候选集/同候选完整 artifact 链；MySQL 全部用例分批通过 |
| 知识沉淀/发布/复用 | observation/proposal/decision/publish 分离，未来需求选择 | learning.collect/decide/_authorize/_publish；tests/specs/test_project_observations.py | 已审；幂等收集、精确独立批准、发布选择锁、未来快照复用回归通过；自动收集是未完成能力 |
| Console/可观测性 | durable 状态、安全错误、知识页面、操作与验收分离 | web_console/core/manager、team_view；tests/web_console、tests/team_view | 已审；JS 49、真实浏览器 fixture 38 通过；恢复链未做真实业务 UI 验收 |

## 各阶段失败归属与恢复点

- 准备/知识：目录、来源摘要或编译冲突停在准备/知识等待；Manager 提出数据或规范协调，不启动无来源模型。
- Product：人类回复改变 checkpoint 时拒绝旧 run；从最新对话重启，不能复用旧 spec 批准。
- Design/Planning：receipt 是崩溃重放边界；模型失败有界重试，缺口回 Manager，preview 无分配副作用。
- Dispatch/Queue：权威 workforce snapshot 与事务内 lease owner 是 fence；失租旧 worker 禁止发布，保留 checkpoint。
- Context：required source 缺失/预算不足不得静默删规则；知识等待保持 Task 交付进度，释放 WorkItem lease。
- Coder：dirty progress 是非候选 checkpoint；恢复精确校验后延续。源码前提修复须批准新计划，不能扩大旧权限。
- QA/Reviewer：FAIL/REJECT 回 Coder；未执行/环境前提由 Manager 协调。PASS/APPROVE 只认相同候选和独立身份。
- 联合/交付：父需求按全部子候选和集成证据收敛；Handoff 读取 terminal event 与完整 artifact 链，不自动合并。
- 学习：观察不是事实批准；学习批准不是能力授权，发布失败不允许伪造交付通过。
- Console：Operation SUCCEEDED 只证明命令完成；交付 BLOCKED/DONE 单独展示；异常用安全诊断定位而非供应商原文。

## 确认缺陷

- D1（P1，已修）：首次修复与恢复来源分叉；真实 fixture 原先 Coder 得到 0/3 份规范。
  统一 `approved_joint_context_sources`，首次、派发和重启同源，但当前 repair preparation 不偷换。
- D2（P1，已修）：legacy QA/Reviewer snapshot 空、恢复补正文后永久阻塞。新增
  `knowledge/legacy_scope.py`，只允许原 baseline 已封存的相同 URI/hash 原生来源补全角色上下文，
  检索仍用原快照。旧文档变化、新选择、未知来源拒绝；不改 gap/resolution/历史摘要。
- D3（P1，已修）：source 的角色限制在 native/Team/Project 投影和 nested 包装时丢失，foreign
  repository spec 空交集变 wildcard，意图模型可见禁读标题。统一交集和可见文档投影；负例已先失败再通过。
- D4（P1，已修）：Product 模型返回后未复核 checkpoint，人类同期回复后仍写旧成功/失败 receipt。
  与 Designer/Planner 一致，在任何 receipt/effect 写前重读并拒绝 stale。
- D5（P2，已修）：全库 strict mypy 发现 4 个既有测试文件共 5 处类型错误；使用类型收窄/Enum/非空断言修正，
  不加 suppress，不将这些测试维护计为产品功能修复。
- D6（P1，已修）：同进程验收第二候选仍用第一候选工作区，重启则 HEAD drift 卡住。
  真实 Git 两条路径先红；QA/Reviewer 改按角色/attempt 绑定目录和 adapter，每次复核，按需独立打开。
  8 个 Git 正反例通过；生产 Host/队列 QA 驳回再交付回归已到 DONE，包含不同真实 Git 候选与租约释放。
  全量回归同时发现本轮新增 Task guard 的兼容回归：独立候选验收 request 绑定 source Task，
  checkout/lease 才绑定 execution Task。已改为模式化精确校验，补 source 接受/execution 冒用拒绝
  两个用例；不是删除身份检查。prerequisite/standalone 恢复和最后补跑均通过，D6 关闭。
- D7（P1，已修）：native 恢复仍用 `attempts == max_attempts` 判断 progress 预算耗尽，
  新冻结策略的工作额度为 3、执行身份上限为 18，导致真正耗尽的 progress 无法恢复。
  复用 `Task.work_budget_exhausted`，保留原 terminal/run/sequence/approval 校验。
  另一个失败是旧 INVALID_OUTPUT 测试假定自动调用 3 次；现行非临时错误立即停止的契约不变，
  改测一次失败后通过正常精确恢复提案，未增加无意义重试。相关 native + verifier-retry 共 11 项通过。

## 本轮之前保留的真实只读证据

- Operation `operation_b461eda39c3dff01cccff4a099c27644`：操作 SUCCEEDED，但交付 BLOCKED，
  `INVARIANT_VIOLATION / LEGACY_KNOWLEDGE_SCOPE_CHANGED`。
- 旧 Context `ctx_ef638d393e314c405608c0ac589e54bfe748a9734d92b0524a8367f4e80d9254`。
- 旧 snapshot `a89df45c47adb2fbb9b04a3b400ddb36693d0fec887e627d609088b03b059d36`，documents=[]。
- 恢复来源按旧 scope 重算 snapshot `a126bc7c6166680cc15f71650df957de907381b9b415415d37474f54074671bf`，
  多出 README.md、.trellis/spec/backend/index.md、.trellis/spec/backend/codex-quota-monitor-contract.md。
- 本任务不改这些历史事实，不将旧任务的测试数量列为本轮审查通过证据。

## 架构结论与仍未完成的能力

主边界保留：Knowledge Plane、Manager 协调、typed Skill 执行、独立 Coder/QA/Reviewer 是正确方向。
本轮局部调整消除的是重复来源组装、权限投影分叉、外部调用窗口和混淆的工作区生命周期，
不是通过删除检查或重写状态机“提速”。

1. 自动学习不是已完成：当前显式 collect 可幂等收集带证据的 delivery observations；上游角色自动提案、
   Manager 前提处理结果自动沉淀及每 checkpoint 自动收集仍属 09-25-team-evolution-audit 的开放项。
   不应把收集副作用塞进 GET projection，也不能让学习失败改写交付 verdict。
2. 通用能力扩展不是把文档发布成 Skill 即激活。新的执行器能力仍需版本化 policy、精确批准和独立拒绝/通过测试；
   现有 Swift/UI 只是适配案例，并非所有项目的通用环境前提。
3. 当前同步 Supervisor 有界推进串行 Task，组织级队列具备 claim/fence；独立进程 fleet 不在 v0.1 范围，
   没有理由为本轮 bug 引入新 MQ 或 DAG。
4. 存量 scope 若曾错误放宽，新权限投影会产生不同摘要并 fail closed；不能静默重写历史快照或自动沿用旧批准。
   legacy 兼容仅覆盖已证明的漏原生正文，不是任意历史数据迁移器。
5. 本轮不部署、不调用真实模型、不运行受控桌面验收；fixture DONE 不能代替原业务需求 QA/Review。
6. MySQL 各轮失败均已定位并修复/补测，全部 95 项分批收齐；离线全库 1909、前端 49 + 38 通过。
   7 项真实环境 opt-in 未执行，2 个依赖弃用 warning 保留；原需求须受控加载修复后由 ASE 真正验收。

## Bug Analysis：为什么会不断修一处、下一步又卡住

### 1. Root Cause Category

B/C/D/E：跨层契约、变更传播、组合覆盖不足和隐式假设共同作用。
恢复路径复制了上下文组装；知识 wrappers 默认为“无角色限制”；Product 假定模型调用期间输入不变；
worktree 假定一个 dispatch 只有一个 candidate；native reader 假定工作预算等于执行序号上限。
这些均是平台代码/测试问题，不是 Xcode、桌面锁屏或业务项目的责任。

### 2. Why Fixes Failed

此前新增路径与正常路径分别测试，没有把历史快照、原生规范、多个恢复代次和新 Host 组合。
固定 greeting 的 happy-path fixture 无法暴露第二候选 worktree 问题；旧 retry 测试未随预算语义更新。
只看到“新建数据跑通”或“单模块测试绿”不足以证明历史需求能继续。
本轮也出现“统一 guard 忽略验收 source/execution 双身份”的回归，被完整 MySQL 恢复测试拦住；
这说明独立验收不是普通 dispatch 的缩小版本，必须把两种身份协议明确写入 spec 和同层正反测试。
最后全量还拦住共享 fixture 的过度修改：不能按 execution attempt 推断候选正文。
多候选数据现仅注入到新增场景，原共享样例默认恢复不变；此项只修测试，未改生产实现。

### 3. Prevention Mechanisms

| 优先级 | 机制 | 本轮动作 / 状态 |
| --- | --- | --- |
| P1 | 架构同源 | 共用批准来源纯投影；消除首次/恢复分叉，已落地 |
| P1 | 不扩大权限 | 角色/repository 交集与统一可见性，含元数据拒绝测试，已落地 |
| P1 | 身份明确 | verifier 独立 attempt 生命周期；work budget 复用领域属性，已落地 |
| P1 | 外部窗口复核 | Product receipt 前重读 checkpoint，含成功/失败旧结果拒绝，已落地 |
| P1 | 真实组合测试 | Git/MySQL、多 candidate、历史 native、重启、反例，已落地 |
| P2 | 规范与记录 | 精确 spec、14 阶段矩阵、恢复门槛、遗留能力边界，已落地 |

### 4. Systematic Expansion

核对同类 Product/Designer/Planner post-call guard；QA 与 Reviewer 两角色及单独验收模式；
Team/Project/native/spec sources 和父包装；全库搜索其余 `attempts/max_attempts` 比较，
余下仅 legacy runner 和身份上限保护，语义正确。未来审查必须同时问“这个身份在哪条路径创建、恢复、清理”。

### 5. Knowledge Capture

已同步 active-knowledge、continuation-knowledge-wait、python-runtime、execution-retry-policy、
verifier-worktree-lifecycle 和 docs/git-worktree。仓库没有模板镜像目录，不虚造同步对象。
按用户要求保留当前未提交改动；不自动 commit/归档，不将前期混杂修改归入本轮。
