# Team 当前摘要与精确完整详情

## Purpose and ownership

Console 定时刷新必须读取当前决策与执行事实，不能为每张卡片反复序列化全部历史正文。
`ProductionTeamReader` 保持纯读，不构造 Host，不修改 Task、Operation、审批、预算或 workspace。
旧 `TeamSnapshot(v0.2)` / `GET /api/v1/team` / 原 Schema 保持兼容。

## Signatures and wire contract

```python
ProductionTeamReader.summary(project_id: str | None = None) -> TeamSummary
ProductionTeamReader.detail(query: TeamDetailQuery) -> RequestDetail | TaskDetail
```

- `GET /api/v1/team-summary` 返回独立 `TeamSummary(v0.1)`，包含全部 Team/Project/Agent
  和所有 Request/Task 当前卡片；显式字段模型不能继承后再制造空正文数组。
- `RequestSummary` 保留原 Request 除 `dialogue/documents` 的所有当前字段，并提供
  `detail_source` 与可选 `product_spec_source`。
- `TaskSummary` 保留原 Task 除 `documents/timeline/execution_history/runs` 的所有当前字段，
  包括完整 `history_task_ids`、role queue、approval/baseline 来源。
- `GET /api/v1/team-details` 返回 discriminated `RequestDetail|TaskDetail`：
  `kind/as_of/scope/resource`，resource 为完整原视图；不截取最近 8 条或任意 N 条历史。
- `GET /api/v1/console` 仅在 reader 同时实现两个 typed 端口时声明
  `team_read_contract_version="v0.1"`，旧 reader 不宣称能力。

独立 Schema 位于 `schemas/team-{summary,detail,detail-query}.schema.json`，通过
`PYTHONPATH=src python scripts/sync-team-read-schemas.py` 确定性生成；不得覆盖旧 v0.2 Schema。

## Locator and validation contracts

`TeamDetailSource` 明确绑定 `team_id/project_id/request_id/resource_kind/resource_id`、
当前 owner `requirement_checkpoint_sha256`、资源 native `resource_checkpoint_sha256` 与
只读 `resource_state_sha256`。Query 使用 `kind/id` 和所有 `expected_...` 版本字段。

普通 SQL Task 的 `task_id/task_revision/task_intent_sha256` 三元组必须完整；真实 revision 0
合法，bool/string/负值非法。预派发三者皆空。候选验证使用真实 reservation `task_id` 与不同的
`source_task_id`、`verification_plan_sha256`，不能伪造 SQL revision/intent。
Python 与 JSON Schema 都约束各变体；跨字段动态相等/不等关系由 typed model 强制。

`resource_state_sha256` 只用于正文读取失效与前后 fence，不能作为批准、READY 或恢复许可。
Request 基于真实 checkpoint；交付 Task 绑定 native checkpoint、Task 三元组、已验证当前
timeline source digest 和该需求各真实 Task 的 model-route attempt digest。候选验证额外绑定
已验证 reservation、plan、authority、QA/Review invocation、已保存 completion、SQL release/
abandonment、supersession 及对应实际 run 的 route attempt digest。阶段名称相同但新结果封存时，
读取版本也必须变化；不能仅用 status label，不创造执行事实。

`ProductSpecSource` 保留原持久化 digest，不 hash 脱敏正文。原生 Spec 有真实 `spec_id`、
`version=null`、精确 `ProductSpec://<id>`；联合 Spec 没有 ID，使用真实 `version>=1`、
`spec_id=null`、`request://<request.id>/ProductSpec`。不能编造联合 Spec ID。
选中原生 Request detail 通过只读 `FileProductRecordStore` 读取完整原生 JSON；核验 native
sidecar 的 Project/repository binding、原 request/preparation、Product checkpoint、Spec ID/digest
后提供正文。缺失、损坏或外部正文必须失败，不能用空引用冒充完整已读。旧 v0.2 full 保留旧引用。

## Read lifecycle and performance boundary

### Detail-owned joint decoder reuse (2026-10-19)

`detail(query)` may explicitly pass a private synchronous journal owner into its body and
final `_read_snapshot(..., joint_reads=...)` calls. The owner holds at most one read-only
`JointJournal` at a time; a changed root clears the prior decoder. Each observation creates
a new `_JointHistorySnapshot` and independently enumerates original files, rejects symlinks,
reads complete bytes and recomputes SHA. Only the existing journal decoder may reuse an
unchanged payload and exact predecessor-bytes identity. Changed bytes/edges, filenames,
chain, Team/Project, native ownership, retirement and current SQL/authority facts retain
their original checks and refusals. The second SQL snapshot remains independently fresh.

