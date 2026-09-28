# ASE 交付全过程复盘：平台缺陷、修复与剩余工作

核对日期：2026-09-28。范围仅限 ASE 平台，重点覆盖 09-25 至 09-28 本次需求交付、全阶段审查和项目切换修复。
这不是“全平台已无 bug”的声明，也不把历史测试数字累计为当前版本一次全量测试。

## 结论

问题主要不在 Swift，也不是 multi-agent 本身不可行，而在 **正常路径、恢复路径、历史数据和真实执行器之间的契约没有统一接通**。
单个类或模块测试通过，经常被误当作生产组合链路可用；每修通一个入口，下一层缺口才暴露。
环境问题本身不算平台 bug，但平台不能识别、协调、保存进度并恢复，属于平台责任。

目前已有一次真实 ASE 闭环：原联合需求 DONE，独立 QA 四项 PASS、Reviewer APPROVE。
候选 `9ac7c9ee830df548571db55ec5cf809e613467ba`；父 checkpoint
`f22850f71024c2abad8e10c0138dac11c42c1cfd8c416067bab35fdc0c0d88df`；最后 Operation
`operation_631cb34a7404c76156e907dd37504d32`。这些是平台权威事实，不是本次合并安装产生的新 verdict。
历史 BLOCKED/中断记录保留，不能因为它们仍在列表中就认为最终交付没有完成。

主要平台修复在 `321f15e`；项目切换修复在 `4d1e799`，发布 tag `v0.1.2` 指向后者。
后续文档提交不移动这个 tag。

## 已解决的平台问题

下表按根因/子系统归并，不把同一个问题的多次报错重复计数。编号只服务本复盘，证据入口见后文。

### A. 审批、Manager、队列和恢复

| 编号 | 平台问题与影响 | 修复方案 | 证据 |
|---|---|---|---|
| A1 | 刚生成审批就追加父 checkpoint，使 exact plan 自行过期；用户反复批准但不执行 | 无真实子变化的 pending gate 不推进父 journal；先同步真实变化再提案，保留真实漂移拒绝 | E1 |
| A2 | 新能力已接入，但旧未启动计划只验证自身 digest，入场时才因当前权限不同失败 | 对未启动计划比较候选当前能力并重提；已入场历史不改；Swift 参数别名归一防重复绕过 | E1 |
| A3 | Manager 恢复类存在却未接生产路径；环境不满足时反复消耗 QA | 从封存结果形成 durable incident；Manager 提精确方案、人审批、受控执行器产 receipt，再独立验收 | E2 |
| A4 | 执行器在模型之前失败，绕过 Manager；重启后仍无法协调 | 首次失败和 admitted-without-completion 恢复共用协调入口；Manager 输入包含精确失败 receipt 和有界诊断 | E3 |
| A5 | 源码前提修复只接受 QA 报告，执行器先失败时无路由回 Coder | 新增独立的 executor-prerequisite 证据类型，精确修复提案/授权后由 ASE Coder 执行；不伪造 QA | E3 |
| A6 | 等待知识时释放 lease，与 heartbeat 续租竞争；本地执行仍可能继续 | 串行化 renew/wait/finish；事务成功后发布等待态；失去所有权后禁止继续执行 | E3 |
| A7 | 恢复保留了 dirty edits，却丢失批准的“修什么”目标 | 从失败 manifest 恢复 required、未截断、精确匹配的 prerequisite context，校验原 Task/Coder/授权 | E4 |
| A8 | QA 知识等待在联合/修复入口丢失，出现 GAP_NOT_FOUND 或父子绑定错误 | 统一 approved parent context；typed checkpoint+gap 回接；接纳后重开 successor runtime | E5/E7 |
| A9 | native 恢复把执行序号上限当作工作预算，真正工作额度耗尽却不能恢复 | 复用领域 `work_budget_exhausted`，不削弱原 terminal、attempt、approval 校验 | E6 |
| A10 | Manager 按模型填写的报告时间选择“最新 QA”，取到了旧结论 | 使用 durable Task event 和 sealed completion 顺序；不按模型 `created_at` 排序 | E7 |
| A11 | 独立 QA 已 PASS、Reviewer 中断后只能整组重跑 | 新增精确 retained-QA proof；新批准只跑 Reviewer，覆盖入场前/后中断及重复中断；新否定结论阻止旧 PASS 复用 | E8 |

