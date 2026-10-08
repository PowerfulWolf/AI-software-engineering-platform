# 工程授权与非终态等待处置

## Scope / Trigger

修改新 Task 的工程 policy、Manager 自动工程动作、恢复授权、人工主体、Console 工程调查或
非终态 WorkItem 继续入口时必须遵守本契约。业务范围批准与工程授权是不同职责；产品用户
无需理解 lease、补丁 hash 或工作区目录。前端仅显示同一 durable disposition 的责任和下一步。

旧终态恢复仍遵守 `delivery-recovery.md`；本契约不重新打开旧终态、不修改角色 verdict，
也不替代 Product 对 exact spec 的批准。

## Signatures

```python
LocalOperatorPrincipal.require_duty(duty: OperatorDuty) -> None
EngineeringPolicy.bounded_local(scope: EngineeringScope,
                                principal: LocalOperatorPrincipal) -> EngineeringPolicy
EngineeringAuthority.admit(task: Task, store: FileRecoveryStore,
                           plan_sha256: str, facts_sha256: str,
                           capabilities: tuple[EngineeringCapability, ...],
                           at: datetime) -> EngineeringAdmission
CandidateVerificationEntry.authorize_policy(path: Path) -> EngineeringAdmission | None
DeliveryWaitService.inspect(command: InspectDeliveryWait) -> DeliveryWaitInvestigation
DeliveryWaitService.handle(command: HandleDeliveryWait) -> DeliveryWaitHandling
DeliveryWaitService.resolve(command: ResolveDeliveryWait) -> DeliveryResolution
ProductionProjectDeliveryBackend.authorize_product_action() -> None
UnifiedProjectEntryService(..., product_action_authorizer: Callable[[], None] | None = None)
TeamHost.inspect_delivery_wait(command: InspectDeliveryWait, *,
                               project_id: str, delivery_id: str) -> DeliveryWaitInvestigation
TeamHost.handle_delivery_wait(command: HandleDeliveryWait, *,
                              project_id: str, delivery_id: str) -> DeliveryWaitHandling
TeamHost.resolve_delivery_wait(command: ResolveDeliveryWait, *,
                               project_id: str, delivery_id: str) -> DeliveryResolution
ProductionProjectDeliveryBackend.inspect_delivery_wait_prerequisites(
    task: Task, step: QueuedRoleStep,
    checkpoint: ProjectDeliveryCheckpoint) -> DeliveryPreflightReceipt
MySqlRoleQueue.resolve_wait(resolution: DeliveryResolution) -> QueuedWorkItem
```

请求不能提交 `operator_id`、职责任意集合、`process_stopped=true`、权限扩张或自由文本命令。
主体来自可信 Host composition；Product、Engineering 操作在服务边界检查职责。新联合 Product
批准封存实际 `operator_principal`；旧字段缺省 None 并排除序列化，保持历史摘要。
Native Product 的 start/reply/approve 也必须在 prepare/current/reconcile、journal写入和模型调用
之前检查 Product 职责, 不能只保护 joint Product 或Web Console。`with_backend` 保留同一 typed
authorizer; Engineering-only主体对公开及直接native服务入口均零调用、零文件变更。
`resume` 在 PREPARING/PRODUCT_DISCOVERY 前也检查 Product 职责；`retry_interrupted_stage`
对 PREPARING、PRODUCT_DISCOVERY、WAITING_PRODUCT_REPLY、WAITING_PRODUCT_APPROVAL 的恢复，
在 reconcile 或恢复 checkpoint 写入前检查。已批准 Design/Plan/Delivery 的工程继续不要求
Product 职责，工程状态只读仍可使用；不能以一次后台恢复绕过业务职责保护。

## Contracts

- 新生产 Task 冻结工程 policy 的版本、Team/Project/Repository、精确真实仓库根、签发主体、
  已注册能力与逐能力/总预算。旧 Task 无 policy 不获得追溯授权。
- `EngineeringAdmission` 是 policy 的确定性应用记录，不是 `RecoveryAuthorization`，
  不带人工批准 decision 或伪造 operator_id。它绑定完整 policy、冻结 Task intent、精确
  plan/facts、能力集合与使用序号。人工决定与自动动作分别审计。
- Team 共享 authority ledger 按 Repository+Task 隔离；先写共享账本，再写本地恢复 store。
  本地 publication 中断后恢复精确 receipt，不重新消费额度。不同 store 不能各拿完整预算。
