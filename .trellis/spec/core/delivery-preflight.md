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
inspect_delivery_prerequisites(..., controlled_capabilities=(), source_revision=None) -> DeliveryPreflightReceipt
RegisteredNativePythonVerifier.discover(task, plan, scope, source_revision=None) -> tuple[DiscoveredControlledCapability, ...]
DispatchDeliveryAgentAdapter.prepare_verifier(request: AgentRequest) -> None
ConfiguredDeliveryRouteAdapterFactory.prepare_verifier(*, request, route, binding) -> None
RegisteredNativePythonVerifier.prepare_verifier(*, request, workspace_root, guard, allow_ordinary_commands=False) -> None
NativePythonVerificationEvidence.validate_current(request, workspace_root, execution_guard=None) -> None
RegisteredNativePythonVerifier.observe_verifier_preparation(request, lease_id) -> VerifierPreparationObservation
observe_verifier_preparation(*, repository_workspace_root, request, lease_id) -> VerifierPreparationObservation
PreflightInvocationControl(..., prepare_verifier=None, observe_verifier=None)
PreflightInvocationControl(..., resumed_preparation: Callable[[VerifierPreparationIntent, QueueClaim], bool] | None)
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
| 全量目录、裸 pytest、inline interpreter、越权入口/路径或未注册能力 | WAIT_ENGINEERING，Coder 零调用 |
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
gate 的产品原因由枚举转换为具体中文；reason_code、原枚举值、hash 只保留在技术证据中。

## 原角色内的受控 Python 验证

- exact pytest function/class-method nodes，最多 32 个；支持 `pytest`、`python[3] -m pytest`、
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

可信 `prepare_verifier` 在真实 guard 下、durable **model invocation start 之前**打开精确 worktree、
读取当前 accepted artifact/Context、执行 registered capability，并缓存封存的 `VerificationEvidence`。
生产 Prompt provider 使用 `require_prepared=True`；准备说明没有任何 verdict。

缓存取得仍重读 Task、Plan/implementation、Context、原 claim/guard 和干净 candidate；受控 receipt
还复核 binding/admission 的当前事实。可以重复读取已封存结果，不重新 discovery 宿主或执行命令。
ordinary Responses 无注册命令时继续使用原严格受限 tool registry，并保存真实 tools evidence。

只有完整准备成功才缓存 ready；Native STARTED 无 final 永远是 EXECUTION_UNCERTAIN。
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
两个已删除 K1 保持删除，暂停业务交付时不得为了验证新建生产需求或调用业务模型。

回滚平台提交保留所有 sidecar records。已启动资源有固定 deadline；未启动过期 owned INTENT
只在显式受控执行/工程 cleanup 重新核验精确身份后清理。当前 native Run 的 reconciliation
不会自动遍历之前所有 Run；不能承诺旧 unstarted resources 已被自动全局清理。