### B. 模型调用、上下文与历史兼容

| 编号 | 平台问题与影响 | 修复方案 | 证据 |
|---|---|---|---|
| B1 | Responses strict Schema 不完整；网关不保存 response ID，工具多轮失败 | 统一 strict schema；stateless 完整 output/receipt 回传，保留 call ID/reasoning，不重放工具副作用 | E1 |
| B2 | 错误被压成 MANAGER_FAILURE 或 `value_error`，安全但无法定位 | 脱敏后限长的 provider 诊断；固定语义 validation-rule；typed Console 错误，不放松报告校验 | E1/E7 |
| B3 | owned CLI 大 prompt 在 `communicate` 超时轮询后停止写 stdin，子进程永远等 EOF | 私有、立即 unlink 的临时输入描述符；继续保留 lease 检查、超时和进程组回收；慢读大输入实测回归 | E7 |
| B4 | 首次/恢复上下文组装分叉；旧空知识快照补原生正文后永久 scope drift | 共用来源投影；只允许原基线已封存、同 URI/hash 原生来源的狭窄兼容；不修改旧 snapshot | E5/E6 |
| B5 | successor 已批准新基线，却读到 parent 的旧规范正文；历史 formatter 字节变化也使摘要不匹配 | 按已批准 successor profile 从精确 Git revision 绑定正文；只识别已知旧 formatter 且重验完整原摘要 | E5/E7 |
| B6 | 角色/repository 范围在多层包装丢失；空交集变 wildcard，连禁读标题也被送给模型 | 统一范围交集及可见性；标题、元数据、正文同样校验；跨角色/跨仓负例覆盖 | E6 |
| B7 | Product 模型返回期间人类已回复，旧成功/失败 receipt 仍可写入 | 与 Design/Planning 一致，在外部调用后、任何 effect 前重读 checkpoint 并拒绝 stale | E6 |
| B8 | 独立 Reviewer 入口遗漏生产上下文预算，退回 12k，正常 QA 证据放不下 | 共享生产 64k 预算及保留额度；required 不截断；真实超限 fail closed，释放预留，显示明确诊断 | E7 |
| B9 | 新可选字段/Schema 生成改变历史 canonical bytes，或覆盖手写跨字段约束 | absent 新字段保持旧 hash；不同旧格式分别兼容；生成器保留语义约束，历史计划/receipt 只读重验 | E3/E7 |

### C. 独立验证与执行器边界

| 编号 | 平台问题与影响 | 修复方案 | 证据 |
|---|---|---|---|
| C1 | 普通 subprocess 的成功被误当成真实 CLI 沙箱可用；缓存、内层沙箱、构建后端契约不完整 | 版本化 Swift executor、独立缓存、批准的内层沙箱例外及 native backend；保留外层源码只读/无网络并实测拒绝 | E2 |
| C2 | CLI verifier 原生命令/写工具不受 Responses typed tool 同样约束 | QA/Reviewer 使用 no-command、只读 CLI；测试由 exact-plan executor 提供真实 receipt；实测工具目录与拒绝写入 | E3 |
| C3 | 同 dispatch 验收第二候选复用旧 worktree/adapter；重启后 HEAD drift；source/execution Task 混淆 | 按 role/attempt/candidate 管理并每次复核；明确双身份契约，fresh Host/不同候选/dirty/冒用负例回归 | E6 |
| C4 | UI 临时目录隔离只覆盖一类路径，另一 canonical/alias temp 可被读 | 同时拒绝宿主 temp 原路径与别名，只有私有 scratch 可用；真实 read/write/network/exec 拒绝测试 | E3 |
| C5 | 桌面锁定被 Manager 误解为队列互斥锁；解锁后旧建议缓存仍不失效 | typed desktop prerequisite、只读 readiness probe、权威人工解锁指引；READY 改变建议输入，不重放旧执行批准 | E4/E7 |
| C6 | 驱动仅识别少数错误，把 TARGET_UNAVAILABLE 等录为 COMPLETED | 所有非空 UI error 转为 typed block；旧 receipt 按有效状态解释而不改 bytes；有界 AX 控件事实交 Manager | E7 |
| C7 | 只有 AX 文本不能证明图表渲染；缺少受控截图、滚动和跨次证据传递 | 补有界 child-window PNG、批准的滚动/AXLink；模型真正收到图像；互补证据只接受 exact-approved 同候选 predecessor，最多旧6+新6 | E7 |
| C8 | CLI ScreenCaptureKit 未初始化 AppKit 崩溃；无效捕获结果异常逃出 receipt | MainActor 初始化 NSApplication；捕获/结果配对校验；驱动边界转 NativeUiUnavailable，保留失败 receipt | E7 |