- 旧 `RecoveryScope` 只有 Team/Repository/Delivery/root, 不独立建立 Project authority。
  工程 admission 必须由可信 Host 的 Requirement → Project workspace → 原 Task 绑定入口调用;
  新 Task 的 `EngineeringPolicy.scope` 保留完整 Project 身份, ProductionFacts 在 admission 前
  精确比较完整 scope。不得仅凭旧 recovery 路径或相同 repository root 认定跨 Project 授权。
- verification refresh 必须重新核验当前 native Task/候选/计划事实；登记受控能力只表示
  可以开始执行，不表示环境已修好、命令已通过或 QA/Review verdict 已存在。每个验证角色
  仍有独立真实 claim、Run、Context；候选 SHA 不变，未知调用禁止复用旧批准重放。
- 原范围源码前提修复必须在 Task 原 write paths 内、避开 deny paths；不能增加验收范围、
  命令、网络、凭据或安装权限。修改必须经受控 Coder 与独立 QA/Review，Manager 不能改代码。
- `EngineeringAuthorityRejected.kind` 是 typed 路由事实。不得解析中文原因猜测业务责任。
  旧授权、新能力、scope/输入漂移、预算耗尽分别保留原事实并交对应授权者。
- 非终态工程等待来自 `DeliveryDisposition`。调查命令绑定 work item、disposition 摘要、
  Task intent、source revision、checkpoint sequence；Host 同时核验 Project Requirement 的
  当前 native 子 Task 和 Repository 注册事实，防止跨 Project 或 Requirement 消费。
- 工程调查的生产 prerequisite collector 必须只读重开 checkpoint 的原 sealed preparation、
  profile、runtime binding 与 compiled spec，校验完整身份/摘要；读取原 dispatch 的权限与
  当前 accepted Plan，以 `step.boundary.source_revision` 检查当前真实注册 executor 前提。
  若已有 execution-baseline binding，仍须校验最新 binding 的完整冻结 Task intent。
  主 checkout 或原生规范升级不能让调查重新 prepare、替换旧批准输入，或在环境检查前误报
  preparation drift。缺失、篡改或不唯一的原记录仍拒绝，禁止 fallback 当前 prepare。
  通用执行 `_facts_for_checkpoint` 的当前准备漂移守卫不变；新代码基线和新规范仍需独立授权。
- 调查取得 manager-owned Task process lock，再读取 exact invocation start/outcome、可信
  continuation receipt、停止进程组及完整 Git/inventory。租约到期不等于进程停止；未知
  调用不能退款、复用旧 Run 或靠产品勾选一个布尔值变成安全。
- 调查结果以 immutable sidecar `wait-investigations` 封存。缺项仍形成可操作工程记录，
  保持等待和现场。处理页面不得显示“已继续”或只有“无需产品操作”而没有责任和缺项。
- `REPLAY_RECORDED_RESULT` 仅重放封存 exact request/result，不重新调用模型，不消费新额度；
  同时封存原真实历史 assignment/lease/model selection 和 request permissions/run/context/source。
  新 claim 不能把原产物归给其他 Agent 或改写 producer。Worker 仍按普通 artifact/verdict/独立性
  guards 接纳，调查不产生 verdict。
  durable INVALID_OUTPUT/PLATFORM_BUG 等拒绝分类, 或原结果为非临时失败, 不能再次广告接纳。
  原 raw outcome 可以 SUCCEEDED, parent/supersedes/验收契约却在封存后被runner拒绝; 不能只看
  adapter status。无真实stop/checkpoint时记录`OUTCOME_REJECTED`并保留原失败, 明确工程修复
  契约和收集停机现场的下一步。有原真实local limit receipt、完整合法现场及冻结工作额度时,
  可走现有checkpoint retry, 不复用旧被拒产物; 不能用provider receipt给拒绝产物退款。
- `RETRY_FROM_CHECKPOINT` 需要匹配原 Run/claim/Task policy 的可信停止记录和完整现场。
  resolution 的 `retry_cause` 由 collector 从 receipt 构造，用户不能指定。provider transient
  才追加 `retry_failure` 并消费对应 transient 额度；本地执行窗口耗尽消耗工作额度，不冒充
  provider failure 退款。queue 在单一 MySQL fence 内核验 Task/WorkItem/Step、无 live claim、
  原等待与剩余额度，并建立新的 step/attempt/claim/Run；旧调用历史不覆盖，Coder 仍沿用原
  branch/worktree。
