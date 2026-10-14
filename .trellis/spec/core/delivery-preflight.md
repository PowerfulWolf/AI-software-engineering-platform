# 交付执行窗口与原角色验证准备

## 范围与签名

新需求的可信平台配置冻结 `PlanExecutionWindow`；模型只能在这个窗口内组织完整已批准范围。
实施前检查验证前提，QA/Reviewer 在原 Task、原候选和真实独立 role claim 内执行验证准备。
准备、命令执行、模型调用和角色 verdict 是四种不同事实。

```python
PlanExecutionWindow.for_seconds(seconds: int) -> PlanExecutionWindow
select_coder_work_slice(task, plan, *, attempt, source_revision, progress) -> CoderWorkSlice | None
validate_coder_slice_output(work: CoderWorkSlice, artifact: Artifact) -> None
JointDeliveryService(..., execution_window: PlanExecutionWindow | None = None)
compile_joint_plan(checkpoint: JointCheckpoint, plan: JointExecutionPlan) -> JointExecutionPlan
inspect_delivery_prerequisites(..., controlled_capabilities=(), controlled_discovery_detail=None,
                               source_revision=None) -> DeliveryPreflightReceipt
RegisteredNativePythonVerifier.discover(task, plan, scope, source_revision=None) -> tuple[DiscoveredControlledCapability, ...]
DispatchDeliveryAgentAdapter.prepare_verifier(request: AgentRequest) -> None
ConfiguredDeliveryRouteAdapterFactory.prepare_verifier(*, request, route, binding) -> None
RegisteredNativePythonVerifier.prepare_verifier(*, request, workspace_root, guard, allow_ordinary_commands=False) -> None
NativePythonVerificationEvidence.validate_current(request, workspace_root, execution_guard=None) -> None
RegisteredNativePythonVerifier.observe_verifier_preparation(request, lease_id) -> VerifierPreparationObservation
observe_verifier_preparation(*, repository_workspace_root, request, lease_id) -> VerifierPreparationObservation
PreflightInvocationControl(..., prepare_verifier=None, observe_verifier=None)
PreflightInvocationControl(..., resumed_preparation: Callable[[VerifierPreparationIntent, QueueClaim], bool] | None)
PreflightInvocationControl(..., prepare_input: Callable[[AgentRequest], None] | None,
                          discard_prepared_input: Callable[[AgentRequest], None] | None)
DispatchDeliveryAgentAdapter.prepare_input(request: AgentRequest) -> None
ModelInputPreparation.prepare_input(request: AgentRequest) -> None
ModelInputPreparation.discard_prepared_input(request: AgentRequest) -> None
BoundModelInputBudget.check(request: AgentRequest, content: str) -> None
NativeCoderContinuation.preview(request: AgentRequest, root: Path) -> str | None
```

## 可信窗口与串行工作

- `hard_seconds` 为 2..3600；完成预留为 1..300 且严格小于执行窗口。
  `for_seconds` 的预留为窗口的五分之一，最多 300 秒。保留至多一个后续 Coder 工作额度供
  QA/Review 返工；它是安排原则，不是新增额度或成功保证。
- 新联合需求在初次 intake 冻结 `JointCheckpoint.execution_window`；journal successor 不可更改。
  重新构造 Host 或更新设置不能静默更改已准备/批准需求。
- SIMPLE 和 COMPLEX 计划均通过 `compile_joint_plan` 机械注入各 unit Draft 的同一窗口。
  Planner 未输出窗口可以填入；不同窗口、放大窗口或为历史无窗口需求自行发明窗口必须拒绝。
  `DerivedStageInputs` 保留批准窗口，native Planner context 和最终 ExecutionPlan 再验证相等。
- 旧字段为 None 时不出现在 wire；旧计划/需求 digest、批准和历史不重写。
- 工作切片覆盖完整 plan step IDs 的精确 partition：此前完成、本轮选择、后续步骤。
  16 个步骤和 3 个工作额度会聚合成有限批次，不能机械变成 16 个 Run，也不新增单 Task DAG。
- 非候选 progress 仍绑定输入 revision、保留完整 pending 列表和 dirty inventory。
  Coder 不能宣称完成本轮未获安排的步骤；尚有 deferred steps 时不能发布完整 candidate。
  中断和 provider 故障分别消耗冻结工作/临时故障额度，不能借窗口重置历史。