C7 是交付中确认并补齐的能力缺口，不是业务 App 缺陷。真实屏幕被锁不是 C5 的 bug，**误诊和恢复缓存**才是。

### D. 知识沉淀、可观测性和前端

| 编号 | 平台问题与影响 | 修复方案 | 证据 |
|---|---|---|---|
| D1 | 学习只收失败 finding，正常发现无法沉淀；resolution 的 Python/Schema/UI 不一致 | Coder/QA/Reviewer 支持有 evidence 的 observations；显式 collect→待审批→精确发布→后续检索；Schema/UI 显示来源与适用范围 | E9 |
| D2 | 知识发布 selection 读改写竞争，可能覆盖用户同时取消的选择 | 同 scope mutation lock 覆盖整个发布/合并 selection；并发取消选择回归 | E9 |
| D3 | 历史 verification 共享图被当树递归重验，读取随恢复次数爆炸 | 单次同步读取上下文内复用“已完整验证”节点；每个新请求重新验字节；循环/深度/数量上限、线程隔离 | E7 |
| D4 | readiness、配置应用反馈与 Team 读取耦合，旧成功反馈/重启提示误导，断连时控件状态错误 | 分离 Console/Operations/Team/settings 事实；过期提示不重建草稿；交付控件原地挂起并在提交前复核 | E10 |
| D5 | 自动刷新忙时直接丢弃 Project 切换，接口越慢越像“点了没效果” | latest-intent 单刷新流水线，立即提示目标、旧响应拒绝、失败保留目标重试；切换中禁止旧页面交付命令 | E10 |
| D6 | Knowledge await 期间内部项目先变、页面还显示旧项目 | 接受快照时同时渲染新项目和加载态；更晚选择/失败仍保持已接受项目内容与身份一致 | E10 |

另有测试工程修复：strict typing 旧错误、fixture 意外探测真实工具链、把 execution attempt 当候选内容、旧 QA fixture 缺真实测试 evidence。
这些修复保留了生产门禁，没有通过降低测试断言或自动接受无证据 PASS“过关”。

## 为什么持续出现“修完一个又堵一个”

1. **组合路径缺测试**：正常派发、独立验收、repair、continuation、legacy、restart 各自实现相近逻辑，却没有同一套可执行契约。
2. **测试与真实执行不等价**：普通 shell 不等于隔离执行；小 prompt 不等于慢 stdin；短历史不等于多次恢复图；AX 文本不等于像素。
3. **阶段成功被误读**：HTTP 200、Operation SUCCEEDED、命令 exit 0、QA PASS、Reviewer APPROVE、Requirement DONE 是不同事实。
4. **恢复身份不完整**：candidate、source/execution Task、attempt、父/子 checkpoint、approval、scope、当前环境观察必须一起验证。
5. **诊断晚于推进**：泛化错误、缺真实执行阶段和陈旧建议让人反复猜；Manager 需要当前、typed、可执行的协调输入。

纠正方向不是删除门禁，而是共用 composition seam、精确证据、真实边界回归，并将教训写成可执行 spec。

## 环境与平台能力的边界

- Xcode/XCTest 缺失、桌面锁定、MySQL 停止、上游 504 属于环境/外部前提，不计入平台代码缺陷。
- ASE 必须负责检测、分类、把证据交 Manager、提出有权限边界的方案、等待人处理、重新探测并恢复。
- Swift 是一个目标项目的技术栈；通用平台不应要求所有项目安装 Swift/Xcode。
- 一次环境修复不能自动变成全项目 Spec；一次知识发布不能自动获得安装、shell、网络或 UI 权限。

## 还未完成的 ASE 工作（按建议顺序）

“已具备”与“待补齐”分开列出；下面是后续路线，不是本次已实施承诺。用户已确定：交付完成后先自动知识闭环，再通用能力扩展。