- `RESUME_UNINVOKED` 只处理确实在调用前暂停的 preflight 等待：无 invocation start，
  原 claimed preflight marker 与等待 evidence 精确匹配，当前前提通过真实 discovery 重新
  核验 READY。保留当前未使用的执行身份，以新 claim 开始下一实际调用；无追溯零调用推断。
- `REVERIFY_CANDIDATE` 处理已接纳的 QA `FAIL` 中 `NOT_TESTED/ERROR` 环境结论。只有
  deterministic `classify_qa_failure=RETRY_VERIFICATION`、精确 sealed outcome、真实原 claim、
  accepted QA receipt、已接纳的 implementation parent 与相同 candidate SHA，以及当前真实
  prerequisites READY，才能封存 `VerificationRetryEvidence` 并发起新一次独立验收。
  evidence 绑定前次 QA ID/digest、Run/Context、outcome、candidate、当前 prerequisite facts。
  它明确消耗 `frozen_work_attempt`，不冒充 provider transient；必须用新的 attempt/claim/
  Run/Context，不能再选择同一个旧 FAIL 后立即回到同一等待，旧 FAIL 不改写。
  原 adapter outcome 可以保留未封存 draft integrity; collector 以共享 `artifact_digest` 精确
  比较 draft 与 accepted sealed artifact 的所有语义字段, 仅排除 store-owned integrity,
  并核验 sealed digest/accepted receipt。不得要求两个 integrity timestamp 相同或放宽内容/父链身份。
- 当前 prerequisite receipt 的 checked_at 可以不同；proof 保留原完整 receipt 引用并绑定
  排除时钟的事实摘要。复验比较 capability/tool/permission/source 的实际事实，不能因时钟
 变化强迫重复调查，也不能以忽略全部 receipt 字段掩盖前提漂移。
- 工程决定先 immutable 封存再消费，精确重放幂等；不同 proof、kind 或 actor 不能覆盖同一
  等待的决定。消费后 Host 驱动原 Requirement 一次同步 Supervisor；READY 不是已执行。
- Console 工程区使用只读 `RoleQueueView.wait_disposition_sha256`，不在浏览器重算或猜测
  disposition 身份。调查/处理提交同时绑定 Project、Requirement 当前 checkpoint 与完整
  WorkItem/Task/source/checkpoint facts；旧按钮闭包在事实或 proof 更新后拒提交。
- 产品摘要继续显示等待、责任与下一步；当前工程处理卡片直接显示调查、缺项和允许的决定。
  调查绑定摘要放在内层参考折叠，不能同时折叠当前必须处理的交互。
  摘要同时保留控制平面封存的具体中文 `disposition.detail`, 如测试入口或工具缺失, 不能只显示
  泛化“工程前提未满足”。展示先使用共享 secret redaction; 原 disposition bytes/hash 不修改。
  只有匹配当前绑定、完整且提供 `permitted_resolutions` 的 proof 才显示对应决定按钮。
  缺少 stop 或原身份时没有“确认已停止”布尔输入；已有决定不显示可重复消费按钮。
- 工程区在提交和轮询后保留展开状态，但精确操作控件重新绑定新事实。调查成功或决定
  成功不覆盖 durable WAITING，也不显示 QA/Review 通过。需求操作记录展示所有 Operation，
  任务执行历史展示全部调查、工程决定、前提检查与实际角色执行，均不裁成最后 8 条。
- 旧终态兼容流程的工程失败封存 `EngineeringDispositionRecord`，绑定原 terminal Task 快照、
  native checkpoint、plan 和 typed rejection code。其 disposition `work_item_id=None`，不伪造
  非终态 queue wait，不重新打开 terminal history。原因/下一步中文，原始诊断只作为技术证据。
- QA/Review 验证准备在真实 claim 内、模型 invocation-start 之前完成，封存完整原请求的
  `VerifierPreparationCheckpoint`。工程调查重读 native binding/started/final 并核对原历史
  claim、当前 Task 快照、source、role、attempt、Run/Context 与新 prerequisite facts。
  NOT_STARTED 允许 `RESUME_UNINVOKED`，保留已预留工作 attempt，但更换 claim/Run/Context；
  FINISHED 绑定真实 final 而角色模型尚未调用时允许 `RETRY_VERIFIER_PREPARATION`，使用一次冻结
  work allowance 并新建 attempt/claim/Run/Context。不得伪造 provider transient 故障；
  原准备成功时 native_failure_code 必须保持 absent，不伪造失败理由。
  STARTED 无 final、记录损坏或观察未知时保留 `NATIVE_EXECUTION_UNCERTAIN`。
  `VerifierPreparationIntent` 必须先于 native command 封存; lease 重新领取后, checkpoint 保留
  原 intent 的 dispatch_sequence/lease_id 和发布等待的 wait_dispatch_sequence/wait_lease_id。
  调查分别核验两份历史 claim, 原 dispatch 不得晚于等待 dispatch, 当前 item 绑定等待 generation;
  两者无需相同, native observation 始终读原 request/claim, 不能用新 Run 掩盖旧未知执行。