## 实施前验证门禁

Designer acceptance mapping 和 PlanTestItem 的结构化验证信息被机械投影成
`PlannedVerificationRequirement`；自然语言测试说明、仓库有 pytest 或模型的安装建议都不是入口。

| 验证事实 | 门禁结果 |
| --- | --- |
| 源码/文档 inspection，精确路径存在或显式计划创建，角色可读、Coder 可写计划新路径 | READY |
| inspection 替代批准的 unit/integration/e2e level | Schema 拒绝 |
| 明确增量普通 Responses argv，当前实际 PATH 的工具可执行，角色命令/路径允许 | READY |
| 任一 route 的显式 controlled capability | 必须有同 kind、role、source、requirement IDs 的注册 discovery |
| Codex 测试只有宿主 pytest 二进制，没有注册 executor | WAIT_ENGINEERING |
| 全量目录、裸 pytest、inline interpreter、越权入口/路径或未注册能力 | 新 Plan 拒绝；旧 Plan 封存等待，QA/Review 零调用 |
| 测试将在本轮创建 | discovery 不提前要求文件存在；最终候选 verifier 仍要求精确 tracked 文件 |
| native UI 只有 driver hash、session 在线，没有精确场景或 AX 执行前提 | 工程等待，不能冒充可执行 UI 验收 |
| Swift filter 不被现有固定 runner 执行 | typed UNSUPPORTED_SWIFT_FILTER 等待，不能执行全量来冒充过滤 |

preflight 读取精确 Git tree，不执行候选源码或待验证命令，不凭当前 dirty checkout 推断文件存在。
角色 policy 和 Task deny paths 同时检查；当前 source 可以是可信反馈/基线输入，Plan 原 hash 不变。
registered discovery 与最终执行使用同一注册对象。普通 Responses 工具和显式 controlled capability
必须区分，不能忽略后者，也不能将普通工具权限扩展到 Codex route。

`inspect_delivery_prerequisites(..., controlled_discovery_failure:
NativeVerificationWaitReason | None = None)` 接收注册执行器的 typed discovery failure。
生产 backend 捕获 `NativeVerificationWaiting` 时须传递原 `reason`，不能只把能力置空、把
已知 Swift 过滤不支持、精确节点不支持、UI 前提缺失或隔离工具不可用都变成通用“能力缺失”。
缺失受控能力的 observation 在原 reason_code 之外封存 `native_wait_reason`；该字段只允许
`WAIT_ENGINEERING + CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED`，不能携带 provider 自由文本
或附在 READY/其他原因上。未使用受控能力的普通 Responses 工具及已成功发现的精确能力不受
无关注册 discovery failure 影响。字段为空时不进入 wire/hash，旧 receipt 保持原 digest。
受控宿主发现还可封存 `native_wait_detail`，只能是版本化的安全分类（平台、Codex、Docker
上下文/套接字/服务进程、MySQL 镜像、Python 运行时、依赖指纹或 runner），不得携带原始 stderr、
绝对路径、DSN、密码、环境变量或 provider 自由文本。字段为空时不进入 wire/hash，旧 receipt
保持原 digest。工程调查的 `next_action` 将去重后的分类映射成中文处理提示；reason_code、原枚举值、
hash 只保留在技术证据中，不能把英文内部枚举直接展示给产品用户。

## 原角色内的受控 Python 验证

- exact pytest function/class-method nodes，最多 64 个；支持 `pytest`、`python[3] -m pytest`、
  `uv run pytest` 和表现 flag `-q`/`--disable-warnings`。目录、file-only、`-k`、其他 module、
  任意 interpreter、未支持 capability 必须等待。
- 原 `NativeRoleVerificationPlan` 绑定 Team/Project/Repository/Requirement、Task intent、Run、
  Context、candidate、request、permissions、accepted Plan/implementation、冻结工程 policy、
  capability 和原 work item/lease/assignment/Agent。Reviewer 同时要求该候选的 accepted QA PASS。
- `NativeRoleVerificationAdmission.authorization_source=frozen_task_role_authorization` 使用原角色预算。
  正常 QA/Review 不建立虚假的 terminal/recovery Task，不消费额外 recovery admission。
