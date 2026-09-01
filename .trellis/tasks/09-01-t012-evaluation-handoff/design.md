# T012 设计

## Data flow

```text
TaskRepository ─┐
ArtifactStore ──┼─> EvaluationTraceBuilder ─> EvaluationTrace ─> EvaluationEngine
EvaluationEvents┘                                             └> case + aggregate metrics

TaskRepository ─┐
ArtifactStore ──┴─> HandoffBuilder ─> HandoffBundle ─> FileHandoffStore (.json + .md)
```

## Public seams

```python
EvaluationEventStore.append(event: EvaluationEvent) -> EvaluationEvent
EvaluationEventStore.list_for_case(case_id: EvaluationCaseId) -> tuple[EvaluationEvent, ...]
EvaluationTraceBuilder.build(case_id: EvaluationCaseId) -> EvaluationTrace
EvaluationEngine.evaluate(traces: tuple[EvaluationTrace, ...]) -> EvaluationReport
HandoffBuilder.build(task_id: TaskId) -> HandoffBundle
FileHandoffStore.put(bundle: HandoffBundle) -> HandoffRef
FileHandoffStore.get(bundle_id: HandoffId) -> HandoffBundle
```

## Evaluation facts

- `CaseStartedEvent` 固定 case/task/base/model/prompt/spec/test entrypoints 和是否纳入评估；
- `AgentRunEvent` 记录 role/run/attempt/output validity/policy violation 数；
- `HumanActionEvent` 用枚举区分允许的启动/查看/合并，与会取消自治资格的澄清/改码/改测试/
  改 verdict/补 evidence/放宽 policy；
- `RegressionCheckEvent` 明确观察窗口 `PASS/FAIL` 和 evidence URI。

StateEvent 继续只拥有状态迁移；EvaluationEvent 不得改变 Task。两类事件由 trace 按时间和 ID
稳定组合，metric 不读取聊天历史或可变进程内计数器。

## ADR policy

分母是有唯一 `CaseStartedEvent`、`included=true` 且已有 `NEW→PLANNING` 的 case。分子必须：

1. Task 与最终 StateEvent 都是 `DONE`；
2. DONE event 引用有效 plan → implementation → QA → review 链；
3. QA `PASS`、Review `APPROVE`、candidate revision 一致、run ID 独立；
4. required acceptance criteria 均有 QA evidence，所有 Artifact 已 sealing；
5. 无 disqualifying human action、policy override 或 uncaught policy violation；
6. 至少一个覆盖交付后的 regression check 且最新结果为 PASS。

已交付但观察窗口未结束是 `PENDING`；明确失败条件是 `INELIGIBLE`。ADR rate 对 pending 保守地
按 0 计入分母，并单独暴露 pending 数。

## Handoff identity

`handoff_id = handoff_ + sha256(canonical bundle without handoff_id/generated_at)`。
`generated_at` 是首次观察时间，不参与 identity。等价重建保留首次值；冲突/篡改 fail closed。
Markdown 由 typed bundle 确定性渲染，不接受 Agent 自由文本模板或 shell 命令。