`JointJournal.clear_verified_reads() -> None` only clears private decoded records and must
not access the filesystem or perform validation. The detail-owned `finally` calls it and
discards the journal on success, stale/not-found, read/validation error or cancellation,
so an exception retained by its caller cannot retain models through this new shared cache.
`history()` also clears completed iterator/genexpr/validator traceback frame locals on
failure, while preserving the same exception type, arguments and traceback locations.
Clearing only the owner dictionary is insufficient: a warm iterator's `previous/cached`
and the tuple generator's prior `item` can otherwise retain the original private model.
Tests must keep the actual source-read exception and its cause/traceback alive and check
weak references to the first observation's private models, including a later-path read
failure and a changed-predecessor/unchanged-successor chain failure. The original byte,
integrity and successor validation algorithm remains unchanged.
Public `history/current` keep defensive deep copies. Full/summary and later independent
detail calls do not share this owner; no reader-instance/global/ContextVar cache is added.
The existing 512-entry decoder bound is a record count, not a serialized-byte or RSS bound.

### Snapshot-local verified history borrowing (2026-10-27)

`JointJournal._borrow_verified_history(delivery_id: str) -> tuple[JointCheckpoint, ...]`
exhausts the same complete `_validated_history` chain as public `history`, but returns the
journal's private frozen models for inspection inside one synchronous Team observation.
`_JointHistorySnapshot` is the only Team consumer. It stores each complete prefix once for
retirement, ownership and display derivation; the returned `TeamSnapshot`, `TeamSummary` and
`TeamDetail` contain newly projected views, never a borrowed `JointCheckpoint`. Neither a
cross-request owner nor a cached verdict/permission is introduced. Public `history/current`
continue making independent deep copies for ordinary callers.

Every observation still enumerates every historical path, rejects symlinks, reads complete
bytes, recomputes byte SHA, validates Schema/integrity and predecessor edges, and checks
Team/Project/native ownership. The detail's second observation remains independent; its
existing exact-byte decoder may only reuse unchanged bytes with the same predecessor byte
identity. On any public read failure, clear completed traceback frame locals before wrapping
or reraising the error, so a caller retaining the exception cannot retain the borrowed
history. The detail owner additionally clears its decoder in `finally`.

| Case | Required result |
| --- | --- |
| Multi-checkpoint full/summary/detail | Complete path/byte checks, identical projected wire, no per-record `JointCheckpoint.model_copy(deep=True)` |
| Public `JointJournal.history/current` | Independent deep copies, including nested scope |
| Ancestor mutation, missing/renamed/symlink record or changed predecessor | Same fail-closed rejection; no partial Team response |
| Late native/SQL read error with retained `TeamReadError` | Private checkpoint weak references release after the exception leaves the worker |
| Later HTTP/Project observation | New journal and complete fresh validation; no borrowed model survives |

This changes only process-local read assembly. Existing journal, SQL, Task, Operation and
approval bytes need no migration. Rollback restores public `history()` in the snapshot
helper during an idle service restart; historical facts and decisions stay unchanged.

Production measurement on 2026-10-27 found 140 joint checkpoints totaling 291 MB for two
Requirements. A read-only profile attributed about 2.46 of 3.43 seconds in one summary read
to complete joint-history verification. Same-data isolated runs of this change measured
2.726→2.538, 2.710→2.476, and 2.503→2.508 seconds, with a 44–80 MB lower peak RSS.
This bounded improvement does not resolve slow first-load refreshes: the full historical
byte, Schema, digest and predecessor checks still run for every observation. A broader
solution must preserve fresh audit validation and decision fences, and needs separate
performance evidence before changing cross-request lifetime rules.

Good: a record's decode/integrity/successor checks run once across unchanged observations,
while original complete-byte reads run twice and typed output is identical. Base: empty
history or evicted decoder entries still yield all records. Bad: a resealed ancestor with
an unchanged successor, same-size/mtime corruption, missing record, renamed file, symlink,
new tail or changed current authority must not borrow a stale source or permission.

File/fake tests in `tests/team_view/test_detail_joint_decoder_scope.py` must count actual
decoder/full reads, assert independent snapshots/SQL,
mutation and chain/path refusal after the body, request isolation, public copy isolation
and explicit release with retained exceptions. No MySQL or portable wall-time threshold
is required. Existing data is unchanged; rollback restores duplicate decoding. Production
measurements and deployment belong to a later controlled idle window.

详情返回完整选中资源，不装配未返回的 ProjectView 统计。Task 详情与其 source fence 仅装配
选中 native Task（含全部历史）或选中 candidate verification（含真实 source Task 核验）。
原 joint/native ownership history 与 reservation SQL envelope 仍完整核验；其他卡片的工程、
队列和正文装配留给普通摘要/full。结束时使用相同 selected Team/Project
文件与独立 SQL snapshot 重新计算 exact `TeamDetailSource`；完整读取该来源所需全部事实并比较
完整 query，不为 fence 构造无关 Project 的统计。普通 full/summary 仍提供完整 Project 列表。
同一 `_TaskReadSnapshot` 的 compact→body 仅重新读取 accepted artifact 原文件和完整 receipt/
claim 校验并装配 documents/runs；已核验的工程状态来自同一 exact projection，不能跨 transaction
或 HTTP 复用。本文后面的“全新当前摘要 fence”指同一当前来源计算，不能解释成可缓存授权。