- Coder、QA、Reviewer 独立；QA/Reviewer 对同 candidate 使用独立 worktree、Context、claim、
  MySQL 资源/账户/代理。默认 Reviewer 重跑精确 QA structured checks，显式 Reviewer checks 优先。
- 低层 shared executor 只拥有 typed command/resource journal，不拥有 Task、verdict 或审批权限。
  源码只读、scratch 独立、网络禁用、仅私有 Unix socket、0600 配置、bounded output、凭据脱敏和
  精确 owned-resource cleanup 沿用 `.trellis/spec/core/verification-environment.md`。
- `native-role-verification/<task digest>/<run digest>/` 在注册 repository 外置 sidecar 保存不可变
  binding、admission、STARTED/final receipt 和 INTENT/CREATED/CLEANED/CLEANUP_FAILED。
  命令非零是给独立 QA/Reviewer 评估的证据；不能自动写 FAIL/PASS 或直接判平台故障。

## 准备与模型调用的顺序

最终 provider input 也属于启动前准备。Context sections 的 token 总和不包含 native wrapper、
序列化转义、工具提示、完整旧补丁、candidate source package 或 evidence 附件；不能以
`ContextBudget.used_input_tokens <= max_input_tokens` 推断最终输入可执行。生产顺序固定为
原 claim/prerequisite → verifier 真实准备及 READY marker → final input prepare →
`DeliveryInvocationStart` → 当前 route 实际执行。已有 durable start 时直接交原 invocation control
回放或报告不确定，不能重新编译输入、运行受控测试或以新预算结果覆盖历史。

`BoundModelInputBudget` 读取 request 精确 Context 的 identity 与 section SHA，使用现有
`estimate_input_tokens` 检查最终序列化字符串。native 编译只进行一次，包含最终随机 launcher
路径、完整 continuation、完整 source package 和 image 描述；准备结果与私有临时资源一起复用。
平台实际传给 CLI 的完整 strict output schema 字符串也计入同一预算，schema 文件按原样复用，
真实执行前复核内容。CLI 内部隐式 system 等材料不可精确观测；此处是共享 estimator 的本地一致
预算估计，不能冒充供应商实际计费 token 或保证所有隐式输入容量。
Responses 检查并复用首次完整 UTF-8 body，包含 input、tools、strict output schema 和 image data。
这是启动前初始输入门禁；后续 Responses tool-loop 新工具结果的动态增长不由此门禁保证。
不截断必要材料、不放大 Context 预算、不改变 artifact/Context wire。

Fallback 的冻结路由都只能纯读准备输入，不能预先消费 continuation admission、发布 capture start、
调用 provider 或写 route-attempt。任一路由超限会清理所有已准备资源并停止整个新 invocation；
成功准备后，真实 route 执行复核 request、原 Context、完整 continuation 和冻结 route list，
复用精确材料。未使用 route 的资源在成功、失败、异常及 Host 关闭路径统一清理。
`NativeCoderContinuation.preview` 复用全部 predecessor、claim、source、权限、inventory、预算与
receipt 校验，但不发布 `ContinuationAdmission`、不修改 `_prepared` 或 `_starts`；实际执行边界
才调用原 `prepare/started`，且返回 prose 必须与 preview 相等。

| 最终输入准备事实 | 结果 |
| --- | --- |
| sections 可装入但 wrapper/完整补丁/附件令最终输入超限 | 启动前 `ContextBudgetExceeded`，零 model start/provider，既有 `BUDGET_EXHAUSTED` 终局，不自动重试 |
| Task/Context/source/hash、candidate lineage 或读取权限不符 | 原 policy/scope 拒绝；不能改写为预算失败 |
| QA/Review 原生测试已结束，之后 model input 超限 | 保留 READY + FINISHED preparation receipt，不能宣称测试 NOT_STARTED |
| durable model start 已存在 | 原 replay/uncertainty，不新建假 stop，不重复准备或模型调用 |

最少验证：native/Responses 初始精确材料复用与 estimator 边界；完整 continuation 超限零 admission/
capture/model start；真实 Retry engine 预算终局与 durable journal 零 start/outcome；fallback 未用
资源/中途超限 cleanup；verifier FINISHED marker 与旧 start 的直接回放。

