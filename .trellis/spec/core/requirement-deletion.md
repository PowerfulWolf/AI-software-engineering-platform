# 产品需求删除与工程历史保全

## Scope / Trigger

适用于 `DeleteRequirement`、Console `DELETE_REQUIREMENT`、Project reader 及删除后重新创建。
删除是产品目录的永久 tombstone，不是关闭、重启、销毁 dirty worktree 或覆盖已封存历史。
生产入口必须核验已显示的 Project / Requirement / checkpoint 精确身份，并证明工程执行停止。

## Signatures

```text
DeleteRequirement(delivery_id, expected_checkpoint_sha256, submitted_at)
JointDeliveryService.delete_requirement(command) -> JointDeliveryResult
RequirementDeletionGuard.protect(checkpoint) -> AbstractContextManager[None]
ProductionRequirementDeletionGuard(project, queue, dsn)
RequirementRetirementStore.retire(checkpoint, reason="deleted", retired_at=...)
RequirementRetirementStore.require_native_active(delivery_id, journal) -> None
ConsoleIntent(action="DELETE_REQUIREMENT", project_id, delivery_id, expected_checkpoint_sha256)
```

Console 的现有 Operation journal 先封存用户意图，再由 Manager adapter 调用服务；不新增第二套
HTTP 删除或目录清理入口。tombstone 继续使用 `requirement-retirement.schema.json`，旧 digest
与原历史保持可读。checkpoint digest 已绑定 scope，不另设可覆盖 scope 的删除参数。

## Contracts

- 支持未批准的 Product draft，以及已停止的 `BLOCKED` / `CLOSED` / `DONE`。不允许删除正在交付的需求。
- 在现有 Requirement operation lock 内验证完整 journal、owner 和 expected digest；同一精确
  deleted checkpoint 重放成功且不改 tombstone 时间/字节，其他 digest 或 replaced 记录拒绝。
- 有 Task 的历史必须配置 production deletion guard；guard 遍历所有联合及原生子交付历史，
  保留全部历史 Task，持有现有 `state/queue-worker-locks/<sha256(task_id)>.lock`；资源按下节完整保全后释放。
- 最终删除准入时 Task 必须是 `DONE/BLOCKED/FAILED`，queue steps 必须 `CLOSED`，无有效 Lease 且进程锁可独占。
  Task/queue facts 从 typed 端口与只读 SQL 获得。明确用户删除可先调用下节取消服务终止已停止的旧执行，
  使用现有 TaskRepository/StateEvent 和队列 service，不能手工改 SQL 或 verdict。无取消能力的 guard 仍严格拒绝非终态/未closed队列。
  缺失、漂移、跨仓归属、live process、有效 lease 都拒绝，不能靠 UI 隐藏处理。
- 新建同名、同scope需求派生新的 delivery identity；仍保留当前输入的幂等创建，永不调用
  `retirements.restore(old_id)`，不复用旧 Product approval / design / plan / Task /候选或预算。
- 已删 parent 的列表、计数、详情、child Tasks、Agent assignment 均从同一 retirement 事实过滤。
  Continue、Product approval、restart、知识审批和原生 child recovery 也必须拒绝 deleted parent；
  原 immutable audit 文件只能用于工程审计读取，不授予再次执行的能力。
- `require_native_active` 校验所有retirement的owner/current digest，并核对完整父历史children
  和未attach子交付的确定性派生identity。Host native Continue在构造recovery controller前调用；
  NativeRecoverySourceReader在读SQL前调用，shared `_parent`重复核验给Candidate/restart使用。
  matched retired parent抛中文`RequirementRetiredError`，不能跳过它并降为standalone恢复。

## Validation / Error Matrix

| 输入 | 行为 |
|---|---|
| exact idle BLOCKED/CLOSED | 写一次 tombstone，原 journal / verdict / artifact 保留，完整保全后释放受管工作区 |
| 相同删除重放 | 返回原 checkpoint，原 tombstone 字节不变 |
| stale checkpoint / other Project | 拒绝，无 tombstone |
| live Worker lock /有效 Lease /不可核验的队列或任务 | `RequirementDeletionRejected`，Console `REQUIREMENT_ACTIVE`，中文下一步 |
| deleted parent Continue/approval/restart | 拒绝，零新增模型调用 |
| 同名新建 | 新 identity + 原产品准备流程，旧 tombstone/history永久保留 |
| corrupted retirement/history | fail closed，不能用缺失数据冒充无活动 |

## Good / Base / Bad