- 工程历史读取会校验 decision 与 proof 的完整 Task/source/checkpoint/step/快照/action 绑定。
  native 执行阶段必须匹配文件、Run 目录和 Requirement；STARTED/final 仅为执行事实，
  不推断 PASS。所有投影文字和嵌套 detail 使用共享 secret redaction，原 bytes/hash 保持不变。
  旧终态工程说明可覆盖产品展示的原因和下一步，但不能把原 terminal Task 改回等待或执行。
  accepted QA遇到环境结论可以直接发布queue等待而不增加StateEvent; 产物历史必须读取
  StateEvent artifact IDs与已验证accepted receipts的并集。后者需逐项核验Task、SHA、Run、
  Context和source, 保留完整finding/命令/父链/修订, 不扫描未接纳文件来冒充独立验收结果。
  QA environment 也须保留完整 typed 值；没有 findings 的 NOT_TESTED/ERROR 报告仍可能通过
  environment 解释无法验收的原因。Console 将其安全地折叠显示，不能丢掉这类不通过理由。
  Artifact 时间使用 store-owned integrity.validated_at；provider created_at 只在 detail 保留。
  相同封存时间的结果必须使用唯一原 CLAIMED 事件的 SQL sequence，并精确核验 accepted
  receipt 的 Task/work item/lease/role/checkpoint/dispatch generation。旧库只有 StateEvent
  references 时保留已验证 revision 引用顺序；不同 durable stream 的序号不能相互比较。
  最新 candidate/QA/Review 与执行历史共同使用 sealed/lineage 排序能力，不能用随机 Artifact
  ID 或模型时间挑选；缺少可证明的唯一最新结果应拒绝判定，不能把旧 FAIL 覆盖新 PASS。
  终态结果重建 `_terminal_delivery_result(repository, artifacts, task_id, *,
  coder_execution_inputs=None)` 也必须读取完整 accepted artifacts，并沿同一基线 resolver 排除
  `superseded_implementation_artifact_id`。BLOCKED/FAILED 的 candidate 只来自已完成 implementation
  report 的 commit_sha、精确 source 和原验收覆盖，不能从停止事件的 execution input source
  猜测；接纳报告落盘后、candidate checkpoint 前停止，重启仍须保留报告与候选引用。
  Supervisor 必须传原可信 baseline_inputs；旧 candidate_ready 历史不能复活已被新基线废弃的
  候选。DONE 继续要求 exact 四产物及同 SHA 独立 QA/Review，不借终态重建提升验收。
- Coder 原分支基线更新通过 `PROPOSE_EXECUTION_BASELINE` 和
  `EXECUTE_EXECUTION_BASELINE` 公开 typed Console 入口。基线工程区只在已验证的
  IMPLEMENTING Task、唯一非活跃 Coder slot、精确 Task intent/revision/source 可读时提供
  操作。默认 preserve_draft；冲突只能显式另提 coder_reapply 新计划。只有当前封存计划
  可以批准，旧 checkpoint/revision/plan 控件拒提交；QA/Review 不提供 Coder 基线变更按钮。
  无计划时入口默认折叠为可选操作；存在未执行计划时计划与决定直接可见，冲突不隐藏。

## Validation Matrix