存量数据处置：此门禁只作用于尚无 durable start 的新执行，不修改历史 Task、Operation、审批、
lease、receipt 或 invocation journal。已经出现 start 无 outcome 的历史不能由本门禁自动恢复，
仍须原精确工程调查/处置流程；既有 terminal BUDGET 事实不重置或退款。回滚代码提交并在无角色
执行时重新构造 Host，所有原 immutable facts 保留。

可信 `prepare_verifier` 在真实 guard 下、durable **model invocation start 之前**打开精确 worktree、
读取当前 accepted artifact/Context、执行 registered capability，并缓存封存的 `VerificationEvidence`。
生产 Prompt provider 使用 `require_prepared=True`；准备说明没有任何 verdict。

缓存取得仍重读 Task、Plan/implementation、Context、原 claim/guard 和干净 candidate；受控 receipt
还复核 binding/admission 的当前事实。可以重复读取已封存结果，不重新 discovery 宿主或执行命令。
ordinary Responses 无注册命令时继续使用原严格受限 tool registry，并保存真实 tools evidence。

只有完整准备成功才缓存 ready；Native STARTED 无 final 永远是 EXECUTION_UNCERTAIN。

### Planner 可执行性与角色边界

新 Plan 在接纳前必须通过 `validate_plan_verification_entries()`，对每个命令确认测试入口、
精确 selector 和注册 capability；不能把未注册的 `node --test` 或缺少 Python/MySQL
capability 的 pytest 推迟到 Coder 领取后才暴露。旧 Plan 仍由 preflight 按原 bytes 兼容读取；
对于 Coder 领取，QA/Reviewer 的验证环境等待只封存 receipt/checkpoint，不阻止 Coder 产出候选。
QA/Reviewer 领取时仍必须通过同一 receipt 和真实 controlled preparation，缺失能力保持
`WAIT_ENGINEERING`，不能把 Coder 开始误报为 QA/Review 可执行。

`planned_new_files` 是候选可能新增的文件清单。若文件已存在于精确 `source_revision` 的
tracked tree，preflight 只要求角色读取权限，不要求 Coder 对该路径拥有新增写权限；仅对 source
中不存在的文件执行 Coder write-path 校验。
“模型未调用”不能证明“受控测试未执行”。纯 prerequisite 未满足、已结束的受控命令与执行未知须
生成各自的 claimed preparation 事实；具体恢复 collector 遵循工程等待契约。
新 claim/Run/Context 不能重用旧 claim 的 binding；新的真正执行在原候选和原角色预算内封存新记录，
不得退款、覆写原 receipt 或使用产品 bool 声称进程已停止。

`PreflightInvocationControl` 在任何受控准备动作前，先在当前真实 lease 的 write fence 内封存
`VerifierPreparationIntent`，包含完整原 request、Task snapshot、checkpoint、原 dispatch 和 lease。
namespace 为 `verifier-preparation-intents`，key 为 `workitem:checkpoint:original_dispatch`。
同一 WorkItem/checkpoint 的历史 intents 保留且取最新的原 dispatch；租约回收提升当前 dispatch
不代表旧准备没执行，也不自动建立新 intent。

准备返回后，gate 再将
`VerifierPreparationCheckpoint` 写到 sidecar `state/delivery-preflight/` 的
`verifier-preparations` namespace。immutable key 为 `checkpoint_sha256`；等待 evidence 为
`verifier-preparation://<checkpoint_sha256>`。记录包含原始完整 `AgentRequest` 及其 digest，
work item/lease、Task snapshot/checkpoint、candidate、Run、role/attempt、Context、READY/WAIT 和
typed failure。不是仅靠“模型 start 尚不存在”猜测尚未执行。
marker 还绑定 `intent_sha256`、原执行 `dispatch_sequence`/`lease_id`，与当前产生等待的
`wait_dispatch_sequence`/`wait_lease_id`。工程 collector 独立核验两份真实历史 claim。