Good：删除用户不再需要的两份已停止 K1，产品页无残留，审计保留，并且不新建/执行。
Base：尚未开始讨论的草稿删除，同一精确命令可安全重放。
Bad：同名create撤销tombstone、直接删除sidecar、只过滤列表而child仍可执行、改旧Task终态。

## Tests / Existing Data / Rollback

增量 `tests/manager/test_requirement_retirement.py`、`tests/manager/test_requirement_deletion.py`、
`tests/web_console/test_manager.py`、`tests/team_view/test_live.py` retirement case。
覆盖公开typed入口、实际process锁、历史owner与原生Task inventory、lease/queue/Task负向、
同名新identity、删除重放与旧审批保持；不跑全量。

存量两 K1 只能在空闲部署后，用当前 Project/ID/digest 提交正式 Console deletion Operation；
检查Operation成功、reader列表/详情/计数/child一致，以及原历史/hash不变。不得直接生产SQL写入、
删目录或绕过完整保全清理dirty worktree。回滚代码需在空闲时进行，保留已删 retirement；旧版本同名create
会复活记录，应暂停create直到修复版本重新加载，不能把回滚作为撤销删除。


## Explicit deletion settles abandoned execution (2026-10-05)

Scope: an exact DELETE_REQUIREMENT of a stopped BLOCKED/CLOSED parent explicitly withdraws
all its historical delivery work. Closing the parent alone never proves its historical Tasks
are terminal. Legacy lease-expired IMPLEMENTING Tasks with RETRY_SCHEDULED items must be
cancelled through the typed application service; rejecting forever or editing SQL manually
is not an acceptable product workflow.

Interfaces: `RequirementCancellationReceipt` binds Project/Requirement/checkpoint, exact Task
snapshots and queue inventory, requested user deletion and SHA-256; the immutable resolution
receipt is written before cancelling. `MySqlRoleQueue.cancellation_fence(cursor, task_id)`
uses the queue authority lock and refuses any valid Lease.
`MySqlRoleQueue.close_cancelled_task(task, *, expected_items, cancellation_sha256, now)` requires the current
exact terminal Task snapshot, closes abandoned work and appends REQUIREMENT_CANCELLED facts.
`verify_cancelled_inventory(cursor, task, expected_items, *, cancellation_sha256, now)` also
checks the sealed inventory under the same authority fence; it rejects new items or drift
and accepts only a receipt-bound exact CLOSED successor with its cancellation event.
The production deletion guard holds all historical Task process locks, checks all owners,
Task snapshots and leases before mutation, then uses existing TaskRepository/StateEvent to
terminate nonterminal Tasks as BLOCKED (NEW uses the existing FAILED edge) with a
receipt-bound Chinese reason. Terminal Tasks
and old events/verdicts/artifacts remain unchanged. No Worker/model call or new claim is made.
Only after all Tasks and queues satisfy the original stop guard may retirement be committed.

| Condition | Required behavior |
| --- | --- |
| Exact requested delete + stopped legacy Task + expired/released Lease | Seal resolution, append cancellation StateEvent, close queue, retire parent |
| Live process lock / valid Lease / owner or snapshot drift | Refuse; no automatic termination of live work |
| Receipt exists, Task/queue settlement interrupted | Revalidate unchanged scope and replay remaining steps; no model or duplicate event |
| Queue close with nonterminal/mismatched Task | Refuse; no CLOSED fact |
| Repeated deleted identity | Original tombstone and resolution preserved; no new event |

Good: user deletes the old stopped K1 and its three abandoned retries are audited as cancelled.
Base: already terminal/closed work needs no settlement. Bad: clearing queue without terminating
Task, claiming a model Run to simulate cancellation, or using terminal cancellation to reopen work.

Required incremental tests: manager cancellation process/lease/ownership/drift and partial
restart cases; work_queue cancellation MySQL validates current terminal snapshot, active Lease
rejection, expired owner fencing, idempotency and no new claim. Existing deletion negative guard
remains strict when the optional cancellation service is unavailable. No production SQL patch.


Receipt signatures and storage:

```text
RequirementCancellationReceipt(team_id, team_manifest_sha256, project_id,
  project_manifest_sha256, delivery_id, checkpoint_sha256, human_action,
  tasks: tuple[CancellationTaskInventory, ...], cancellation_sha256)
CancellationTaskInventory(task, repository_id, task_snapshot_sha256,
  state_revision, state_events_sha256, source_revision, queue_items,
  queue_inventory_sha256)
FileRequirementCancellationStore(requirement_root).find()/put(receipt)
# <requirements>/<delivery_id>/cancellations/receipt.json (0600)
```

