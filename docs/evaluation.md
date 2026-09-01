# Evaluation 指标、ADR 与 Human Handoff

## 1. 为什么需要独立事件流

`StateEvent` 只记录 Orchestrator 的状态迁移，无法诚实回答“有没有人改代码”“policy 是否被
放宽”“非法输出出现了几次”“交付后有没有回归”。因此 T012 保留 StateEvent 的单一职责，
另建不可变 `EvaluationEvent` 流；评估输入是：

```text
Task snapshot + ordered StateEvents + sealed Artifacts + ordered EvaluationEvents
    → EvaluationTrace
    → EvaluationEngine
    → per-case assessment + aggregate metrics/ADR
```

汇总数字不是事实来源。任何 report 都可从同一 trace 重算。

## 2. Public API

```python
EvaluationEventStore.append(event: EvaluationEvent) -> EvaluationEvent
EvaluationEventStore.get(event_id: EvaluationEventId) -> EvaluationEvent
EvaluationEventStore.find(event_id: EvaluationEventId) -> EvaluationEvent | None
EvaluationEventStore.list_for_case(case_id: EvaluationCaseId) -> tuple[EvaluationEvent, ...]

EvaluatingAgentAdapter.run(request: AgentRequest) -> AgentResult
EvaluationTraceBuilder.build(case_id: EvaluationCaseId) -> EvaluationTrace
EvaluationEngine.evaluate(traces: tuple[EvaluationTrace, ...]) -> EvaluationReport

HandoffBuilder.build(task_id: TaskId) -> HandoffBundle
FileHandoffStore.put(bundle: HandoffBundle) -> HandoffRef
FileHandoffStore.get(handoff_id: HandoffId) -> HandoffBundle
```

四类 Evaluation event：

| kind | 关键字段 | 作用 |
|---|---|---|
| `case_started` | case/task/base/model/prompt/spec/tests/included | 冻结可比较的 case |
| `agent_run` | role/run/attempt/output status/artifact/policy counts/duration | 计算 run 与输出质量 |
| `human_action` | action/evidence URI/note | 区分允许动作与取消自治资格的干预 |
| `regression_check` | PASS/FAIL/window/evidence URI/hidden tests | 关闭交付观察窗口 |

`FileEvaluationEventStore` 每个事件保存一份 `event + canonical sha256` JSON 信封。相同 ID/正文
重放幂等；相同 ID/不同正文、合法字段篡改、损坏 JSON 或非法 lookup 都返回 typed error。

## 3. Autonomous Delivery Rate

在给定 evaluation 集合和窗口内：

```text
ADR = ELIGIBLE 的 DONE cases / 已启动且 included 的 cases
```

`ELIGIBLE` 必须同时满足：

1. StateEvent 从 `NEW` 到 `DONE`，最终事件引用有效 plan/implementation/QA/review 链；
2. implementation/QA/review 绑定同一 candidate，四个 producer run 独立；
3. `AgentRunEvent` 与四个 Artifact 的 role/run/artifact identity 完全一致；
4. QA `PASS`、Reviewer `APPROVE`，required criteria 都有 QA evidence；
5. 无改码、改测试、改 verdict、补 evidence、需求澄清或 policy override；
6. 无 uncaught policy violation；
7. `DONE` 后的最新 regression window 为 `PASS`。

结论有四态：

- `ELIGIBLE`：进入 ADR 分子；
- `PENDING`：交付链合格，但 regression window 尚未关闭；进入分母、不进入分子；
- `INELIGIBLE`：任一硬条件失败；
- `EXCLUDED`：case 明确 `included=false`，不进入分母。

人工只做 `START_TASK`、`VIEW_HANDOFF`、`MERGE_DELIVERY` 不降低 ADR。其他人工动作必须记录，
不能靠不记录来“优化”指标。

## 4. 可重算指标

| 指标 | 计算 |
|---|---|
| Task Completion Rate | DONE / started included cases |
| First-pass QA/Review Rate | 首个对应 run 在 attempt 1 产生 PASS/APPROVE / started cases |
| Artifact Validity Rate | VALID / (VALID + INVALID) Agent outputs；NOT_PRODUCED 不进分母 |
| Evidence Coverage | 有 PASS evidence 的 required criteria / required criteria |
| Median Cycle Time | PLANNING event 到 DONE event 的毫秒中位数 |
| Mean Attempts | 每 case 最大持久化 attempt 的平均值 |
| Regression Escape Rate | regression FAIL 的 DONE cases / DONE cases |
| Regression Observation Coverage | 已关闭窗口的 DONE cases / DONE cases |
| Human Escalation Rate | BLOCKED / started cases |
| Policy Violation Rate | 记录的 policy violations / Agent runs |
| ADR | ELIGIBLE / started included cases |

每个 `Rate` 同时保留 numerator、denominator、value；分母为 0 时 value 是 `null`，不伪造 0%。

## 5. 运行装配

```python
event_store = FileEvaluationEventStore(runtime_root / "evaluation-events")
event_store.append(case_started_event)

instrumented_agent = EvaluatingAgentAdapter(
    case_id=case_started_event.case_id,
    delegate=real_or_fake_agent,
    event_store=event_store,
)
runner = RetryingOrchestrator(
    repository=repository,
    artifact_store=artifact_store,
    context_builder=context_builder,
    agent_adapter=instrumented_agent,
    agent_definitions=agent_definitions,
)
runner.run_task(case_started_event.task_id)

trace = EvaluationTraceBuilder(
    repository=repository,
    artifact_store=artifact_store,
    event_store=event_store,
).build(case_started_event.case_id)
report = EvaluationEngine().evaluate((trace,))

bundle = HandoffBuilder(
    repository=repository,
    artifact_store=artifact_store,
).build(case_started_event.task_id)
handoff_ref = FileHandoffStore(runtime_root / "handoffs").put(bundle)
```

同一 Agent request replay 会复用确定性 evaluation event ID 和首次 `occurred_at`，不会重复计数。
回归窗口结束后追加 `RegressionCheckEvent`，重新 build trace/evaluate 即可把 `PENDING` 更新为
`ELIGIBLE` 或 `INELIGIBLE`；不修改旧 report 或旧事件。

## 6. Handoff 内容

`DONE` handoff 必须包含四制品链、candidate、QA/Review gate、逐 criterion evidence、changed
files、风险、事件 ID 和 tokenized Git review argv。`BLOCKED` handoff 包含最后 reason/
classification、已有 candidate/QA evidence、风险和安全下一步。`FileHandoffStore` 同时写
canonical JSON 与 deterministic Markdown；两者任一被篡改，读取 fail closed。

Handoff 只帮助人类复核、合并或决定如何解除阻塞。它不会执行 Git 命令、自动 merge、修改
verdict 或把终态 Task 原地重开。

## 7. v0.1 边界

- Evaluation event 和 handoff 当前使用文件端口；未来可替换 PostgreSQL/observability adapter，
  但 typed contract 和 replay 语义不变；
- runner 通过装饰后的 AgentAdapter 自动发 run 事件；human/regression 事实仍需可信外部执行器记录；
- v0.1 不提供在线 dashboard、分布式 tracing、自动隐藏测试平台或统计显著性分析；
- metrics 不得用于放宽 QA/Review/evidence 标准，任何未捕获的 policy violation 仍是发布阻断项。