| 输入/事实 | 结果 |
|---|---|
| 首次preflight等待后主checkout/原生规范升级 | 调查原批准source与sealed上下文，检查真实当前前提；不rebase或调用模型 |
| 调查缺失/篡改sealed preparation、stale source或baseline intent | 拒绝，保持原Task/等待，不制造新批准或恢复proof |
| 已改执行输入、无 accepted implementation | 重建 candidate=None，输入 SHA 不冒充候选 |
| implementation已接纳、candidate checkpoint尚未写入 | 按accepted报告保留真实candidate和Artifact引用 |
| 原candidate_ready存在、对应implementation已由基线废弃 | 原记录保留，candidate=None；新报告存在则只保留新candidate |
| 终态report source/commit或验收覆盖漂移 | 拒重建，不回退旧StateEvent source或放宽DONE验收 |
| 新冻结 policy、精确 scope/plan/facts、已注册能力、预算内 | 独立自动 admission |
| 共享 ledger 已封存、本地写入中断 | 恢复同 receipt/序号，不重复计费 |
| 旧 Task 无 policy、漂移、新安装/网络/凭据/能力 | 拒自动，记录对应工程责任 |
| Product-only 主体请求工程批准/调查/处理 | Host/服务边界先拒绝，无模型或执行 |
| Engineering-only 主体创建/修改/批准业务需求 | Product 职责检查拒绝 |
| Engineering-only请求native Product start/reply/approve | 入口最早拒绝; 无prepare、reconcile、journal或模型调用 |
| 真实 stopped receipt、完整合法现场、预算余量 | 精确 retry decision，新执行身份 |
| 调查后 worktree/source/Task/step/prerequisite 漂移 | 拒消费，旧记录和等待保留 |
| 真实 sealed outcome 但无停止 receipt | 仅允许 exact result replay，零新调用 |
| sealed outcome已被拒绝, raw status为FAILED或SUCCEEDED | 禁止重复接纳; 无真实停机则等待并列出中文工程处置 |
| accepted QA 的 NOT_TESTED/ERROR，候选未变、当前前提 READY、工作额度内 | 新验收 reservation；旧 QA 保留，禁止只重放旧 FAIL |
| 同类 QA 但缺 accepted receipt、候选 parent、前提或预算 | 保持等待并列缺项，不把环境结论改为代码缺陷 |
| 原 invocation start 已有、结果未知且无 stop/checkpoint | 封存缺项调查，保持等待 |
| 无 start、原 claimed preflight marker、当前重查 READY | 恢复尚未调用的 step，新 claim |
| lease 过期但 Task lock/进程组仍活跃 | 拒执行，保持原现场 |
| 试图提交 stop bool、actor、retry_failure 或自由 shell | typed 请求入口拒绝额外字段 |
| 重启后同工程决定再次提交 | 返回原决定，queue 消费幂等 |
| 执行预算耗尽 | 不退款、不启动，不用工程决定替代追加资源授权 |

## Good / Base / Bad

- Good：模型短暂失败后的合法 Coder 改动有真实 stop、完整 mutation receipt 和冻结预算。
  平台消费原失败后以新 claim 继续原 Task/branch，再进行独立 QA/Review；自动动作标为 policy。
- Base：未知执行没有可信 stop，工程调查指出缺项并保留等待。工程用户看到可核验的事实，
  产品用户只看到工程负责处理和当前下一步，不被要求审批内部 hash。
- Bad：Manager 生成一条“用户已批准”字符串、lease 到期后推断没执行、修改历史 verdict 或
  每次新建 recovery Task/branch 代替正常返工。全部违反本契约。

## Product user path for an engineering wait (2026-10-08)

`HandleDeliveryWait` is the product-facing request to let the platform process one exact current
engineering wait. It carries only the displayed `work_item_id`, disposition digest, frozen Task
intent, source revision and checkpoint sequence. It cannot carry a stop flag, actor, retry cause,
hash override or shell command. `TeamHost.handle_delivery_wait()` executes one bounded collector
under the Task lock and queue idle fence, then records one immutable `DeliveryWaitHandling` before
the optional existing Supervisor continuation. It must not create a new Requirement, Task, branch,
or model Run merely because a wait was displayed.

The handling record has `status`, `summary`, `user_action`, `recheck_when`,
`manual_resolution_allowed`, `collection_failed`, the exact investigation and (only when
resolved) the exact resolution. `RESOLVED` means a policy or real engineering decision was
sealed and the original delivery was handed back to the existing Supervisor; it does not mean QA,
Review or final delivery succeeded. `WAITING_EXECUTION` means the process may still be live or its
stop is not proven. `NEEDS_AUTHORIZATION` means the old Task has no new frozen capability and
requires an actual engineering decision. `PLATFORM_ATTENTION` means records or fact collection
failed and the system must preserve the original wait; a product user is not asked to repair it.