Standalone native candidate verification 没有 joint owner 时，选中详情和最终 source fence
仍从已核验的当前 native checkpoint 构造其真实 Request owner；不能因跳过其他 Task 装配
而遗漏 owner，也不能用 query 自报归属代替真实 source Task 与 native history 的核验。

Request detail 的正文只装配真实当前 owner 的 native work 及其 verification descendants。
历史 joint/native ownership、原生 checkpoint 链、退休记录、Task ID 归属歧义和所有 reservation
envelope/source/repository/release 一致性仍完整核验；仅省略最终会被
`_current_requirement_work` 丢弃的旧工作及无关需求的工程/队列/正文投影。
`_read_verifications(..., selected_source_delivery_ids: frozenset[str] | None)` 的筛选发生在
完整 reservation envelope 与真实 source/repository 校验之后，不能按 query 自报归属略过检查。
普通 full/summary/Task detail 保持原有装配范围。

Request 的 `resource_state_sha256` 按原契约只绑定真实 owner checkpoint，但独立第二次
Request source observation 仍重新完整读取当前 Task 的 SQL、工程授权与 verification 事实，
以及 Team/Project/journal/native/退休/ownership。不能因这些字段不进入 source hash 而省略原有
最后检查；仅省略真实归属检查后确定不会返回的历史或无关 Task 装配。两个 observation 不共享
权限或跨请求 cache。真实未归属 joint 的 standalone native 仍使用其当前 checkpoint。

Good：含多个旧 Task 的 Request 只装配一个真实当前 native work，最终 fresh checkpoint
仍决定是否可返回。Base：Task detail 保留所有历史。Bad：直接信任 request_id、跳过外来损坏
journal/ownership，或用先前的 checkpoint 代替第二次真实观察。
独立性能基线为真实 K1 完整 Request detail 11.571s wall/10.898s CPU；DB 仅0.37s。
不得将瞬态 `TEAM_READ_IN_PROGRESS` 当成数据丢失或证明的死锁。性能验证用计数及独立真实
只读 profile；不以可移植的墙钟时间阈值代替完整性测试。

摘要从装配开始跳过未选中 pretty documents/dialogue、run 展示与历史 Task 完整 hydration，
禁止先 full snapshot 再 strip。摘要仍完整核验当前 Task 所需 accepted artifact、evaluation、
engineering disposition、continuation 和 exact receipt，不能删掉决定安全恢复与终态的事实读取。
本优化减少正文序列化与旧 Task 展示装配，不承诺取消当前事实校验。

详情仅装配选中 Request/Task 的完整正文与所有历史。检查精确来源之后才读取选中正文，读取后
以全新当前摘要重新 fence；新 source 变化则丢弃旧正文并返回 409。
所有 HTTP 成功或失败只持有本次有限快照，不跨 HTTP 缓存成功事实或权限。

full/summary/detail 共用原单 worker admission。只允许完全相同
`(mode, selected Project, complete typed query)` 合并，最多两个额外 waiter；不同模式、
资源或任意 expected version 不得 join。取消 HTTP 不得在真实同步 worker 结束前释放 admission。

## Error matrix

| Trigger | Result |
| --- | --- |
| 未知/删除/外部 Team 或 Project | 固定中文 404，无正文 |
| owner/checkpoint/Task/state 版本漂移 | 固定中文 409，要求重新打开 |
| 未知/重复 query key、非法 ID/hash/revision、部分三元组 | 读取前拒绝，中文 409 |
| 真实原链、正文、receipt 或 scope 不可核验 | 固定中文 503，不部分成功，不泄露内部 exception |
| reader 不支持新契约 | capability 不宣称，新 GET 返回 404 |
| worker 正忙且不同 query/超额 join | 原有 bounded busy 行为，不能绕过开新 worker |

## Executable validation points

`tests/team_view/test_read_models.py` 覆盖字段保留、身份/版本/变体负例、Schema parity 和重复生成。
`test_summary_detail_reader.py` 用真实 Team/Project/journal/Product stores 验证选择性装配、20轮对话、
正文完整与拒绝损坏；13轮旧 Task SQL fixture 仅用于装配计数，真实当前 Task reader 另行核验完整
receipt、QA live 清除旧 receipt、terminal engineering disposition。真实验证 stores/route ledger
覆盖同阶段结果、QA→Review、封存 completion、release/abandonment 导致读取版本变化与旧版本
在 pretty read 前拒绝。`tests/web_console/test_team_summary_detail.py` 与原
`test_team_snapshot_coalescing.py` 覆盖 route/query/error/gate/cancellation/result 生命周期。

## Existing data and rollback

无需修改 SQL、journal、Task、Operation、审批、预算、checkpoint 或 worktree。新视图只从已有
durable facts 计算读取版本。空闲受控加载版本并刷新原需求，原历史仍通过选中详情和旧 full 完整
读取。回滚新 capability/routes/UI 到旧 full；不重写存量事实。仅执行增量测试，全量由用户决定。