The receipt MUST NOT be a top-level JSON beside numbered JointCheckpoint files, because
JointJournal validates all top-level JSON as its immutable sequence. Native Task scalar
status and typed snapshot must agree; a deletion never silently repairs corrupted indexes.
Current operator origin denotes a trusted local submission, not authenticated RBAC or a
model self-approval. This session's submission is explicitly delegated by the user's request.
Original StateEvents, queue history and verdicts remain unchanged; audit adds cancellation
resolution/state/queue events, retirement and resource preservation/release records.

## Explicit close of stopped engineering waits (2026-10-13)

`CLOSE_REQUIREMENT` also accepts a `DELIVERING` parent only through
`RequirementWaitingCloseGuard.protect_waiting_close(checkpoint)`. The production guard holds
all historical Task worker locks and rejects any valid Lease, unverifiable owner or inventory.
No guard/cancellation capability means rejection. BLOCKED close also settles abandoned stopped execution through the same typed service.

`RequirementCancellationService.cancel(..., action="CLOSE_REQUIREMENT")` binds the real user
action in the immutable receipt. All open historical queue items must be WAITING_HUMAN or
WAITING_DEPENDENCY with a typed engineering disposition bound to the original Task intent,
current effective queue source revision and current checkpoint. Each nonterminal Task must have such a wait; READY,
RETRY_SCHEDULED, LEASED/RUNNING and missing/stale waiting facts reject. A waiting label alone
does not prove execution stopped: the existing full-history locks and lease fence remain required.
The original sealed inventory decides replay eligibility, including when some Tasks/queues have
already been cancelled. Cancellation uses existing state events and queue fences, then CLOSED
is appended only after every Task and queue satisfies the original inactive guard.

Closing produces a new parent checkpoint. A subsequent exact DELETE of this CLOSED checkpoint
checks terminal Tasks/closed queues directly and preserves the existing close receipt; it must
not try to rewrite that receipt under the new digest or describe the close as a deletion.
Waiting cancellation replay clears wait_disposition together with wait_reason/available_at,
matching the production queue's exact CLOSED successor.

Required tests: public waiting close/delete, stale/missing/nonengineering disposition,
nonwaiting queue, worker lock/valid and racing lease, owner/digest/inventory drift,
receipt-before-event and event-before-queue replay, and unchanged BLOCKED lifecycle.
Existing K1: reload at an idle controlled restart; submit formal CLOSE with current Project/ID/
digest, reread the new CLOSED digest, then submit formal DELETE. Preserve old Operations,
Task/event/queue/artifact history and dirty code; no direct SQL or directory deletion.

已由 CLOSE_REQUIREMENT 取消工程的需求不得 RESTART_REQUIREMENT 复活；明确提示新建身份。
Console只显示关闭/删除，不显示重启；低层兼容接口仍可读旧普通关闭记录。单份immutable cancellation receipt
不扩展为多轮恢复策略。terminal/closed删除跳过新settlement前仍核验既有receipt的typed/digest、
Team/Project/Requirement、完整Task/repository范围与journal祖先；CLOSE receipt必须对应已完成的
CLOSED直接后继。损坏/外项目/缺失完成链拒绝，不以新checkpoint规避原审计完整性。


### Rebound execution sources

Task.base_ref and previous StateEvents remain immutable after an approved ExecutionBaseline.
For CLOSE, sealed wait facts must match the current typed `queue.step(work_item_id)` boundary,
including exact Task/work identity, role, attempt, checkpoint and repository scopes. Production
`MySqlRoleQueue.step` validates immutable SQL step bytes and resolves same-item baseline overlays;
a reserved successor already has its own fenced, immutable current-source boundary. Missing
step/overlay or a changed effective source rejects. No second baseline approval/resolver is added.
Fakes without this typed step capability retain the original event-source equality.

Recheck the effective boundary during current-state preflight and inside the existing queue
mutation authority fence, before and after the cancellation event. The new terminal event uses
the unique sealed, verified current waiting source. Old Task.base_ref and event bytes remain
unchanged. A real baseline regression must call `validate_pre_candidate_sources` over the
resulting terminal Task/events and full baseline epoch; original old-source events cannot be
copied as the source of the post-binding cancellation.

## 通用关闭、删除和资源释放（2026-10-13）

产品不提供归档。空闲 Product 草稿、BLOCKED 和严格已停止工程等待可关闭；DONE可删除。
Console不提供关闭后的重启按钮；已取消执行必须新建身份。保全压缩包是恢复资料，不是产品归档。

### Signatures / facts

