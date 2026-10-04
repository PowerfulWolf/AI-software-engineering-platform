# 面向产品用户的交付与中断续跑方案

日期：2026-10-04。状态：第一切片已实现并通过增量验证；后续扩展仍需独立契约和测试。

## 1. 产品定位与职责

普通用户是产品负责人。用户决定做什么、为什么做、验收标准、业务取舍和资源上限；ASE 团队负责工程实现、质量验收、已授权的技术恢复和完整过程记录。lease、Run、恢复 Task、patch hash、源码基线是平台内部工程事实，不能成为日常产品操作的前提。

这要求同时改变后端责任分配和前端呈现。只隐藏技术字段、保留每次技术故障都等产品点击的执行逻辑，不满足此目标。

| 决策 | 责任主体 | 产品界面 |
|---|---|---|
| 需求目标、范围、验收歧义、业务行为变化 | 产品负责人 | 具体问题、选项、影响、建议、批准后的记录 |
| 范围内实现选择、QA/Review 返工、已授权服务重试、可验证中断续跑 | ASE 团队，确定性 policy 校验 | 自动处理进度、原因和完整历史，无技术审批要求 |
| 普通工程基线更新 | 获版本化工程授权的团队机制；新输入必须重新绑定事实 | 未改变业务时展示工程进度，不要求产品选择 commit/hash |
| 新执行能力、命令/目录/网络权限、凭据、超出资源授权 | 工程管理员/授权者 | 标明等待工程处理；若涉及产品资源或业务取舍，再询问产品 |
| Candidate 质量 | 独立 QA/Reviewer | 报告、返工理由和最终验证结果，不由 Manager 或产品覆盖 verdict |

产品负责人和工程管理员可以是同一个人，但两个身份、操作入口和审计类型必须明确。产品确认界面不能默认承载工程维护审批。Manager 可以组织诊断、建议方案并调用已授权 Skills；它不能批准自己提出的新权限、伪造可信人工决定、批准 ProductSpec 或覆盖 QA/Review。

自动工程动作的授权来自明确、版本化、持久化的 policy 或授权记录。不是复用一个旧 hash、让模型说“我批准”，也不是把管理员私下代点当成自治能力。产品批准仍须绑定 exact ProductSpec ID/digest；已批准业务内容改变才重新询问产品。

具体分成三类事实：产品对 exact 业务内容的决定；管理员事先授予的版本化工程执行 policy；确定性执行器按当前精确事实生成的单次 admission receipt。事实更新可以触发新 receipt，不必触发产品重新批准。自动动作记 `authorized_by_policy`，真实人类操作记实际主体和 HumanAction；两者不能混用。

目前 `local-operator/web-console/cli-user` 只是可信本机操作来源，代码没有产品/工程管理员的独立权限契约。需要在现有单 Team/可信 operator port 中显式定义职责与授权来源，不把 UI 标签当成已经实现的 RBAC，也不引入多租户。现有 `ManagerRepairCapability` 是可复用的预授权构件，但真实环境恢复装配尚未启用通用 capability 集合；不能宣称已有自动工程修复能力。

## 2. 改造前的问题与复用的能力

- `work_queue/mysql.py::wait/retry/make_ready` 已有等待、延期、释放 Lease 和 owner fence；`execution_store.py::finish(next_step)` 已有原子关闭旧 WorkItem/发布下一步骤。
- `runtime.py::RuntimeSession.run_step`、`steps.py::BoundedRunControl`、Supervisor 已限制每次领取只执行一个角色。生产知识缺口已接入精确等待 receipt 与恢复信号。
- `agents/codex_cli.py` 在 timeout/非零退出后，只要工作区有改动，就生成非 transient `POLICY_VIOLATION`；`orchestration/retry.py` 因此终态化 Task，Supervisor 关闭 WorkItem。
- 下一次调用仍要求 clean、合法 CoderProgress 或精确的 `InitialWorkspaceAdmission`。仅改错误码或 transient 标志不能解决，还可能触发同一 Run 的模型 fallback，越过草稿核验。
- 同 Task Coder worktree 已可复用，合法 progress 已支持正常续跑；普通中断缺少受控草稿事实、授权和 admission 的完整接入。

因此不新增第二套执行引擎，也不把所有阶段塞进一个巨大的恢复函数。保留已有 TaskOrchestrator、Dispatcher、Supervisor 和专用验证器；统一失败原因、下一步决定和审计记录的契约，让同一种事实只有一种处理规则。

## 3. 第一个实现切片：普通 Coder 中断的完整闭环