read-only observer 只读原 Run 的 canonical native binding、STARTED/final receipt，验证原 claim、
request、admission、candidate、Context 和 linked digest。不执行 discovery、cleanup 或命令。
已经存在 durable model start 时，gate 首先走 invocation replay/uncertainty，禁止再进行准备。
准备中崩溃而无最终 marker 时，新 claim 仍通过旧 intent 观察原 Run。不得转到新 namespace
绕过原 STARTED。只有队列证明精确 `RESUME_UNINVOKED` resolution 已消费，当前前提 READY 且
完整原执行确为 NOT_STARTED，可信 `resumed_preparation` 才能许可在新 claim/Run/Context 封存
新的 intent。callback 不是产品 bool 或模型建议；旧 intent/claim/native bytes 永远保留。

| 封存原生执行事实 | 原角色恢复方式 |
| --- | --- |
| NOT_STARTED，无受控执行 start/final | 当前前提重检 READY、精确 marker/历史 claim 一致后 RESUME_UNINVOKED；保留 attempt，新 claim/Run/Context |
| FINISHED，成功或确定失败、linked STARTED/final，尚无 model start | RETRY_VERIFIER_PREPARATION；消耗冻结工作额度，新 attempt/claim/Run/Context，同原候选/角色 |
| STARTED 无 final、损坏记录、binding/lease/request/hash 漂移 | UNCERTAIN，工程调查，不重放命令或退款 |
| model start 已存在 | 原 invocation 结果重放或未知执行调查；preparation marker 不能覆盖这项事实 |

原生命令 timeout、启动失败或隔离资源故障不是 provider transient failure。不得构造虚假
`RetryFailure`、借临时故障额度重试或重复消费原 Run。工程调查重新读取 marker 及真实 native
receipts；marker 与当前事实漂移时拒绝。真实工程主体的精确 resolution 单独封存后消费队列。
成功 final 的 `native_failure_code` 保持 None，不虚构失败；等待中文说明为原验证准备已结束、
角色模型尚未启动、需重新领取独立验收。旧 claim 的成功准备不能冒充新 claim 的当前证据。

跨 route 的缓存包含普通工具模式。Responses 的普通权限不能用于 Codex fallback；同工具模式的
模型 fallback 可以引用同一原 Run 的封存验证证据。未知调用仍走工程调查，不假装无模型执行。

Dispatch 在 durable MODEL start 之前按完全有序 routes 集合逐一准备；实际执行必须比对同一集合。
factory 将 `route.to_wire()` 与有效 connection_mode 的摘要绑定到 registry；缓存只在实际相同
ordinary/registered 模式内复用原 Run 的封存受控 receipt，并另以 exact route digest 约束 ready。
同 registered 模式的 Responses/Codex 双向 fallback 不重执行受控命令；普通 Responses 权限
不得流入 Codex。unsupported fallback 在任何模型开始之前进入 typed WAIT，不能静默排除该
route、仅准备 primary 或把“同 kind”当成“同精确模型路由”。

## 同候选的验证 lineage

候选 SHA 不等于 implementation/QA/Review 产物身份。即使 Coder 只修订实施说明而不改变代码，
新的 implementation ID 也必须获得以该 ID 为直接 parent 的独立 QA；新 QA ID 必须再获得
以该 QA 为直接 parent 的独立 Review。历史 verdict 不能仅凭相同 source_revision 复用。
同候选重验传递原同角色 report 为只读输入，并精确约束 `supersedes`；它不会扩大任何角色的
verdict 写权限。`domain.agent.DELIVERY_ROLE_INPUTS` 是生产、Runtime 与权限校验的共享输入契约，
QA 包含历史 QA report，Reviewer 包含历史 Review report。不能只更新 retry 的输入而遗漏
definition/Context 的 allowlist，否则真实 ContextBuilder 会拒绝安全重验。
原 artifact、Run/Context/claim 和每轮否定理由保留；任务依然串行使用不同 Agent。

## 验证矩阵与增量命令

`tests/planning/test_joint_execution_window.py`：new intake、SIMPLE/COMPLEX、native projection、
window drift、旧 wire/hash、restart immutable。`test_execution_window.py`：精确 step partition/额度。

`tests/manager/test_delivery_preflight.py`：real Git/tool file、零命令执行、普通/受控 route、planned
file、deny paths、exact source、生产 backend 实际注册 discovery 的 typed 根因、普通工具不被
无关发现失败阻塞、旧 receipt digest。`test_python_verification_discovery.py`：host/最终 candidate 分层。

