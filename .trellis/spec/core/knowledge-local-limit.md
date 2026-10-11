# Knowledge Preparation Local Execution Limit

## 1. Scope / Trigger

适用于已领取 Delivery Coder、QA 或 Reviewer 在主角色模型开始前，知识准备 native
调用达到 `local_execution_limit`，且已经保存完整原始调用、结果和独立实际停止记录。
此时保持原 Task 的交付 checkpoint，释放 Lease，把 WorkItem 置于工程等待；平台可以在
精确冻结授权和剩余工作额度内扩大下一次知识准备窗口。Product、Designer、Planner
的知识准备和未知中断不使用本契约。

该扩展不创建新需求、终态恢复 Task 或替代候选分支；不接纳草稿，不生成 QA/Review
结论，不跳过任一角色。有效 QA FAIL / Review REJECT 继续按原 findings 回到 Coder。

## 2. Signatures

```python
# knowledge/invocation.py
class KnowledgePreparationLocalLimit(StructuredModelError):
    outcome: KnowledgeInvocationOutcome

# knowledge/preparation_retry.py
def claim_identity_sha256(claim: QueueClaim) -> str: ...
def read_local_limit(records_root: Path, outcome_sha256: str) -> KnowledgeInvocationOutcome: ...
def preparation_retry_evidence(
    *, outcome: KnowledgeInvocationOutcome, task: Task, item: QueuedWorkItem,
    source_revision: str, scope: EngineeringScope, historical_claim: QueueClaim,
    previous: KnowledgePreparationRetryEvidence | None,
    delivery_requirement_id: str | None = None,
) -> KnowledgePreparationRetryEvidence: ...

# knowledge/legacy_scope.py
def legacy_delivery_gaps(
    records: KnowledgeRecordStore, *, task_id: str, role: TeamRole,
    team_id: str, project_id: str, repository_id: str, source_revision: str,
) -> tuple[KnowledgeGap, ...]: ...
def require_delivery_requirement_scope(
    binding: KnowledgeRunBinding, expected_requirement_id: str,
    *, records: KnowledgeRecordStore,
) -> None: ...

# work_queue/execution_store.py, MySqlRoleQueue
def knowledge_preparation_retry(
    self, work_item_id: str, *, _depth: int = 0,
) -> KnowledgePreparationRetryEvidence | None: ...
def knowledge_timeout(self, task: Task, claim: QueueClaim) -> int | None: ...
def resolve_wait(self, resolution: DeliveryResolution) -> QueuedWorkItem: ...
```

`KnowledgeRunContextBuilder` 接收
`invocation_timeout: Callable[[Task, QueueClaim], int | None] | None`。
`DeliveryWaitService` 接收 `knowledge_requirement_id: str | None` 和
`knowledge_retry: Callable[[str], KnowledgePreparationRetryEvidence | None] | None`。
生产 backend 注入当前真实 `queue.knowledge_timeout`，Host 在同 Task idle/process lock
内读取已消费窗口。不存在 claim 时拒绝 timeout override，不能拿未领取的计划身份调用模型。

## 3. Contracts

### 独立调用记录与等待身份

- `KnowledgeInvocationJournal` 首先记录精确 intent，再封存每个 route admission 与其独立
  completion；完整 `FAILED / TIMEOUT / local_execution_limit` outcome 才抛 typed error。
  `with_context` 和服务重开 replay 必须保留该子类型及同一 outcome。
- 已封存的 local-limit intent 在知识 runs 根目录增加
  `knowledge-local-limit-intents[outcome_sha256]` 索引。它只帮助按 SHA 定位；collector 仍
  独立重读 lane intent、outcome、全部 execution records，并核验各自摘要/归属。
  索引写失败返回 uncertain，保留原 outcome 和实际 STOP；重放可幂等补索引，不能重启原调用。
- 至少一个真实 `StructuredNativeStopReceipt`，最后一个 native STOP 的 kind 必须为
  `local_execution_limit`；所有 admission 均已有 completion。仅 NOT_STARTED、HTTP 超时、
  pending、丢失 owner/STOP 或当前仍存活的原 process group 不满足。PID/group 复用导致
  当前活跃也保守拒绝，不能把旧 receipt 当成杀停现进程的权限。
- Failure router 写 `KNOWLEDGE_PREPARATION_LIMIT` 与唯一
  `knowledge-preparation://<outcome_sha256>`；不在旧 claim 内循环，也不消费或退款 provider
  transient。旧无 engineering policy 的 Task 同样保留非终态等待。