目标场景：新需求首次 Coder 执行已调用，可信执行器确认执行结束，模型窗口到期或明确 provider 中断，留下合法范围内草稿但没有合法 report/progress。系统保存草稿，在原有授权和预算内，用同 Task/branch 的新 Run 继续。第一版限定一次自动替代 Run；其他 attempt/返工中断按验证覆盖逐步接入，不宣称一次改动涵盖全部情况。

### 3.1 分开记录原因、工作成果和处理决定

新增 `ExecutionInterruptionReceipt`，明确它是执行事实，**不是 CoderProgress、候选、QA/Review verdict**。

receipt 至少绑定：

- Team/Project/Repository/Requirement/Task、原 Run/attempt/claim 和 Context；
- 可信执行器记录的结束原因与停机事实，不能从租约过期推断进程已停止；
- worktree 身份、原 source/当前 HEAD、branch/index、精确 dirty inventory、完整有界补丁与 SHA；
- 冻结的路径/命令权限、预算与续跑 policy 版本；
- 既有 output/candidate/accepted receipt 是否存在。

原因和草稿检查分别进行。服务中断并有草稿不等于越权；合法草稿也不等于可以接纳候选。真实违规仍停止，不能靠重试清洗。

### 3.2 前置授权与确定性 admission

增加版本化 `InterruptionContinuationPolicy`，由工程授权机制批准并随新 Task/dispatch 冻结。它规定允许的原因、可捕获变化种类、累计额度、工作区/基线不变条件、停机证明与单次 admission。旧 Task 缺该字段保持旧 digest 和审批语义，不能追溯赋权。

只有以下全部成立，确定性执行器才可自动产生一次性续跑 admission：

1. Task 尚未终态，处于允许的 Coder checkpoint，当前实现切片没有已接纳候选或模型 output；
2. 原执行已确定停止，没有仍可写入该工作区的进程/锁；旧 claim 已失效或按 fence 释放；
3. 同一工作区、branch、source/HEAD，双读 capture 与重领时的 current facts 完全一致；
4. 全部草稿在冻结权限内，无受保护路径、secret、越界/符号链接违规；
5. 原业务、范围、能力与预算授权未改变，冻结 policy 覆盖此原因及变更类型；
6. 新执行按正确预算记账，并持有新 Run、Context、WorkItem 与真实 claim。

v1 正常 capture 只覆盖有界文本新增/修改。删除、改名、文件模式变化等不能假称已有自动支持；保留现场、明确等待工程处理，未来按契约扩大可验证能力。

自动 policy 只能启用在已验收的执行能力上。Git inventory 不能证明全部文件系统副作用：ignored 文件、受保护目录下未跟踪改动等不能被 `git status` 干净掩盖。实现必须给出可信 mutation inventory 或对应 OS/tool 写入约束及真实拒绝测试；无法核验的原生 CLI 情况留在工程处理通道，不能仅凭补丁哈希开放自动续跑。

未知崩溃、结果不确定、HEAD 变化/可能已提交候选、live process、证据漂移、真实越权、终态或额度耗尽，都不能进入这条自动通道。按事实进入工程调查、精确授权或终止，不自动归为“等产品批准”。

### 3.3 持久化与调度

- 中断等待时 Task 保留 `IMPLEMENTING` 等最近交付 checkpoint，WorkItem 表达 `WAITING_DEPENDENCY/WAITING_HUMAN/RETRY_SCHEDULED` 与有类型的原因、恢复条件和解决信号。等待对象必须注明是团队、管理员还是产品。
- 已结束失败的模型 Run 不重复调用。按原始 typed 原因记账，通过现有 `record_retry_failure`/相应工作预算事务生成下一执行身份，再由 `finish(next_step)` 发布新 WorkItem。未知原因不退款，本地窗口不能伪装成 provider transient。
- 不直接把 completed model Run 丢给 `queue.retry()` 反复执行；它的同 Run claim/reclaim 语义不能代替新的模型调用身份。
- dirty 中断禁止同 request/Run 内直接换模型。保留原故障与草稿，再由新领取执行 admission；fallback 不能绕过它。
- capture 不伪造成带 remaining steps/next actions 的 CoderProgress。下一 Coder 从完整捕获输入理解草稿，自行产出合法 progress/report，候选仍由 CandidateCommitSkill 校验提交。
- 文件 receipt 与 MySQL 跨存储使用既有可重放流程：先封存事实，再在 owner fence 下绑定决定和队列变更；receipt 落盘到预算/queue finish 的崩溃窗口可在新 claim 中核验重放。admission 发布之后调用是否发生未知时，不自动重放，保留现场并走明确工程处理及正式 recovery；不声称具有通用自动崩溃恢复。

### 3.4 前端一起验收

当前阶段和当前执行状态分别展示。实现阶段保留高亮，不代表 Coder 此刻仍运行。只消费 durable facts/队列/heartbeat，不从 Manager 自由文本推断。

