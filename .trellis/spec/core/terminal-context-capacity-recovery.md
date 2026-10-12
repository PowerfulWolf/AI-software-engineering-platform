# Legacy terminal Context capacity recovery

## Scope / Trigger

仅针对旧版本将 Coder 最终 Context 超限归为 terminal `BUDGET_EXHAUSTED` 的原需求。
已真实 claim、有 latest `coder_reapply` 基线、已落盘 Context，但该 attempt 无 invocation/capture/
provider-route 的场景与普通有原失败 Run 的恢复分开。首个 Planner Context 超限仍使用已有严格
pre-execution restart 契约；未来 no-start overflow 使用 owner-fenced nonterminal waiting。

## Signatures

```python
LegacyContextCapacitySourceReader.discover(scope: RecoveryScope) -> NativeRecoverySource
LegacyContextCapacitySourceReader.inspect(scope: RecoveryScope, receipt_sha256: str) -> NativeRecoverySource
validate_capacity_context(*, task: Task, context: ContextBundle,
    epoch: RecoveryBaselineEpoch, terminal_at: datetime) -> ValidatedCapacityContext
RecoverySource.context_capacity_receipt_sha256: StageSha256 | None
RecoverySource.failed_run_id: RunId | None
RecoveryPlan.context_capacity_input: ContextCapacityRecoveryInput | None
```

## Contracts

- ordinary Source 必须有真实 `failed_run_id`；仅 capacity receipt 源省略 Run 字段。普通非空字段
  wire/hash 保持不变，不能借此放宽 native route reader 或旧 terminal workspace stop 验证。
- 新 reader 使用现有 native dispatch、完整原审批链、完整 Project/Requirement 归属及基线 epoch
  校验；当前 Task、StateEvent 和 checkpoint 必须保持 original terminal identity。
- 原原因匹配完整 `BUDGET_EXHAUSTED: Required context exceeds the configured input budget; no automatic retry.`；
  checkpoint summary 去掉错误码前缀，不改写存量原因。
- Context 必须由 FileContextStore 完整校验，必须有唯一完整 baseline 与 execution.claim，
  `used_input_tokens > max_input_tokens - reserved_output_tokens`。不从新配置猜历史容量。
- latest baseline 必须经完整 FileExecutionBaselineStore 验证 authority、start、patch 与 native rules，
  并与 queue baseline consumption 及 Context 精确一致；原 claim 从 CLAIMED event 重建，不能从
  当前 CLOSED item 凭空恢复 claim；所有 searchable SQL columns 与 typed payload 保持一致。
- SQL 只做 consistent READ ONLY SELECT，finally rollback/close；无 ACTIVE claim、所有 item CLOSED、
  old Worker lock 空闲。完整扫描本次 attempt/work item 的 invocation-start/outcome、provider route、
  capture start/stop；旧 attempt 的真实历史可保留，不选择旧 route 冒充本次执行。
- receipt 的 `origin=legacy_terminal_context`、`observed_at=当前回溯时间`，`request=None`、
  `final_input_tokens=None`、`provider_started=False`。receipt 仅是可重验观察，不能充当历史 Run、
  stop/outcome、批准或工作预算退款。发现和 current gate 只读；公开 proposal 显式封存收据。
- clean actual `capture` 仍精确验证当前 worktree；历史开发内容保存在独立
  `context_capacity_input`，其 bytes/SHA 匹配最新 binding.retained_patch 与 store.complete_capture.patch。
  capacity 只支持 `coder_reapply`，不混入 workspace snapshot、scope supplement 或 quarantine。
- `recovery.patch` 是完整 required 旧补丁，不能截断、摘要或因当前 capture 为空而丢弃。Coder 从
  已批准干净目标基线重新适配，完整人工精确计划由原审批服务核验，新内部 Task 必须重新真实 claim；
  结果仍须独立 QA/Review，同一个原 Requirement 不重建。

## Validation & Error Matrix

| 输入 | 结果 |
| --- | --- |
| exact legacy Context + latest approved patch + ended claim + no start + closed queue | 准备精确恢复方案，等待人工批准 |
| old attempt 曾真实调用、本次没有启动 | 保留旧历史，允许继续验证本次 no-start |
| 本次任意 invocation/capture/route/outcome | 拒绝 capacity 分支，必须按真实运行事实处理 |
| baseline/queue/Context/claim/权限/目标 preparation 漂移 | 不接受计划或旧批准，保留原现场 |
| receipt 源缺完整 input 或伪造 failed Run | Python 与 Schema 入口拒绝 |
| 普通源无 Run | Python 与 Schema 入口拒绝 |
| 新方案未精确人工批准 | 不创建或运行 successor |

## Good / Base / Bad Cases

- Good：旧 K1 的 final Context 为 255325 tokens，历史可用输入为 252000，保留 clean worktree 和
  已封存完整旧补丁；新计划只引用这次回溯 observation，不创建 `run_capacity_*`。
- Base：普通 failed-Coder plan 仍携带原 Run，新增字段为空时序列化结果及摘要不变。
- Bad：选择早期失败 Run，生成假 request/stop，直接 reset terminal Task，或把 clean capture 当作
  “无开发进度”；这些都不能满足恢复批准前提。

## Tests Required

增量测试覆盖 required 完整补丁、legacy/no-run wire、普通 source 无 Run 拒绝、结构 Schema 负例、
真实 append-only start/outcome/route absence、只读 SQL/closure/claim/baseline/shadow columns、公开
scope→proposal routing、exact approval/new Task/no verdict bypass。原 pre-execution restart 和普通
terminal baseline Context 的缺原 invocation-start 负例必须继续拒绝。