- `KnowledgePreparationRetryEvidence` 精确绑定 scope、Task、role、WorkItem、原 lease、
  claim SHA、attempt、dispatch/checkpoint sequence、Run/Context、source、snapshot、phase、
  intent/outcome/request SHA 及全部独立 execution-record SHA。claim SHA 包含完整 immutable
  WorkItem、Assignment、Lease、ModelSelection、worker 和 claimed_at；只排除队列状态/
  心跳 expiry 等 mutable 字段，`repository_scopes` 不得排除。
- 原主角色 invocation start/outcome 或接纳 artifact 已存在时不得执行本续跑。

### 冻结窗口、权限与原子消费

首次 exact intent 的 `timeout_seconds` 为 `initial_timeout_seconds`。第 1、2 次扩窗分别为
`min(initial * 2, 86400)`、`min(initial * 4, 86400)`；maximum 为
`min(initial * 4, 86400)`，next 必须大于 current。最多两次扩窗，提前触顶也结束。
后续窗口只从已消费 `WAIT_RESOLVED` 的完整 resolution 读取，不重算当前设置。

同 role/checkpoint/source 的普通 provider successor 保留已消费窗口与扩窗次数；role、
checkpoint 或 source 改变后属于新的工作 slice。每个 parent 只按精确 next WorkItem ID
查询至多两条 `WAIT_RESOLVED`，重复记录拒绝，祖先读取深度至多 512；不能扫描全部事件、
只读最新任意决定或遇到非知识后继就重置窗口。

新 Task 有冻结的 `EngineeringCapability.DELIVERY_WAIT_RESOLUTION` 才可自动工程决定。
旧 Task 没有该 policy/capability 时，只允许真实工程主体审批 exact proof；不追溯添加
权限。resolve 再采集 proof 并逐字段比对，MySQL fence 重查 Task snapshot/revision/intent、
source/step、当前 WAITING、原 claim 和已消费窗口链；Task 有任一 ACTIVE claim 则拒绝。

一次消费增加同 Task 的共享冻结 work attempt，关闭旧 WorkItem，创建
`work_<resolution_sha256>`、新 step、真实新 claim、Run/Context。原 Task/status/source、
候选和保留 worktree 不变；不改 `retry_failures`，不退款。重放返回同一新 WorkItem，
不重复扣额度。工作预算耗尽或窗口触顶时保留历史和等待，不提供必败的继续动作。

### 知识 scope 与交付 Requirement

`requirement_id` 保留原知识 binding scope；可选 `delivery_requirement_id` 是 collector
验证后的当前 native 所属 Requirement。通常两者一致。旧 `task_continue_*` QA/Reviewer
可能已有以 Task ID 为 scope 的 gap，runtime 会保留它；不能为了 UI 把旧知识归属改父 ID。

共享 `require_delivery_requirement_scope` 只允许常规 exact Requirement，或同
Task/team/project/repository/role/source/snapshot 的真实 legacy gap。legacy 分支最多读取
512 个 gap，逐条校验完整摘要及独立 `gap_id` store key，独立重读 snapshot 并核验 scope。
仅 continuation 形状的名称不足以授权。调用者必须另用已验证 native binding 证明 Task
属于预期父 Requirement；helper 本身不发明该关系。

previous window 按 `delivery_requirement_id or requirement_id` 校验交付身份，保留旧 None
的常规兼容。`team_view.engineering_history` 的 `delivery_requirement_id` keyword 只传递
知识交付的父身份，原 preflight/native history 的 Requirement scope 保持其精确旧值。
前端消费 server 已证明、摘要覆盖的双身份，不能凭 Task 命名推断父关系。

新增 evidence 及 investigation/resolution optional 字段 None 时使用 `Field(exclude_if=...)`
从嵌套 wire 排除；不改变旧 Console/handling bytes、digest、store key。

## 4. Validation & Error Matrix

