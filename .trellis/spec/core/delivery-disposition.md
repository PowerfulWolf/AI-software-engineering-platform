# Delivery disposition and recoverable waiting

## Scope and signatures

New Tasks freeze organization engineering authority. One deterministic decision contract is shared
by the execution router, Manager coordination and read projection. It supplements existing
specialized proof validators; a disposition never grants permissions or changes a verdict.

```python
decide_delivery_disposition(facts: DeliveryFailureFacts) -> DeliveryDisposition
DeliveryFailureControl.wait(task, classification, reason, source_revision, artifact_ids) -> None
WorkerLease.wait_for_delivery(disposition, *, now) -> None
queue.wait(..., disposition: DeliveryDisposition | None = None) -> QueuedWorkItem
queue.make_ready(..., expected_disposition_sha256: str | None = None) -> QueuedWorkItem
```

## Contracts

- Failure cause, preserved work, authorization and next action are different facts. Ordinary
  provider retry and QA/Review remediation use existing new-Run/budget/claim services.
- Required business decisions belong to product. Execution uncertainty, missing evidence,
  environment, source preparation and unsupported capability belong to engineering. Queue waiting
  records actual responsibility, a stable cause, exact input facts and a typed resume condition.
- A recoverable wait preserves Task phase/revision; its owner-fenced queue transition releases the
  Lease. No StageEvent or role verdict is fabricated. Only explicit termination, true policy
  violation or terminal budget exhaustion becomes BLOCKED.
- Unknown invocation is not free retry. No receipt/admission may be rebound merely because its
  Lease expired. Resumption requires a fresh, exact application-verified engineering resolution;
  new invocation consumes its frozen budget and new Run/Context/claim.
- Existing policy-less Task/queue bytes remain valid and do not gain authority. Durable old
  failure history is never rewritten. Text-only legacy waits retain their specialized validators.
- Product UI consumes the durable disposition; "engineering" does not claim an administrator or
  model is actively working without assignment/execution facts. Current phase, execution state,
  responsible duty and next action remain separate.

## Validation matrix

| Facts | Decision |
| --- | --- |
| Typed provider failure, eligible budget | Existing bounded retry, new identities |
| QA FAIL / Review REJECT, eligible work budget | Existing Coder remediation with exact findings |
| Business ambiguity | Product decision wait, lease released, checkpoint retained |
| Environment unavailable / required evidence missing | Engineering dependency wait |
| Required Context or final serialized role input exceeds frozen capacity | `CONTEXT_CAPACITY`, engineering dependency wait; role model has not started |
| Execution outcome or owned-process stop unknown | Engineering investigation wait, no invocation |
| True denied mutation / terminal budget exhaustion | Terminate with evidence and retained history |
| Wrong/foreign/stale resume signal or changed facts | Reject without queue/Task/model change |

Good: UI and Manager explain the same sealed waiting facts and a fresh verified signal resumes.
Base: legacy knowledge receipts retain exact scope/route/resolution checks.
Bad: UI hides a technical approval while backend still silently waits for product; or a free-text
message/Lease expiry resumes unknown native execution.

## Tests and rollout

Incremental domain, queue, native public entry, Manager and DOM regressions must cover exact
responsibility, nonterminal checkpoint, released lease, signal refusal and restart idempotency.
The two deleted K1 identities must remain retired; no production business work is started.
Retain new receipt/policy readers on rollback and deploy only while idle.

## 交付角色输入容量与调用前等待（2026-10-12）

### Scope / signatures

`RetryingOrchestrator.run_task` 将 trusted Context builder / final input preflight 抛出的
`ContextBudgetExceeded` 分类为 `RetryClassification.CONTEXT_CAPACITY`。
`DeliveryFailureFacts.classification` 的所有嵌入 Schema 保持同一可接受枚举。
`manager/delivery.py::_blocked_failure_code` 映射到
`DeliveryFailureCode.CONTEXT_CAPACITY`，原 Requirement checkpoint 的所有嵌入枚举
同步，兼容入口的终态不会被读成重试额度耗尽。

### Contracts

- 输入容量、工作额度、临时故障额度是三个事实。不得把 Context 容量拒绝标记成
  `BUDGET_EXHAUSTED`、供应商失败、业务 QA 失败或已运行的 Coder。
- 当前有 `EngineeringPolicy` 和 `DeliveryFailureControl` 的 IMPLEMENTING/QA/REVIEW
  Task，通过真实 claimed Worker 的既有 `wait_for_delivery` 进入 `WAITING_DEPENDENCY`，
  释放 Lease；Task 最近 checkpoint、attempt、retry_failures 和 accepted candidate 保留。
  无真实 claim 的兼容 Planner/旧入口不能伪造 queue wait，旧入口终态也保留准确分类。
- 本次角色模型尚未启动不代表历史执行停止。此分类不生成 `DeliveryInvocationStart`、
  native stop、provider route 或 verdict，不推断历史 Coder 输出，不退款。
  完整容量 receipt 和当前授权必须经专门恢复服务核验，disposition 本身不授权模型调用。
- 中文摘要说明“输入上下文超过配置容量”“本次交付角色的模型调用未启动”，处理方为
  ASE 工程，下一步核验完整输入/冻结容量。业务目标与验收标准不因此要求产品重新填写。

### Validation / error matrix

| 事实 | 结果 |
| --- | --- |
| Coder/QA/Reviewer 的 required Context 或 final input preflight 超限，真实工程 claim | 保留当前 checkpoint，工程依赖等待并释放 Lease，无当前角色调用 |
| 同样失败，旧无工程控制端口入口 | `BlockedResult.classification=CONTEXT_CAPACITY`，不冒充重试额度耗尽 |
| capacity wait 后再次运行，无精确恢复决定 | 保留原等待，不生成新 claim/run 或重复调用 |
| true work/transient budget exhaustion、供应商故障或验收否定 | 原有独立分类/预算/反馈行为不变 |

Good：当前 final input 未获容量接纳，工程等待保留 QA 候选和已完成 Coder。
Base：历史不含此枚举的 bytes/digest 不变。Bad：补造 invocation 让通用执行调查读取、
直接设置 Task=IMPLEMENTING，或声称容量分类本身证明旧进程已停止。

### Tests / 存量数据处置 / rollback

`tests/orchestration/test_context_capacity_wait.py` 覆盖三角色、两种输入边界和新旧入口；
`tests/domain/test_delivery_disposition.py` 覆盖额度事实独立及所有嵌入 Schema；
`tests/work_queue/test_worker_mysql.py::test_context_capacity_failure_waits_and_releases_real_claim_without_role_launch`
验证真实隔离 MySQL 的等待、释放 claim 和重读。只运行增量测试。

无生产 SQL、历史 event/Task/Operation 修改。已经封存为 BLOCKED 的 K1 不因该分类
自动重开；由专门 no-start recovery reader 核验完整 Context、保留补丁、当前 baseline
和 source facts 后，走精确方案、批准、新 successor claim 与独立 QA/Review。
新等待写入后回滚须保留该枚举兼容 reader；不能删除历史来绕过新契约。
