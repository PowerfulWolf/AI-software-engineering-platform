# Requirement close and physical deletion

## Scope / Trigger
The user explicitly chose physical deletion (2026-10-13). DELETE_REQUIREMENT removes Requirement-owned bodies and execution resources. CLOSE_REQUIREMENT stops execution and retains Requirement data. There is no archive feature. Already merged repository code and shared Team/Project knowledge survive deletion.

## Signatures
- `JointDeliveryService.delete_requirement(DeleteRequirement(delivery_id, expected_checkpoint_sha256, submitted_at)) -> RequirementDeletionResult(delivery_id, checkpoint_sha256)`.
- `RequirementPhysicalDeletionGuard.protect_physical_delete(checkpoint) -> ContextManager[RequirementPurgePlan]`; `purge_storage(plan, already_fenced=False)`.
- `RequirementPurger.prepare(checkpoint, targets, native_ids, persist=True) -> RequirementPurgePlan`; `persist=False` is a read-only inventory preview.
- `RequirementPurger.execute(plan, already_fenced=False) -> RequirementPurgeCompletion`.
- `delivery_wait_recovery_scope(task: Task, scope: EngineeringScope) -> RecoveryScope` is the shared deterministic producer/cleanup scope for Task engineering authority. It checks exact repository root and frozen policy scope before deriving the `delivery_wait_` identity.
- Console retains POST `/api/v1/operations` with `action=DELETE_REQUIREMENT`, Project/Requirement and exact checkpoint digest. No arbitrary-path or raw-SQL cleanup API.

## Contracts
1. Validate the complete parent/native histories, manifests, exact Project/Repository/Task owners, stopped process locks, terminal Tasks, CLOSED queue and absence of valid leases. Independent verification must be released and have its existing sealed plan/completion provenance. Reject active or unverifiable resources.
2. Settle abandoned delivery through the existing cancellation service before removal; never manufacture QA/Review verdicts. Close keeps cancellation receipts, journals and archived worktree drafts; explicit delete removes them after validation.
3. Seal a pending plan containing exact relative paths, complete streamed file SHA/size, exact SQL primary keys/row SHA and Git ref expected revisions. No Requirement body is copied into this plan. Validate fresh source bytes, typed SQL identities/digests and storage ownership before irreversible changes. Missing sealed files/rows/refs are accepted only for this exact plan's replay; new files, rows, owners or changed bytes reject.
4. Cleanup covers the parent journal/attachments/release archives, all native children and old Tasks, SQL Task/events/dispatch/queue/Manager facts, sidecar artifacts/context/evidence/run/invocation/knowledge facts, owned Operation/preparation histories, Team Task authority ledger and exact temporary worktree metadata/references. Current and legacy FK families never share an identity set. Matching unsupported legacy contracts refuse cleanup.
5. Knowledge uses namespace → typed model → exact hashed storage key. Invocation lanes must match every intent's complete binding and lane digest; execution records must reference a verified owned intent. Query-only knowledge-intents derive scope from their verified run binding. A nested reference or arbitrary filename is never deletion authority. Shared Manager contexts are removed only if no unrelated run references them.
6. Team ledger paths are `team/work-items/digest({repository_id, task_id})`. Verify its `RecoveryScope`, every EngineeringAdmission via `EngineeringAuthority.validate`, and either native delivery scope or exact scope produced by `delivery_wait_recovery_scope` for the already verified Task. This is the existing writer's contract (manager/delivery_wait.py), not a caller-selected identity exception.
7. Git retained refs derive from verified release archive owner/path digests. Coder branches come from the same exact archive/Task identity. Ref deletion uses expected-SHA CAS, refuses still registered worktrees, drift and protected refs. Main commits and shared Git objects are preserved; normal Git GC may reclaim unreachable objects. No direct `.git/objects` deletion or aggressive GC.
8. Publish deleted retirement before destructive replay, including a crash after prepare but before retirement. Completion retains only bounded body-free identity revocation digests/native IDs; it contains no Requirement content, artifact, diff or operation history. Old commands cannot recreate journals; same-name creation uses a new identity. Release private decoded journal caches after completion.
9. Before removing any Operation chain (terminal historical or current DELETE), publish a bounded, sealed ConsoleDeletionCleanup outside the history root. It binds the exact Team/Project/Requirement and original typed snapshots, paths and byte digests. Exclusive Console entry replays cleanup before parsing histories; read-only queries consume the original pending snapshots. Delete the pending body only after every selected file/directory is gone.
10. The current DELETE Operation is physically removed after successful execution. A bounded in-memory exact acknowledgement (64 entries, <=16KB each, 120 seconds) supports immediate GET; it is excluded from history and disappears on restart/expiry. Failure must not be reported as successful cleanup.