| 输入/事实 | 检测边界 | 结果 |
|---|---|---|
| 完整 native local limit，主角色未开始，剩余额度/授权满足 | collector + resolution + queue fence | 同 Task 新 claim 有界扩窗 |
| pending、缺独立 receipt、owner loss、NOT_STARTED-only | journal/read_local_limit | 保留现场，未知状态不获续跑 |
| main start/outcome/accepted artifact 已存在 | collector | 不冒充知识准备未开始 |
| claim、仓库范围、source、requirement 或 proof 漂移 | collector + resolve 再核验 | 拒绝消费，attempt 不变 |
| 旧 Task 缺冻结工程 capability | EngineeringAuthority | 需 exact 工程主体决定，不添加 policy |
| work attempt 耗尽 | investigation + queue | BUDGET_EXHAUSTED，无可消费动作 |
| 第三次扩窗或 current 已到 max | evidence/collector | KNOWLEDGE_WINDOW_EXHAUSTED，无可消费动作 |
| provider successor 介于两次知识 timeout 之间 | consumed-window resolver | 保留之前窗口及工作记账 |
| 只有 Task 名称、错 legacy scope 或缺 snapshot/gap key | shared scope resolver | 不放宽知识/交付身份 |
| 索引写失败但 outcome/STOP 完整 | journal | uncertain，重放仅补 index，不重启模型 |

## 5. Good / Base / Bad Cases

- **Good**：真实 1 秒 native timeout 封存停止结果，自动工程 admission 在原 Task 消费一次
  工作额度，下一真实 claim 使用 2 秒。再次 timeout 后最多 4 秒；第三次无可用扩窗。
- **Base**：旧 Task 无工程 capability，页面显示“让平台处理知识准备”及精确检查结果，
  工程主体确认 proof 后继续同一 Task；scope 和源代码进度均保留。
- **Bad**：把所有 provider timeout 当本地停止，热配置改大时间，在旧 lease 内重试，
  重置 source/Task/branch，或把 Task ID 知识 scope 静默写成父 Requirement。

## 6. Tests Required

- `tests/knowledge/test_invocation_native.py`：真实七角色 timeout/非零/invalid receipts、
  typed 首次/replay、索引发布失败后独立 stop/outcome 保留且不重启/不 fallback。
- `tests/knowledge/test_delivery_context.py`：timeout 从当前 actual claim 解析，两阶段
  使用消费窗口，缺 claim 在模型开始前拒绝。
- `tests/knowledge/test_delivery_requirement_scope.py` 与旧 legacy continuation cases：
  QA/Reviewer 同 scope 新 Run 允许；错 Task/role/team/project/repository/source/snapshot、
  独立 gap key 漂移、缺 snapshot 和无父归属证据拒绝。
- `tests/work_queue/test_knowledge_preparation_retry_mysql.py`：真实 native stop → failure
  router → durable wait → exact resolution → fresh Dispatcher/MySQL claim；断言同 Task/
  source/dirty worktree 保留、额度不双扣/不退款、两次封顶、policy-less 人工边界、
  main-start/receipt/scope/proof 反例，以及 legacy QA/Reviewer 双身份真实消费。
- `tests/work_queue/test_wait_resolution_mysql.py`：旧等待处置、exact authority 与重放回归。
- `tests/domain/test_knowledge_preparation_retry_schema.py`：模型/Schema 正反例、有限窗口、
  双身份与 None 嵌套序列化；生成器不得抹掉既有 Console baseline `allOf` 安全约束。

仅增量测试使用 `ASE_TEST_MYSQL_DSN` 隔离测试库，不连接生产库；测试 reset 不得并发。

## 7. Wrong vs Correct

**Wrong**：读取最新服务 timeout，给相同 Run/lease 再调一次模型；主调用是否开始未知时
清空工作区；UI 看到 `task_continue_` 就接纳父 Requirement。

**Correct**：先重读完整原 journal、真实停止及 exact native 归属，再记录 immutable
engineering proof/resolution；队列原子消费冻结窗口和工作额度，新 claim 才重新进行知识
准备。旧 Task 没有 capability 则等待精确工程决定，代码或模型文案不能代替权限。

## 8. 存量数据处置与回滚

无需改库、退款、重新建需求或补造旧停止事实。完整已封存 local-limit journal 的现有非终态
Task，在执行空闲后装载新版本，通过需求详情“让平台处理知识准备”重新调查；若自动授权
完整则平台记录有界处理，否则工程主体批准页面列出的 exact 决定，再继续原需求。

旧缺 journal/pending/STOP/原 claim 的记录继续显示缺失事实；本补丁不为其追溯生成 receipt，
不重开终态 Task。恢复历史、草稿、旧失败及人工决定全部保留。

部署前等当前受控执行完成；不为了装载本补丁中断正在运行的 Coder/QA/Reviewer。
回滚需保留新增 typed resolution/evidence readers 和 Schema。已消费决定不能交给拒绝新
类型的旧版写端，也不能删 `WAIT_RESOLVED` 或手改 attempts；应停止新派发、保留现场，
重新装载能够读取该版本契约的发布，再按公开工程等待入口继续。