产品界面的示例：

- “开发因模型服务中断，草稿已保存，系统将在 45 秒后继续。”时间只能来自真实 `available_at`。
- “QA 第 2 轮发现 3 项问题，开发正在修改。”只有真实 claim/运行事实成立才显示正在修改；否则显示已排队。
- “验证环境暂不可用，团队正在处理。当前无需你操作。”
- “验收标准有两种解释，需要你确认：A / B；分别影响……”
- “执行状态暂时无法确认，团队正在检查。”不能用旧阶段或旧心跳冒充活跃执行。

执行记录包含每次中断、处理决定、授权来源、新调用、QA/Review findings、Coder 输入及后续验收，完整展示，不固定八条。hash/Run/lease 进入工程详情，产品主要看到影响、责任方和下一步。“收到反馈”不代表“已修复”，最终仍以独立验收为准。

## 4. 最小实施顺序与验收

1. 先定义上述 Coder 切片的 receipt、policy、decision、等待信号与 Schema，明确正反例；实现 adapter → capture/admission → 预算/queue → Console 的完整一条路径。
2. 用公开统一入口通过增量组合回归，再按同一 decision 契约接入其他等待原因。QA FAIL/Review REJECT 保留已有 artifact 返工路径；基线/范围变化仍用专用验证器，不全部改成中断恢复。
3. 建立产品问题与工程问题的持久化分流，并逐步整理历史恢复模块。每迁移一种事实来源才删除其旧判断，避免在旧模块外再套一层。

切片的发布验收：

| 场景 | 必须通过的结果 |
|---|---|
| provider 中断 + 合法草稿、窗口到期 + 合法草稿 | 同 Requirement/Task/branch，新 Run/claim，预算正确，无重复产品审批 |
| receipt 已封存且预算或队列尚未完成时重启 | 新 claim 中重放正确预算并调度；admission 已发布且调用未知时准确工程停止，无重复调用 |
| 草稿/HEAD 漂移、仍活跃进程、越权路径、未知 output | 无调用，保留证据并准确分流 |
| 无合法模型 progress | 不伪造 progress，不直接给 QA，不同 Run 才能再执行 |
| 两轮 QA 与两轮 Review 返工 | 完整 finding/input/candidate 历史，独立身份，同候选验收 |
| 队列等待、重试倒计时、无 heartbeat、刷新/切页 | 阶段/执行状态/责任方一致，没有假执行或过期阻塞 |
| 新 policy 与旧 Task/approval | 新 Task 可自动，旧记录 hash 不变且不追溯赋权 |

仅跑该切片影响的增量 tests/typecheck/format 与公共路径组合测试。完整仓库测试继续交用户负责。

## 5. 现有 K1 与存量数据

本轮没有启动 K1、批准恢复或改写终态 Task。已按用户要求通过正式 DELETE_REQUIREMENT 退役两个 K1，两个 Operation 均成功且无模型调用；Requirement tombstone、sealed artifact/event、历史 worktree 和审计记录保留，产品列表、详情和继续入口均拒绝已退役身份。

旧草稿和完整历史按正式退役事实保留，不再启动旧身份。后续如用户重新提出需求，必须使用当前版本新建全新 Requirement；旧 tombstone 不会复活旧审批、Task 或预算。用户已委托的工程代办必须保留代理人与 exact 授权记录；不能冒称产品新批准或自治完成。

普通平台服务升级与目标源码版本分开。平台修 Bug 不自动要求产品重建需求，不暗中 rebase 候选；只有目标源码确需新内容才由工程授权流程更新基线。已形成候选的 QA/Review 始终验同一 SHA。

长期正常路径用非终态等待和同 Task 续跑；旧终态 successor 是兼容处置，不成为日常用户需要选择的功能。

## 6. 保持不变的约束与本轮验证

无单 Task 并行/DAG、无角色自我批准、无自动保护分支合并、无直接生产 SQL 修状态、无删除草稿或重写 sealed 事实。Manager 不持有 shell/store ambient authority。原生 CLI 写入边界仍需单独验证，后置检查不冒充 OS 预防性隔离。

本轮已在 Trellis Task `10-04-product-oriented-resumption` 下实现上述第一切片、产品状态/完整历史与安全删除入口。真实生产 factory、Worker、队列和候选校验接线的增量组合测试已通过：使用可控模型 runner，首轮 owned Python 子进程写入草稿后超时，同工作区的新 Coder Run 接续，独立 QA/Review 后到达 DONE。不会把 fake model 测试称为真实模型交付。发布与两个 K1 的实际删除结果记入该 Task 的 implement.md；暂不运行任何业务需求或全量 tests。回滚须保留新增历史事实、旧 policy 兼容读取和删除 tombstone。