## Validation / Error Matrix
| Case | Required behavior |
| --- | --- |
| Exact stopped draft/closed/blocked/done | Physically remove owned data and resources; publish minimal revocation |
| Stale checkpoint, foreign repository, corrupt record/digest | Refuse before deletion |
| Live process/lease, unreleased independent verification | Refuse; retain resources |
| Prepare/retirement/SQL/file cleanup interruption | Preserve exact pending plan; replay without reviving identity |
| Unrelated Task, shared organization knowledge, main branch | Preserve |
| Deleted parent/native continue/approve/restart | Reject before model/claim creation |
| Same name after deletion | New Requirement identity |

## Good / Base / Bad
Good: deleted K1 histories, owned queue rows and temporary references disappear; unrelated current Requirement remains readable.
Base: a draft and its attachment are removed, exact delete replay succeeds, stale commands fail.
Bad: silently hiding 329 MB of old journals, leaving current delete Operation on disk, recursively treating reference IDs as ownership, or skipping verifier release safety.

## Tests and assertions
`tests/manager/test_requirement_physical_delete.py` covers real public deletion, query closure/foreign preservation, pre-retirement crash, partial file replay, equal-size drift and stale direct append. Related deletion/cancellation/resource-release tests must assert physical absence in dedicated MySQL and real Git fixtures, and keep active/process/lease/tamper rejection. Console tests verify physical removal and transient GET acknowledgement. Schema fixtures validate purge plan/completion. Original HTTP latency harness must pass on team summary and operation summaries including 304, followed by browser checks.

## Existing-data handling and rollback
Inventory exact deleted Requirement IDs/digests and release conditions first; deploy at idle, then replay the same typed service for those IDs. Any old verifier reservation without release must be reconciled through the existing typed dispatch abandonment service only after controlled Host stop/process proof; record the precise decision before mutation. Do not reset a Task or revive a deleted Requirement. Verify file/SQL/ref counts before and after plus the unrelated current Requirement. Physical deletion is irreversible; rollback is code-only at idle and must preserve revocation compatibility. No deletion backup containing Requirement bodies is retained.

## Performance failure mode
Retirement visibility formerly reparsed 271 JSON files / 328,576,222 bytes on every read (3–5 seconds CPU). Operation summary caches did not include this dependency; 304 only reduced response transfer. Purged identities now use small verified completion markers and never reload deleted bodies. Measure the complete endpoint dependency chain rather than only a projection cache.

## Close waiting execution contract
Close retains cancellation receipts and drafts. Hold all historical process locks, reject valid leases and validate exact typed WAITING facts before cancellation. Terminal state events use the effective admitted execution baseline, not an obsolete Task base revision. A cancellation is final for that execution; restart cannot revive cancelled work.

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
digest and retain Operations, Task/event/queue/artifact history and captured drafts under CLOSE.
Reread the new CLOSED digest, then submit formal DELETE to physically remove the exact owned,
validated records and release resources. Do not bypass the service with ad hoc SQL or directory deletion.

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


Task branch declarations do not authorize removing a pre-existing colliding branch. Semantic refs require an exact release archive or clean removal marker reconstructed from the durable Task/StateEvent/Artifact revisions and actual attempt. Unverifiable legacy default refs refuse full deletion; an operator can inspect and authorize exact ref/SHA cleanup, then replay.


Task-owned continuation and execution-baseline directories are not selected by Task ID alone.
`task_state_directories(sidecar, StateDeletionScope)` validates every receipt, admission,
capture claim, plan, authority, binding, native-rule epoch, continuation authorization and
quiescence record against exact Team/Project/Repository/Requirement scope and writer keys.
The complete baseline namespaces are `baseline-plans`, `baseline-authorities`, `baseline-starts`,
`baseline-bindings`, `baseline-native-rules`, `baseline-continuations`, `baseline-quiescence`.
Validate the formal `invocations[*].legacy_containment` and original claim repository scopes;
Task IDs or directory names alone cannot authorize deletion. The only non-JSON baseline file
is the private regular `execution.lock`.
Unknown additional files or foreign scope refuse deletion before mutation. Persisted purge
plans use the same indent=2 byte budget at preparation and publication as pending replay.

Completion publication followed by pending-plan removal interruption must replay via `finish_completed(completion)`: exact owner/checkpoint/plan digest equality before unlink; disagreement refuses and no deleted identity is revived.


A branch shared by multiple stopped Task identities inside the same complete deletion scope
can be selected only with exact verified removal provenance. A holder outside the scope
still refuses deletion. Historical continuation aliases are not foreign resource owners.


Legacy PREPARING snapshots already revoked by an exact deleted retirement may be physically
purged only at initial sequence=1 with no predecessor, when checkpoint digest matches and no approved requirement/design/plan/child/integration
exists. Fresh PREPARING remains ineligible; the execution/Operation/resource guard still applies.
This compatibility rule never appends a new approval or revives the retired identity.