| Product view | Platform responsibility | User action |
|---|---|---|
| `WAITING_EXECUTION` | preserve worktree and wait for durable stop facts | check again after the displayed condition; never start a second Coder |
| `RESOLVED` | continue once through the original delivery Supervisor | read subsequent role records and independent QA/Review |
| `NEEDS_AUTHORIZATION` | keep exact proof and expose an engineering decision entry | an engineering-duty operator decides the listed exact action |
| `PLATFORM_ATTENTION` | retain evidence and report the missing/corrupt record in Chinese | wait for ASE maintenance; repeated inspection cannot repair the record |
| `BUDGET_EXHAUSTED` | do not refund or silently expand frozen budget | an authorized owner decides whether to provide new resource authority |

The Console must make “让平台处理中断” the primary action for an active engineering wait. The
current card keeps the reason, responsible party, concrete action and recheck condition visible;
technical IDs and digests remain in a secondary engineering details section. “重新检查状态” is
secondary and must say that it only re-reads durable facts. Operation success is command completion,
not delivery completion. The full operation and engineering timeline is retained; it is never
truncated to the last eight entries.

Legacy Tasks without a frozen wait-resolution capability are not retroactively expanded. If their
sealed proof is complete, an engineering-duty operator may record the exact decision. If the old
run has no trustworthy start/stop/claim or complete workspace facts, the platform records
`PLATFORM_ATTENTION` and does not invent a timeout or checkpoint. Existing production data needs no
migration; the user refreshes after the service is idle, submits the exact platform-handling action,
and reads the resulting report. A real missing ledger remains a maintenance defect, not a product
approval step.

## Tests / Evidence

增量测试覆盖共享预算/partial publication/restart、真实 pinned candidate QA/Review、Product
与 Engineering 权限、未知调用拒绝、真实 Git/inventory 停机 proof、漂移后拒绝、封存 outcome
重放、preflight 前提变化、queue 原子预算/身份与 Console exact checkpoint。生产 Host 集成使用
离线 fake adapters 和串行 MySQL fixture，不触发真实业务模型。相关 selectors：

```text
tests/manager/test_engineering_authority.py
tests/manager/test_native_product_authority.py
tests/manager/test_terminal_candidate_reconstruction.py
tests/manager/test_delivery_wait.py
tests/manager/test_production_execution_baseline.py
tests/manager/test_sealed_preparation.py
tests/recovery/test_engineering_verification.py
tests/work_queue/test_invocation_journal.py
tests/work_queue/test_wait_resolution_mysql.py
tests/team_view/engineering-wait.test.cjs
tests/team_view/browser/engineering-wait.test.cjs
tests/team_view/test_accepted_artifact_history.py
```

工程调查 frozen-preparation 回归通过公共 `TeamHost.inspect_delivery_wait` 复现未调用 Coder 的
preflight 等待：升级主分支并新增 AGENTS 后，调查必须封存原 source 的真实 WAIT receipt，
保持 Task/events/revision、queue、checkpoint 和原批准记录不变；stale expected source 拒绝。
生产 backend 的缺失/损坏 sealed preparation 测试必须拒绝且不重建准备或调查 proof；已有
binding 时修改 Task intent 必须在 discovery 前拒绝。调查与更新原分支基线的授权不能混用。

Wrong：调查先 `prepare(当前主checkout)` 并要求旧准备摘要一致。
Correct：读取精确原 sealed 上下文、校验当前 binding，再按 queued source 检查当前 executor。

## 存量数据处置 / Rollback

2026-10-06 调查 preparation 漂移修复不需要改库。当前原 K1 的 FAILED 调查 Operation 保留，
它未产生可用 proof，不能改成成功或直接解除等待。服务装载后由用户在同一需求重新调查，
只有新 proof 提供精确可用的处理方式才继续。前提缺项先由工程人员处理后重新调查；含新原生
规范的最新 main 仍不是原批准输入，不由环境调查自动更新或批准。

不回写旧 Task policy、人工批准或终态。旧记录 bytes/hash 保持兼容；新 schema 字段 absent
排除序列化。已删除的 K1 维持 tombstone，不重建、不触发业务执行。旧终态只能走已有显式
审计恢复；旧非终态无 proof 时保留等待，先工程调查并收集真实前提，禁止直接 SQL 改状态。

回滚运行时代码前暂停新工程操作，保存已封存 authority/proof/decision 及 queue history；旧版本
不能消费不认识的新 policy/resolution，应安全拒绝而不是删记录或重置预算。schema、服务和 UI
作为同一版本部署。任务现场、角色证据与独立验收历史不清理。