```text
GitWorktreeManager.archive_and_remove(ref, *, archive_root, owner_sha256)
  -> WorktreeReleaseArchive
ProductionRequirementDeletionGuard._verification_resources(checkpoint, targets)
  -> fenced context of released independent verification worktree identities
SELECT id FROM dispatch_authority_lock WHERE id=1 FOR UPDATE
SELECT plan_sha256,payload_json,completion_sha256,abandonment_sha256
  FROM verification_reservations ORDER BY plan_sha256
```

guard读取所有父历史、附着child和所有历史plan确定性派生的真实native journal，持有每个历史Task锁，
核对owner、terminal Task、CLOSED queue和无live Lease。未附着但已持久化native Task同样在范围内；
不存在的native journal不能凭名称猜成任务。独立VerificationReservation不是tasks表里的Task；
其source必须属于已核验原生Task，repository必须为当前Project，计划scope/input/execution identity必须
精确，completion或abandonment仅一个合法SHA。未释放reservation即使lease时间已过也拒绝。
先短暂取得fence只读预检并拒绝未完成验证，再settle普通队列，后取得现有dispatch authority fence，重读reservation并保持到CLOSED/tombstone发布；
fence内不再调用会在另一连接写入dispatch lock的settlement服务。不能伪造abandonment或verdict。

释放只接受上述历史Task的受管角色路径、精确需求baseline/candidate reviewer路径、已释放独立验证
QA/Reviewer attempt01。完整保全tracked/unstaged/untracked/ignored/目录/链接、raw index及所有stage blobs；
记录archive/entry/index/object SHA和scope digest；给HEAD建立`refs/ase/retained/<owner>/<path-sha>`避免detached
成果在Git GC后丢失。branch、commit、artifact、audit和共享数据库保留。每工作区上限100000条/2GiB，
单stage blob32MiB、manifest32MiB；split-index、nested Git/submodule、特殊文件或超限均拒绝并保留现场。
压缩包、immutable archive.json、release-intent.json、released.json存于
`<project>/requirements/<parent>/resource-archives/<sha256(abs-worktree-path)>/`，0600文件/0700目录。
原像封存和校验完成后才reset/clean，再调用原有非force remove。新保全契约见
`schemas/worktree-release-archive.schema.json`与`git/release.py`。

### Validation / recovery matrix

| 输入/中断 | 必须行为 |
|---|---|
| 完整停止且全部资源可核验 | 保存全部原像、释放临时工作区后发布CLOSED/tombstone |
| live process/lease、未释放独立验证、owner/hash漂移 | 拒绝，不丢弃原文件或伪造停止 |
| tar已发布但manifest未发布 | 保留unsealed副本，从仍在的完整原像重新保全 |
| settlement完成但archive失败 | 父checkpoint不变，原receipt可重放；页面终态Task/CLOSED队列允许重试关闭 |
| reset后、remove前失败 | 只有index及逐文件byte/mode/kind都为HEAD后像，且未tracked资源为原保全子集可重放 |
| assume-unchanged/skip-worktree或未保全新增文件 | 拒绝，不能只靠git diff为空证明干净 |
| remove后released发布失败 | 从完整manifest重新核验owner/path/tar/intent/retained ref，补同字节completion |
| CLOSE后DELETE | 复核所有保全及完成记录，不能重写CLOSE receipt/时间/原文件 |

Good：关闭一个停止的需求，全部受管草稿私密保全，角色/基线临时工作区释放，无关目录不动。
Base：无Task草稿仍释放其精确baseline。Bad：只写CLOSED、只存diff遗漏ignored/staged、用force-remove、
把reservation当普通Task或从expired lease猜provider停止。

Required tests：真实Git staged/unstaged/ignored/link、GC恢复stage blobs及detached commit、partial reset
重放/hidden flags拒绝、tar/manifest/completion中断、公开close→delete多角色/基线释放、未attach native
锁、独立验证released/unreleased/foreign scope和dispatch fence竞争；Operation过滤测试同时验证完整audit。
Wrong：通过直接SQL/tombstone隐藏活动资源。Correct：typed停止+完整scope锁/fence+verified原像+正式产品操作。

### 存量数据处置 / rollback

旧K1已正式CLOSE/DELETE且30临时工作区已另行完整保全释放；不重跑清理、不改旧journal或共享数据库。
新K1暂停在产品待批准，部署不批准或恢复。日常读取按retirement实时过滤旧操作，无需改库。
代码回滚只在空闲受控重启，必须保留CLOSE receipt兼容读取、tombstone、archive与retained refs；
回滚不恢复已取消执行。资源恢复由维护者在隔离位置校验manifest/tar并恢复stage blobs/index，
不能解压覆盖主checkout或自动复活旧需求。