| 优先级/顺序 | 事项 | 当前事实与待补齐 | 最小验收标准 |
|---|---|---|---|
| P1 / 1 | **自动知识收集闭环** | 现有收集由显式 POST 触发；没有每个 accepted checkpoint 的可靠自动触发、增量游标及失败补偿 | sealed report 被接纳后自动产生待审提案；重启/重复事件不重复；失败不改交付 verdict；A 需求经验经批准后被 B 检索并引用 |
| P1 / 1a | **上游与 Manager 的学习生产者** | observations 已覆盖 Coder/QA/Reviewer；Product/Designer/Planner 和 Manager 前提处理结果未形成统一采集协议 | 每类提案都有 source revision、owner、适用条件和证据；成功/失败/人工澄清均可提案；临时环境事实不变全局规范 |
| P1 / 1b | **知识效果评估与维护** | 已有冻结快照、角色检索、引用及部分评测；生产级收益闭环尚不足 | 能查“哪条知识被哪次角色用、是否减少重问/返工”；冲突/失效可退休，不追改旧快照；前端能看待收集/失败/待审/发布/引用 |
| P1 / 并行可靠性 | **Manager 全阶段前提协调** | 候选验证的 incident→方案→审批→执行→恢复已接通；还不是 Product/Design/Plan/Coder 等全阶段通用能力 | 各阶段环境/数据/权限/能力缺口均有 owner、解除条件、当前 probe、恢复点；等待释放 lease，不消耗明知不可执行的模型重试 |
| P1 / 并行质量 | **生产组合回归矩阵常态化** | 本次已补大量 Git/MySQL/GUI/CLI 组合测试，但 opt-in 套件需要独立环境，不能假定每次全跑 | CI 分层运行；至少固定覆盖旧记录升级、fresh Host、多候选、角色中断、等待/续租、不同模型路由和大上下文；报告跳过与耗时 |
| P1 / 2 | **受治理的通用能力扩展** | `SKILL` 发布目前仅生成设计提案；Swift/UI 是受控适配，不是通用自扩展系统 | 提案→隔离实现/测试→独立评审→人工/策略批准→版本化注册→按角色授权→运行反馈/回滚；禁止 Agent 自授权限 |
| P2 | **其余 CLI 角色执行权限审计** | 独立 QA/Reviewer 已 no-command；其他角色与 typed-tool 入口的一致性需单独核查 | 逐角色列实际工具目录与允许路径/命令；包含越权写、网络、环境变量和命令别名负例；不是只看 prompt |
| P2 | **刷新/投影性能预算** | 历史图指数重验已修；本次 codex 单 GET 仍曾约 7.4–8.0s，导航现在不丢但仍可能慢 | 分段指标、请求耗时预算、增长历史基准；优化不引入跨请求过期信任缓存，不把 GET 变写操作 |
| P2 | **模型路由健康与诊断** | 已有授权 fallback、typed 错误与分路由记录；真实多次 504 仍拉长交付 | 对持续异常路由给 Manager 可执行建议，评估受控冷却/健康探测；不静默更换授权目的地，不无限重试 |
| P2 | **依赖弃用和历史工程台账核对** | Starlette/httpx、AnyIO 两个 warning 保留；部分旧 Trellis 任务仍为待核实 | 针对性升级回归；按证据逐任务结项，不凭“代码在”推断完成。下面列出的已闭环任务本次更新状态 |

不因本次问题立即引入：复杂单 Task DAG、消息队列重构、向量数据库、独立进程 fleet、自主扩权、自动生产部署。
它们不是当前可靠交付/知识闭环的必要前提；若未来有测量证据，再单独设计。

此外，既有工程台账仍列 Reporter/T033（角色或确定性服务尚未决定）、T044 的历史特定恢复验收、
Requirement 独立源基线的完整环境验收、Worker 独立进程/多 Task 验收等。
本次成功需求不能自动替这些任务结项，先核对各自验收证据再判断是补实现还是补验收。
收尾的全目录台账检查还发现两个既有问题：`09-21-chinese-knowledge-confirmations` 有 task.json
但未出现在索引；`09-21-operation-notification-dialog` 有 PRD 却无 task.json。
本轮未凭实现猜测它们完成，也未伪造元数据；列入 P2 台账治理，当前五个相关任务的 metadata/index 已单独验证。