`tests/manager/test_native_verification.py`：原角色 admission、receipt reuse、不同角色/资源、
STARTED 无 final、cached current-fact 检查、dirty 保留、Responses/Codex route 隔离、factory preparation。
`tests/recovery/test_python_mysql_execution.py` 保持既有 recovery wrapper 的低层边界回归。
`tests/manager/test_verifier_preparation.py`：准备先于模型 start、完整 request/claim 绑定、真实
native timeout FINISHED、无 final UNCERTAIN、既有 model start 不重做准备、损坏记录不冒充未执行。
Coder preflight 尚未开始模型时须封存原 typed 根因并显示具体中文，产品摘要不拼接英文 reason_code。
三种准备崩溃状态均覆盖 dispatch 回收提升后新 claim/Run 不绕过原 intent。
`tests/manager/test_delivery_wait.py`：真实 marker/native store 的未开始、确定完成失败、未知、
事实漂移恢复边界和预算来源；collector 不能被假 receipt 替代。
`tests/orchestration/test_verification_lineage.py`：Review 驳回后同 SHA 的新实施、QA、Review ID
和直接 parent/supersedes；QA/Review 检查点重启不复用旧 verdict、不改写历史事实或跳过独立验收。
`tests/manager/test_verifier_route_preparation.py`：QA/Reviewer mixed route 双向准备/复用、
unsupported fallback 零模型调用、未准备的同 kind 路由和有序集合漂移拒绝。

`tests/manager/test_production_continuation_v2.py` public entries：source inspection 正向的多轮继续和
QA/Review 返工、missing controlled capability 的真实 claim 工程等待、registered Python 正向的
production facts reader/accepted artifacts/Context/同候选验收。MySQL 使用测试 DSN，模型与低层
外部服务用 ports fake；不宣称这些 fixtures 证明真实 OS/Docker/MySQL sandbox 已验收。

## 存量数据处置与回滚

无需改生产 SQL、重算旧 hash 或恢复 terminal Task。旧请求保持历史窗口/授权；新能力不得追溯添加。
非终态工程等待通过可信 investigation/精确 resolution 恢复，保留旧 claim、候选与执行记录。
已物理删除的需求保持删除。继续交付现有需求必须有用户明确授权，不能以验证平台为由新建生产需求。

回滚平台提交保留所有 sidecar records。已启动资源有固定 deadline；未启动过期 owned INTENT
只在显式受控执行/工程 cleanup 重新核验精确身份后清理。当前 native Run 的 reconciliation
不会自动遍历之前所有 Run；不能承诺旧 unstarted resources 已被自动全局清理。

## 模型前输入容量等待的原候选继续（2026-10-12）

`manager/capacity_input_reader.py::claimed_verifier_capacity(*, item, task, step,
prerequisites, state, queue, artifacts) -> VerifierPreparationEvidence` 只读校验当前
`CONTEXT_CAPACITY` 的 QA/Reviewer 工作项。`CapacityInputReader` 同时供历史 Coder
基线收集器使用；当前验证角色不得使用历史 marker 的宽限。

- `VerifierPreparationEvidence.context_capacity_receipt_sha256` 与
  `context_capacity_claim_sha256` 必须同时存在；缺省从 wire 省略以保持旧记录摘要。
  容量 proof 的 `budget_source/native_failure_code` 必须为 None，只允许
  `RESUME_UNINVOKED`。普通 FINISHED 准备仍使用 `frozen_work_attempt` 和独立重试规则。
- 当前工作项/Task/完整原 Task 快照、receipt、Context、原真实 claim、历史 queue step、
  原 claim 前的最新授权基线必须精确一致。原 verifier intent/checkpoint 必须唯一、READY，
  `observe_verifier_preparation` 的新鲜完整结果必须与其相同；成功 FINISHED 仍保留真实
  binding/start/finish 摘要。native 成功命令不是模型调用、QA PASS 或 Review APPROVE。
- no-start 必须扫描完整 invocation start/outcome、provider route、native capture
  start/stop/receipt/admission 和原始 ArtifactStore。所有目录禁止 symlink；已存在的匹配
  artifact/route JSON 必须是有界普通文件（每条最多 8,000,000 字节）并完成 typed/SHA/键校验。
  不存在目录可视为无记录，损坏、孤立、重复别名、非普通文件和无法读取均拒绝。
  容量收集不能使用 AcceptedArtifactStore 隐藏未接纳但已经封存的角色产出。
