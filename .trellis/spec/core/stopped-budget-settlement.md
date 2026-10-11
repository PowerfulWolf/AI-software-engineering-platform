# Stopped exhausted failure settlement

## Scope

旧版本可能把 `transient=false` 的 provider failure 标成 `TRANSIENT_INFRA`，按临时额度保持等待，即使真实普通工作额度已耗尽。新分类路由修正不追溯改写旧 disposition、错误或 retry 账。

## Signatures

- `DeliveryWaitService.handle(HandleDeliveryWait) -> DeliveryWaitHandling`：公开原等待的确定性处理；INSPECT 仍只读。
- `StoppedBudgetSettlementService.try_settle(command, task, item, step, proof, guard)`：只接受原 Coder 的已停止、非临时、无产出失败与普通额度耗尽。
- `MySqlRoleQueue.settle_stopped_budget(cursor, StoppedFailureBudgetSettlement)`：调用方持独占 Task lock；同一个 idle authority/Task/claims transaction 追加合法 StateEvent、Task snapshot 和 CLOSED work item。
- `MySqlRoleQueue.retired_rejected_outputs(task_id, *, cursor=None) -> tuple[RejectedCoderOutputEvidence, ...]`：复用已消费 `WAIT_RESOLVED` 的 typed resolution/digest 校验；事务内必须复用当前 cursor。
- `is_retired_rejected_publication(publication, retired, *, current_work_item_id, current_run_id, checkpoint_sequence) -> bool`：只识别精确已消费退役的历史 publication。
- `DeliveryWaitHandling.budget_settlement_sha256: SHA256 | None`：None 不进入旧 wire/hash；非空仅允许 `BUDGET_EXHAUSTED`、无 resolution、无 collection failure，不授予新执行。

## Contracts

1. 校验原 invocation/start/outcome、完整历史 claim、capture start、真实 failed stop、原 Task intent/source/context/revision、停止的当前进程归属。失败 `transient=false`，无 artifact、无 output、cause=None，停止错误与原失败一致。
2. 唯一未关闭工作项；无 ACTIVE claim、无当前 work/Run 产出、无真正后继 checkpoint 的 accepted artifact。同 checkpoint 历史 publication 只有精确匹配已消费 `RETRY_REJECTED_CODER_OUTPUT` evidence 才可排除：task/work/lease/dispatch/checkpoint/run/context/source/artifact ID/SHA 全部相等。`AcceptedRoleArtifact.checkpoint_sequence` 是发布 claim 的输入 checkpoint，多个执行可共享它；不能把 `>=` 机械改为 `>`，不能按 attempt 小、source 不同、旧时间、已退役 ID 集合或 supersedes 祖先泛化放行。普通工作额度按冻结 Task 的真实账核验，不能从旧错误 disposition 的 `budget_available` 推断。
3. 当前 worktree HEAD/branch/owner 与原调用一致，完整 inventory 必须等于原 start，包括 ignored 文件及 modes。完整合法 mutation capture 独立封存，补丁正文不能只剩摘要。
4. 先封存收尾决定及 replay 记录；同事务用纯 state-machine reducer 形成 `IMPLEMENTING -> BLOCKED`。不调用模型、不新建 claim、Run、Assignment、candidate 或 verdict，不退款、不复活 Task、不新建 Requirement。
5. SQL commit 成功后才发布普通 `wait-handlings` 报告。崩溃前重查完整原事实；崩溃后核验精确 terminal Task/event/CLOSED item 与唯一 queue settlement event。重入零重复 event，审计前缀保留。
6. Host 只通过既有 resume seam 同步真实 terminal cursor；之后仍须同 Requirement 的 RecoveryPlan 与精确批准，不能以收尾代替恢复批准。

## Validation matrix

| Input | Outcome |
|---|---|
| Real permanent failure, owned failed stop, complete unchanged lawful draft, exhausted ordinary budget | End old Task and close unique waiting item atomically; retain requirement and draft |
| Same input checkpoint old progress, exact consumed typed rejected-output retirement | Exclude only the exact retired publication; preserve its disk bytes and SQL history, settle/replay normally |
| Same checkpoint unconsumed publication, mismatched SHA/claim identity, current work/Run, actual larger checkpoint | Reject; retirement IDs or earlier attempt alone grant no exception |
| Corrupt consumed resolution/digest | Fail closed before Task/event/queue mutation |
| Ordinary budget remains / different wait classification | Existing investigation path, no settlement |
| Missing stop/result, live or unknown process, foreign claim, changed inventory/source, accepted candidate/successor | Reject or retain wait, no Task/event/queue mutation |
| Failure before queue event / transaction commit | Roll back Task/event/queue; no public success report; exact replay can consume sealed decision |
| Exact replay after commit | Same result, zero new event/claim/refund |

## Tests and stock handling

`tests/manager/test_stopped_budget_settlement.py` covers original red symptom, read-only INSPECT, drift, remaining budget and crashes on both sides. `tests/work_queue/test_stopped_budget_settlement_mysql.py` uses actual released MySQL claim and a real exited process; it verifies atomicity, rollback, history and exact replay. Public Host regression confirms terminal cursor and recovery proposal boundaries.

The MySQL suite must also publish a progress under a real claim, consume its real rejected-output resolution, claim a successor sharing the input checkpoint, then HANDLE the stopped exhausted successor. Assert unchanged original Task event prefix, accepted receipts and claims, unchanged attempt/retry accounting and one terminal event on replay. SQL negatives cover absent consumption, changed SHA/lease/current work/later checkpoint and corrupt decision digest. Good: exact consumed historical progress. Base: no historical publication. Bad: treat all equal checkpoints as current outputs, or exempt by ID alone.

存量通过原 Requirement 的公开 HANDLE 精确处理；不直接改生产数据库。不满足严格前提的历史等待保留原记录，不能以批量迁移或臆造 stop 消除阻塞。新增记录后回滚保留 typed readers，不删除草稿或审计记录。