### 每个角色在“可进化 AI Team”中的职责

| 角色/组件 | 对进化负责什么 | 不应该做什么 |
|---|---|---|
| Manager | 识别缺口、协调资源/环境/授权、跟进解除与恢复；汇总可复用处理经验并提案 | 直接改业务源码、写 QA verdict、把人工建议当授权 |
| Product | 需求语义、验收条件、可复用业务事实候选 | 自批 ProductSpec、把猜测发布成知识 |
| Designer / Planner | 技术决策、依赖/风险/能力需求和有证据的设计经验 | 设计文档直接激活新执行权限或替代真实派发 |
| Coder | 使用足够上下文实现需求，记录可验证发现 | 自己验收自己、改平台权限/spec 或其他角色报告 |
| QA / Reviewer | 独立验证同一候选、审查证据、反馈失败模式/经验 | 用未执行项冒充 PASS、擅自修源码或扩权 |
| Knowledge Plane | 管理提案/批准/发布/选择/冻结/检索/引用与退休 | 把模型记忆、环境状态、可执行能力混成一份无版本文档 |
| 确定性执行器/调度器 | enforce policy、lease、idempotency、evidence 和版本兼容 | 让自然语言覆盖机器权限或凭证边界 |

“自我进化”应是**有证据的提案积累 + 受治理的知识/能力发布**，不是让 Agent 自己给自己开权限。

## 当前验证口径与未做事项

- ASE 最新全离线回归：1971 passed、10 明确 opt-in skipped、101 MySQL deselected。
- 最终 Project/Knowledge 修复：Node 61 passed；相关 Python 151 passed；Ruff、strict Mypy 485、构建通过；真实浏览器切换通过。
- Reviewer-only 修复另有 4 个真实 Git/隔离 MySQL 组合通过；较早审查的 95 个 MySQL 是分批补齐，不称本次最新全库一次全绿。
- 真实原需求已由 ASE 独立角色验收到 DONE。Mock UI 证据仍是 Mock，不据此宣称真实 OAuth 链路验收。
- 本轮没有实施自动采集/通用能力扩展，没有清理历史 sidecar/worktree，也没有改生产数据库或重跑已 DONE 的需求。

## 证据索引

- E1：[审批、Responses、Swift 计划、错误诊断分析](../../.trellis/tasks/09-25-joint-approval-delivery/bug-analysis.md)
- E2：[Manager/受控执行器接通](../../.trellis/tasks/09-25-joint-approval-delivery/manager-executor-bug-analysis.md)
- E3：[队列等待、CLI 权限、执行器前置失败](../../.trellis/tasks/09-25-joint-approval-delivery/analysis-20260927.md)
- E4：[UI 前提与保留修复目标](../../.trellis/tasks/09-25-joint-approval-delivery/continuation-20260926-native-ui.md)
- E5：[知识等待与升级兼容](../../.trellis/tasks/09-25-joint-approval-delivery/knowledge-wait-analysis.md)
- E6：[14 阶段审查矩阵](../../.trellis/tasks/09-27-delivery-reliability-audit/audit.md)及[逐轮验证](../../.trellis/tasks/09-27-delivery-reliability-audit/verification.md)
- E7：[恢复后全部增量修复与真实 Operation 时间线](../../.trellis/tasks/09-25-joint-approval-delivery/continuation-20260927-post-audit.md)
- E8：[独立 Reviewer-only 恢复](../../.trellis/tasks/09-25-joint-approval-delivery/reviewer-recovery-analysis.md)
- E9：[显式知识闭环验证](../../.trellis/tasks/09-25-team-evolution-audit/verification.md)与[当前 executable contract](../../.trellis/spec/core/project-learning.md)
- E10：[项目切换验证](../../.trellis/tasks/09-28-project-switch-refresh/verification.md)、[导航规范](../../.trellis/spec/core/project-navigation.md)、[Console readiness 契约](../../.trellis/spec/core/web-console.md)

未完成项的当前代码检查：`learning.py:ProjectLearningStore.collect` 仅收 finding 和三种 delivery report
observations；生产显式调用在 `web_console.administration.collect_project_learnings`；
`_publish_skill_design` 仅写设计提案，不安装执行器。完整记录优先于历史日志里尚未更新的“待完成”句子。