- same Run、same 原 Context 或 same 原 Lease 事实均否定未调用。当前 QA/Reviewer 对 same
  WorkItem 的任意调用事实拒绝。不同 Run/Context 不证明不同 claim：相关角色的完整 Context
  必须携真实 `source:execution.claim`，并与唯一完整调用 start 和队列 original claim 一致。
  历史 Coder marker 仅允许真实更晚、不同 Lease 的 dispatch/step/source 事实；不能把未知
  alias 当成之后的合法调用。旧独立 native 验证准备仍来自其自身 ledger，不被当成主模型 start。
- 调查与消费保留 Task worker lock、队列 authority 和 MySQL Task fence。SQL 再核对当前
  candidate/attempt/dispatch 和 proof 的唯一真实 claim，拒绝已有该 WorkItem 接纳产出。
  `preparation_resume_consumed` 必须找到两真实 CLAIMED 之间的 exact WAIT_RESOLVED 决定。
  继续只增加 dispatch sequence 并领取新 Lease/Run/Context；同 Task、WorkItem、candidate 和
  attempt 不变、不退款、不添加失败、不改原 READY/native 记录，不跳过独立 QA/Review。

| 场景 | 结果与断言 |
| --- | --- |
| READY + NOT_STARTED + 精确容量 receipt | 原候选 RESUME_UNINVOKED；新 claim，attempt 不变 |
| READY + 真实 FINISHED native 成功 + 模型未开始 | 同上；保留真实原命令，不制造失败或预算退款 |
| 原 READY 缺失、native finish 缺失/未知/失败/漂移 | 保留等待；不发布可消费继续决定 |
| start/outcome/native receipt/admission 为 alternate Run 但同原 claim | 拒绝，不因 Run 名称不同放行 |
| provider route 或未接纳 Artifact 为 alternate Context 但仍同原 claim | 完整 Context/claim 校验后拒绝 |
| raw Artifact 为 dangling symlink、目录、FIFO、超限文件 | 有界读取前拒绝；不把坏文件跳过成 absence |
| 两轮容量停止后继续 | 每轮独立真实 claim；原完整 receipt/READY 历史字节保持不变，最终独立 QA/Review |
| 旧普通 FINISHED verifier retry | 原 frozen_work_attempt 契约、旧 SHA 和原权限保持 |

执行回归为 `tests/manager/test_public_context_capacity_baseline.py`、
`tests/manager/test_public_verifier_capacity_resume.py`、
`tests/manager/test_verifier_capacity_input.py` 和
`tests/domain/test_delivery_resolution_schema.py`。Schema 入口包括 engineering wait、Console
与 stopped-budget settlement 的嵌入 proof；重新生成同样保留 capacity 与旧 provider/knowledge
守卫。公开用例使用隔离 MySQL 和 fake 模型/受控执行端口，不访问生产需求或生产数据库。

存量数据处置：无需迁移 SQL 或改写已有 Requirement/Task/Operation/READY/capacity 事实。
已封存完整容量 receipt 的非终态 QA/Review 在发布后先调查工程等待，再按精确证明继续原候选；
缺真实事实者保持等待，不补造历史。Coder 使用基线 PAUSE→RESUME 专门路径；旧终态容量任务
使用独立兼容恢复，不能由此将终态重置。回滚执行逻辑必须保留已发布的新字段只读兼容，
不得删除已保存 proof 或重写已消费决定。


## 2026-10-14 Coder 前提等待兼容与节点上限

生产入口与签名：

```python
multi_directory.planning.validate_plan_verification_entries(
    plan: JointExecutionPlan, *, max_pytest_selections: int = MAX_PYTEST_SELECTIONS
) -> None
multi_directory.planning.rejection_feedback(
    plan: JointExecutionPlan, reason: str, *,
    test_matrix_issues: tuple[PlanTestMatrixIssue, ...] | None = None,
    verification_issues: tuple[PlanVerificationIssue, ...] | None = None,
) -> JointPlanFeedback
manager.native_verification.exact_python_selections(
    requirements: tuple[PlannedVerificationRequirement, ...]
) -> tuple[PytestSelection, ...]
```

