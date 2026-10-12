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
validate_legacy_capacity_pre_candidate_sources(task: Task,
    events: tuple[StateEvent, ...], epochs: tuple[RecoveryBaselineEpoch, ...]) -> None
ContextCapacityReceipt.legacy_terminal_event_sha256: Sha256 | None
ContextCapacityReceipt.legacy_terminal_source_revision: NonEmptyStr | None
```

## Contracts

- ordinary Source 必须有真实 `failed_run_id`；仅 capacity receipt 源省略 Run 字段。普通非空字段
  wire/hash 保持不变，不能借此放宽 native route reader 或旧 terminal workspace stop 验证。
- capacity Source 的 `execution_baseline_sha256` 和 `execution_base_revision` 必须同时存在且非 null；
  Python 与 `delivery-recovery.schema.json` 的 Source/Plan 条件约束一致，不能仅用 `required` 声明
  nullable 属性。同步脚本只替换上一版容量条件，不删改普通源和历史 Schema guard。
- 新 reader 使用现有 native dispatch、完整原审批链、完整 Project/Requirement 归属及基线 epoch
  校验；当前 Task、StateEvent 和 checkpoint 必须保持 original terminal identity。
- 原原因匹配完整 `BUDGET_EXHAUSTED: Required context exceeds the configured input budget; no automatic retry.`；
  checkpoint summary 去掉错误码前缀，不改写存量原因。
- 旧版本还有终态事件错误写 `Task.base_ref` 的问题。只在容量专用 Native reader 的纯校验 seam
  接受最后的 exact legacy `IMPLEMENTING → BLOCKED`、同 Task/attempt 的该
  已知错源；普通 Native reader 保持原严格校验。全部 earlier source、epoch 前后关系、revision、
  minimum attempt、时间仍按原 validator 检查，任意第三个 revision 都拒绝。
  回溯 receipt 同时保存原事件全文 digest/原 source 与完整 Context 的真实 input source；原事件
  字节保留，不能补造一个“正确 source”的旧事件。两个 legacy 字段成对出现，`final_input`
  receipt 禁止这两个事实；None 从 wire/digest 省略，旧正常收据摘要不变。
- terminal artifact IDs 只能为空或与唯一原 `plan_validated` event 中的单个 Plan ID 完全一致。
  专用 reader 另从只读 Artifact/Context store 验证真正 sealed `PlanArtifact` 的 Task、原 source、
  ORCHESTRATOR Context/attempt，并绑定 queue admission receipt 或 accepted publication 的
  SHA/Run/Context/source。原 seed Plan 的 created_at 可早于实时 planning Context；两者分别
  不能晚于原 plan_validated event，不猜新的历史模型调用或改原时间。
- Context 必须由 FileContextStore 完整校验，必须有唯一完整 baseline 与 execution.claim，
  `used_input_tokens > max_input_tokens - reserved_output_tokens`。不从新配置猜历史容量。
- latest baseline 必须经完整 FileExecutionBaselineStore 验证 authority、start、patch 与 native rules，
  并与 queue baseline consumption 及 Context 精确一致；原 claim 从 CLAIMED event 重建，不能从
  当前 CLOSED item 凭空恢复 claim；所有 searchable SQL columns 与 typed payload 保持一致。
- SQL 只做 consistent READ ONLY SELECT，finally rollback/close；无 ACTIVE claim、所有 item CLOSED、
  old Worker lock 空闲。完整扫描本次 attempt/work item 的 invocation-start/outcome、provider route、
  capture start/stop；旧 attempt 的真实历史可保留，不选择旧 route 冒充本次执行。
- no-start 还要求 `FileArtifactStore(read_only=True)` 没有本次或未来 Coder 产物，即使它未被队列
  接纳也不能忽略。产物 envelope 没有 attempt，必须从它引用的完整 `FileContextStore` Context
  核验 Task/role/attempt，不能根据 Run ID 字符串猜测。continuation ledger 的 receipts/admissions
  也必须完整 typed 读取并拒绝本次/未来或 claim 别名；损坏 ledger 拒绝，早期完整历史保留。
- receipt 的 `origin=legacy_terminal_context`、`observed_at=当前回溯时间`，`request=None`、
  `final_input_tokens=None`、`provider_started=False`。receipt 仅是可重验观察，不能充当历史 Run、
  stop/outcome、批准或工作预算退款。发现和 current gate 只读；公开 proposal 显式封存收据。
- 当前 checkout 存在时，clean actual `capture` 仍精确验证当前 worktree；历史开发内容保存在独立
  `context_capacity_input`，其 bytes/SHA 匹配最新 binding.retained_patch 与 store.complete_capture.patch。
  capacity 只支持 `coder_reapply`，不混入 workspace snapshot、scope supplement 或 quarantine。
- 正常 cleanup 可移除本次未调用的 clean checkout。discover 只能使用
  `GitWorktreeManager.require_clean_coder(spec)` 只读证明 exact baseline path/branch/source 与
  manager-owned clean-removal marker，不补造 absent checkout 的 capture。缺 marker、错误路径、
  branch/SHA 漂移或现有 dirty checkout 都拒绝。公开 proposal 复用已有
  `restore_clean_coder(spec)` 有界重建同一合法已清理 checkout，再做真实空 capture；不建新需求、
  不执行模型、不补旧 Run。新内部 Task 仍须精确人工批准，完整旧补丁仍由 required Context 传递。
- `recovery.patch` 是完整 required 旧补丁，不能截断、摘要或因当前 capture 为空而丢弃。Coder 从
  已批准干净目标基线重新适配，完整人工精确计划由原审批服务核验，新内部 Task 必须重新真实 claim；
  结果仍须独立 QA/Review，同一个原 Requirement 不重建。

## Validation & Error Matrix

| 输入 | 结果 |
| --- | --- |
| exact legacy Context + latest approved patch + ended claim + no start + closed queue | 准备精确恢复方案，等待人工批准 |
| old attempt 曾真实调用、本次没有启动 | 保留旧历史，允许继续验证本次 no-start |
| 本次任意 invocation/capture/route/outcome | 拒绝 capacity 分支，必须按真实运行事实处理 |
| 本次/未来 Coder 产物、receipt/admission 或 claim 别名 | 拒绝 no-start，保留真实结果和现场 |
| 原 clean checkout 合法移除，精确 semantic branch/source/removal marker 验证通过 | discover 只读验证；公开 proposal 有界恢复同一 checkout 后实际 capture |
| checkout 无可信清理 marker、path/branch/SHA 漂移或现有 dirty | 拒绝准备，不猜空补丁或清空旧现场 |
| 唯一最后 exact legacy capacity 事件误写 Task.base_ref，完整 Context 独立核验通过 | 保留旧事件，收据同时绑定旧错源和真实输入源 |
| earlier 错源、第三来源、任意别的 reason/状态/attempt 或 epoch 时间不符 | 拒绝所有容量兼容；普通 reader 始终原严格 |
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
Schema/Python 双层覆盖 nullable baseline 和 legacy receipt 字段配对；Native SQL fake 验证专用
hook 接受唯一旧错误、普通 source gate 仍拒绝。只读完整 artifact Context、孤立 continuation
receipt/admission、损坏 ledger、早期历史保留都有真实 file store 正反例。
真实 Git fixture 覆盖合法 clean removal、缺 marker、symlink marker、branch/source/path 漂移、
existing dirty 拒绝；source discovery 不重建目录，公开 proposal Git seam 只恢复同一 clean checkout。