`MAX_PYTEST_SELECTIONS=64` 定义在独立 `python_verification_runner.py`；runner 使用
`-I -S -B` 启动，不能导入平台包或依赖平台环境。Pydantic、Console intent、recovery、原生
discovery、JSON Schema 和 runner 共同使用同一上限。仍限制 256 cases、32KB 私有配置和
3000-byte summary。增加 selector 上限不扩大网络、路径、命令或角色权限。

Planner 检查在接受新 Plan 前执行。`PlanVerificationFeasibilityError.issues` 使用从 1 开始的
`unit_index/package_index/test_index` 和固定 reason_code；不要回显模型生成 ID、argv 或 secret。
`JointPlanFeedback.reason_codes/required_changes` 给出可行动修正。COMPLEX Planner 只在原
冻结 `planner.max_attempts` 内继续；SIMPLE 或额度耗尽保留反馈并拒绝，无 Task 创建或退款。
selector 按仓库 unit 去重和计数，校验复用 `PytestSelection` 的精确 node 契约。

| 输入/事实 | 输出与断言 |
| --- | --- |
| 新 Plan 每仓库 33/64 个精确节点，显式 Python capability | 接纳；多仓库不合计为同一个 Task |
| 新 Plan 第 65 节点、file-only、路径穿越、不支持 flags | 固定 LIMIT/SELECTOR reason，有限 Planner 修正 |
| 新 Plan `node --test`、pytest 未声明 capability | 固定 UNSUPPORTED/REQUIRED reason；保留批准覆盖 |
| 旧 immutable Plan 精确 pytest 未声明 capability | 原生路线派生同一已注册能力；保留原 Plan bytes/digest；普通 Responses 仍用原受限 tools |
| `planned_new_files` 中路径已在精确 source tracked tree | 要求 verifier 可读；不要求 Coder 能重新创建已有文件 |
| 同路径 source 中不存在 | 要求 Coder 可写；deny paths 和 verifier 读权限依旧检查 |
| Coder 纯 preflight WAIT，模型尚未开始 | 封存 receipt/checkpoint 后允许实施；QA/Review 仍经真实准备门 |
| 旧 Coder ENVIRONMENT_UNAVAILABLE，有完整原 marker/claim、无 start/outcome | 独立重检并封存前提；允许精确 RESUME_UNINVOKED，即使 verifier 前提仍 WAIT |
| marker 缺失/Task 摘要漂移、模型有 start/outcome、QA/Review 前提 WAIT | 不适用 Coder 兼容；保留原工程调查/验证门 |

必须测试：`test_delivery_preflight` 同一 planned 路径已有/缺失与 Coder read-only；
`test_native_verification` 旧 33/64/65 节点及普通 Responses 不变；
`test_python_verification_runner` 真实独立解释器 33/64 节点有界错误汇总，65 节点零源码导入；
`test_delivery_wait` 精确未启动 claim 在新前提 READY/WAIT 两种状态保持 attempt 并精确消费；
`test_joint_planner_test_matrix` 1/3 次额度拒绝/修正且产品批准与 Design 不变；
`test_verification_schema_embedding` 三个公开 Schema 的 limit 与 runner 一致。

存量数据处置：不改 SQL、旧 Plan、旧 receipt 或 Task.base_ref。更新源码使用 Console
`propose_execution_baseline`（expected Task intent/revision/work item/source/checkpoint 与完整
目标 Git SHA），核对 plan facts/冲突/native rule change 后执行精确 digest；必要时先 PAUSE，
再 `resume_execution_baseline`。授权由平台封存，原 branch/worktree、批准、失败历史保留。
K1 使用执行时再次确认的最新 main SHA。旧 preflight 的原地恢复只消费有完整未启动证明的
`RESUME_UNINVOKED`；不能复活终态或补造 QA/Review。

回滚：停止新派发，等受控执行收尾，回退平台提交并受控重启；保留新 baseline/claim/receipt
只读兼容。新 baselines 不通过回退代码撤销；重新绑定源码必须提出新的精确计划并授权。
`generate-fault-retirement-schemas.py` 必须输出 canonical `$id`，避免全 Schema registry
在测试收集阶段因缺 ID 失败；这项元数据修复不改变历史 artifact payload/digest。
