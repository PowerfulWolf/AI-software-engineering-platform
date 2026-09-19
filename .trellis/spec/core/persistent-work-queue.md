# Persistent WorkQueue / Dispatcher Contract

## 1. Scope / Trigger

本规范适用于组织级 Run 调度：`QueuedWorkItem`、MySQL `PersistentWorkQueue`、Planner-owned
Dispatcher tick、Assignment/ModelSelection/Lease 原子提交，以及 Worker 的 start/renew/complete/
wait/retry 生命周期。

一个 `QueuedWorkItem` 只表示一次 Coder、QA 或 Reviewer Run；它不替代 `TaskStatus`，也不允许
Scheduler、Dispatcher 或 Worker 根据自然语言 verdict 迁移 Task。修改这些接口、表、状态或
Team Host composition 时必须同步本规范、`schemas/work-queue.schema.json` 和真实 MySQL 测试。

## 2. Signatures

```python
class QueuedWorkItem(WorkItem):
    id: WorkItemId
    role: AgentRole                 # coder | qa | reviewer
    attempt: AttemptCount
    checkpoint_sequence: int
    dispatch_sequence: int
    repository_scopes: tuple[str, ...]
    parent_work_item_id: WorkItemId | None

PersistentWorkQueue.enqueue(item: QueuedWorkItem) -> QueuedWorkItem
PersistentWorkQueue.get(work_item_id: WorkItemId | str) -> QueuedWorkItem
PersistentWorkQueue.list_schedulable(*, now: datetime, limit: int = 100) \
    -> tuple[QueuedWorkItem, ...]
PersistentWorkQueue.list_active_leases(*, now: datetime) -> tuple[TaskLease, ...]
PersistentWorkQueue.list_assignments() -> tuple[RoleAssignment, ...]
PersistentWorkQueue.claim(item, *, assignment, lease, model_selection, worker_id,
                          owner_token, agent_capacity, now) -> QueueClaim
PersistentWorkQueue.start(work_item_id, *, lease_id, owner_token, now) -> QueuedWorkItem
PersistentWorkQueue.renew(work_item_id, *, lease_id, owner_token, now,
                          expires_at) -> TaskLease
PersistentWorkQueue.complete(work_item_id, *, lease_id, owner_token, artifacts,
                             next_work_item, now) -> QueueCompletion
PersistentWorkQueue.wait(work_item_id, *, lease_id, owner_token, status,
                         reason, now) -> QueuedWorkItem
PersistentWorkQueue.retry(work_item_id, *, lease_id, owner_token, reason,
                          now, available_at) -> QueuedWorkItem
PersistentWorkQueue.make_ready(work_item_id, *, now) -> QueuedWorkItem
PersistentWorkQueue.reclaim_expired(*, now, retry_at) -> tuple[QueuedWorkItem, ...]

DispatcherLoop.tick(*, now: datetime) -> DispatcherTickResult
TeamHost.planner_dispatcher(*, demand_builder, worker_id,
                                        owner_token_factory=None) -> DispatcherLoop
```

MySQL 8.0/InnoDB tables:

```text
work_queue_authority_lock(id PK)
work_queue_items(id PK, task_id, repository_id, role, attempt, checkpoint_sequence,
                 status, priority, risk_rank, available_at, payload_json, version,
                 UNIQUE(task_id, role, attempt, checkpoint_sequence))
work_queue_claims(lease_id PK, work_item_id FK, task_id, agent_id, worker_id,
                  owner_token_sha256, assignment_json, lease_json,
                  model_selection_json, capacity_units, state, acquired_at,
                  expires_at, last_heartbeat_at, ended_at)
work_queue_events(sequence PK, work_item_id FK, event_type, from_status,
                  to_status, lease_id, payload_json, occurred_at)
```

## 3. Contracts

### 3.1 Planner / Dispatcher ownership

- Planner Agent 决定执行计划、优先级、依赖、何时继续/等待/升级；它调用 typed Skill，不持有数据库
  锁，不保存 Lease secret，也不运行无限轮询。
- Dispatcher 是确定性 application service；每次 `tick` 先回收过期 Lease，再最多领取一个 Run。
  外部进程监督器重复 tick，并在无工作时退避；Worker 自己负责 start/renew/result 生命周期。
- `PortfolioScheduler` 和 `ModelRouter` 只计算当前 Agent/模型选择。MySQL queue 在 authority lock
  内重新校验 WorkItem、容量和角色独立性后提交。
- `preferred_agent_id` 只表达 Coder checkpoint 续跑 affinity；不允许绕过 active、role、capability、
  capacity 或 Coder/QA/Reviewer 独立性。

### 3.2 Queue identity and ordering

- 逻辑 Run 唯一键是 `(task_id, role, attempt, checkpoint_sequence)`；`id` 是其稳定外部身份。
- 同一逻辑 Run 因等待恢复、retry 或 Lease 过期重新派发时不改 `id`，但必须递增
  `dispatch_sequence`。Scheduler 将它纳入 Assignment/Lease ID，旧 Lease 因此不能与新 Lease 冲突。
- 可调度顺序固定为 priority 降序、risk 降序、created_at 升序、id 升序。
- `repository_scopes` 至少一个且唯一，用于展示和后续 Worker 授权；它不是绕过 project binding 的
  任意路径 allowlist。

### 3.3 Lease fencing

- `claim` 生成高熵 `owner_token`；调用方持有明文，数据库只保存 SHA-256。`DispatcherTickResult.to_wire()`
  必须排除 token。
- 单节点 v0.1 的所有 queue mutation 先获取 `work_queue_authority_lock`，再锁 WorkItem/claim 行；禁止
  start/renew 与 reaper 使用相反锁序制造死锁。
- 只有 exact `(work_item_id, lease_id, owner_token)` 且 state=ACTIVE、`expires_at > now` 的 Worker
  能 start、renew、complete、wait 或 retry。
- `renew` 不能复活已过期 Lease。reaper 将过期 claim 标记 EXPIRED，将 WorkItem 变为
  RETRY_SCHEDULED，并递增 `dispatch_sequence`。
- wait/retry 立即释放 Agent capacity；WAITING_HUMAN/WAITING_DEPENDENCY 只能由已验证外部信号调用
  `make_ready` 恢复。

### 3.4 Completion and artifacts

- Worker 必须先将结果 Artifact seal、持久化并读回校验，再把 `artifact_id + sha256` 传给 complete。
- complete 在同一事务中关闭当前 WorkItem、释放 Lease、追加 COMPLETED event，并可选发布下一角色
  WorkItem。任一步失败全部回滚，禁止产生“Coder 已关闭但 QA 未入队”的裂缝。
- 相同 lease/owner/artifacts/next 的 completion 重放返回首次 `QueueCompletion`；任一正文变化都
  `QueueConflict`。
- Queue 只保存 Artifact receipt，不解释 Artifact 内容或 verdict；TaskOrchestrator 仍是 Task 交付状态
  的唯一写入者。

### 3.5 Legacy Project schema upgrade

- `MySqlPersistentWorkQueue.__init__` 必须在任何 queue read/write 前检查
  `work_queue_items/work_queue_claims/work_queue_events` 的 exact column set。
- 当前结构使用 `work_queue_items.repository_id`。若三张活动表完整匹配旧 v0.1
  `project_id` 结构，必须使用一次原子 `RENAME TABLE` 将整个 FK 聚合归档为对应的
  `*_legacy_project_v01`，随后创建空的 Repository 结构；不得单改索引列或重写旧 JSON，因为旧
  WorkItem/Assignment/Lease payload 的 canonical hash 与 Project 身份绑定。
- 崩溃发生在原子 rename 后、current create 前时，下一次初始化可在完整 archive 旁重建 current
  表。活动表、archive 任一 partial/mixed/unexpected schema 必须 `QueueCorruption` fail closed。
- current FK 使用 `fk_work_queue_claim_item_repository_v02` 与
  `fk_work_queue_event_item_repository_v02`，避免完整 legacy archive 保留旧 FK 名时发生 schema 级
  constraint-name 冲突。authority lock 不含 Project/Repository 身份，继续复用。

## 4. Validation & Error Matrix

| 输入/当前事实 | 检测点 | 必须行为 |
|---|---|---|
| naive datetime、非法 worker/work item ID | Pydantic/queue boundary | 拒绝；不写数据库 |
| 非 delivery role、重复 repository scope | `QueuedWorkItem` | ValidationError |
| same item ID exact replay | enqueue | 返回首次事实 |
| same ID 或逻辑 Run identity、不同正文 | enqueue | `QueueConflict`，保留首次事实 |
| WorkItem 已被另一 Dispatcher 领取 | claim row/global lock | loser 返回 conflict，tick 继续/IDLE |
| Agent 已满或违反角色独立性 | claim under lock | `QueueConflict`，不创建 claim |
| owner token 错误、Lease 已释放/过期 | lifecycle operation | `QueueConflict`，无状态变化 |
| renew expiry 不晚于 now | renew boundary | ValueError |
| wait status 非 WAITING_* 或空 reason | wait boundary | ValueError |
| retry 时间不在未来 | retry boundary | ValueError |
| current/next task 或 parent 不一致 | complete | `QueueConflict`，整个事务回滚 |
| CLOSED exact completion replay | completion event | 返回原始 completion/时间 |
| CLOSED changed replay | completion event | `QueueConflict` |
| 持久 payload/claim/event 不能通过模型校验 | decode boundary | `QueueCorruption`，不猜测修复 |
| exact legacy `project_id` queue aggregate | initialization | atomic archive whole aggregate, then create empty current tables |
| partial/mixed legacy/current tables or archive | initialization | `QueueCorruption`; no guessed migration |

## 5. Good / Base / Bad Cases

- **Good**：两个 Dispatcher 同时看见一个 READY Coder Run；只有一个持有 claim。Worker 完成并提交
  implementation receipt，事务同时关闭 Coder 和发布 QA；QA 随后可被另一成员领取。
- **Base**：队列为空返回 IDLE；有工作但没有合格 Agent/模型时返回 REJECTED reasons，不产生 Lease。
- **Bad**：旧 Worker 在 Lease 过期并重派后提交结果；owner/state fence 拒绝，新的
  `dispatch_sequence` 产生不同 Assignment/Lease identity。

## 6. Tests Required

- `tests/work_queue/test_dispatcher.py`：单 tick、Agent affinity、无候选 IDLE、typed rejection、
  owner token 不序列化、worker ID/aware clock 校验。
- `tests/work_queue/test_schema.py`：QueuedWorkItem、QueueClaim、QueueCompletion、DispatcherTickResult wire payload 通过
  canonical Draft 2020-12 schemas。
- `tests/work_queue/test_mysql_queue.py` 使用真实 MySQL 专用测试库：exact enqueue replay、wrong owner、
  start、renew、atomic close+next enqueue、completion replay/conflict、wait/make_ready、retry、expiry
  reaper、旧 owner 拒绝、两个 Dispatcher 竞争只有一个 winner。因为 fixture 会重置整组 queue 表，
  pytest 必须在 fixture 执行前拒绝不带显式测试库命名的 `ASE_TEST_MYSQL_DSN`。
- `tests/work_queue/test_mysql_schema_upgrade.py`：fresh/current idempotence、exact legacy aggregate rename、
  partial/mixed schema 与 incomplete archive fail closed；不依赖真实数据库。
- 合并前运行全量 Ruff、strict Mypy、pytest、offline build 和 `git diff --check`。

## 7. Wrong vs Correct

### Wrong

```python
while True:  # Planner 的模型会话承担常驻循环和 Lease 安全
    work = llm.choose(queue.latest())
    db.update(work, status="RUNNING")
```

### Correct

```python
# Planner 产出规则；无模型依赖的进程监督器重复执行有界 tick。
tick = host.planner_dispatcher(
    demand_builder=build_run_demand,
    worker_id="worker_team_host_001",
).tick(now=clock.now())

if tick.status is DispatcherTickStatus.DISPATCHED:
    worker.execute(tick.claim, owner_token=tick.lease_owner_token)
```

当前 `ase request` 保持同步调用兼容，但内部已接入逐角色 Worker（见 §8）；每次模型执行有真实
claim/heartbeat。外部独立进程 fleet 尚未实现，不得把同步 Supervisor 宣称为独立后台集群。

## 8. Production bounded Worker integration (2026-09-19)

T046 is now the execution boundary for production Delivery role Runs. `RuntimeSession.run_step()` keeps
one existing `RetryingOrchestrator` state machine and returns a typed `RoleRunBoundary` before a second
Coder/QA/Reviewer invocation. A trusted `QueuedDeliverySupervisor` must admit the exact Task/allocation,
claim the exact `(task_id, role, attempt, checkpoint_sequence)` item, start/renew the owner-fenced Lease,
and complete the item only after the existing Task transition gate accepts the sealed Artifact.

The deterministic prelude may write the existing Plan and move the Task to its current role checkpoint
before the first queue item is admitted; it must not call a delivery model or create a delivery Context
without a claim. The queue is not a verdict authority. Only accepted Artifact receipts bound to
`work_item_id + lease_id + dispatch_sequence + run_id + context_manifest_id + source_revision` are
eligible for restart recovery; filesystem Artifacts without that receipt remain inspectable evidence and
are not selected by the Worker recovery store.

Production admission is explicit and immutable. The first queue item and the `RoleQueueAdmission` are
published under the shared dispatch-authority then WorkQueue lock order. Legacy native dispatch
records remain immutable for audit and role independence; once a Task is adopted, its ordinary
delivery reservations are excluded from live capacity. Independent candidate-verification reservations
are not migrated and retain their active capacity until completion/abandonment/expiry. Queue claims
include these reservations and the unadopted native reservations. WorkQueue claim validation rejects a
second active claim for the same Task even when two different WorkItems are presented.

Lease ownership is checked on the same MySQL Task mutation transaction through the bound cursor before
`record_attempt` and StateEvent writes. Provider execution receives the trusted execution guard; Codex
subprocesses inherit the Task lock, are terminated on lost ownership, and cannot finalize a candidate
after the guard fails. A dirty or uncertain worktree is retained for explicit recovery and is never
silently reused by a replacement Worker.

Knowledge gaps have two replay-safe windows: if a durable gap/route exists but the first wait was lost,
an active owner retries the exact `QueueKnowledgeWaitPort`; if the wait was already committed, the
queue item remains waiting until an integrity-checked resolution calls `make_ready`. Neither window
changes the Task verdict or fabricates a new claim. The supervisor is currently called by the existing
bounded Console/Manager operation; no independent fleet or same-Task parallelism is introduced.

### 8.1 Signatures and persistence

```python
RuntimeSession.run_step(task_id: str, control: BoundedRunControl) \
    -> RuntimeRunResult | RoleRunBoundary
MySqlRoleQueue.admit(admission: RoleQueueAdmission, step: QueuedRoleStep) -> None
MySqlRoleQueue.finish(claim: QueueClaim, token: str, *, next_step: QueuedRoleStep | None,
                      now: datetime, guard: Callable[[], None] | None = None) -> QueueCompletion
ApprovedRoleDispatch.validate_routes(role: AgentRole, routes: tuple[ProviderRouteConfig, ...]) -> None
```

The additional tables `work_queue_admissions`, `work_queue_steps`, and
`work_queue_accepted_artifacts` each store `(id PK, task_id, payload_json, sha256)`; row identity and
canonical payload digest must agree. `schemas/role-queue-execution.schema.json` owns their typed
wire contracts. Existing approvals, dispatches, Task events and terminal status are not rewritten.

`finish.now` is the deterministic completion/successor timestamp, not an ownership clock. After taking
the authority lock, check generation, active owner and fresh expiry; check heartbeat guard and locked
expiry again before commit. Failure rolls back close, successor binding and successor enqueue together.
Exact CLOSED replay still validates the original owner and immutable completion content without
requiring the already released lease to become active again.

Primary actor/model identity stays frozen. Explicit fallback routes must be an ordered subset of the
dispatch's exact `ModelSelection.policy_id/policy_version` routes, with the primary first and matching
reasoning effort. Legacy effort=None may resolve only one unambiguous configured route. The claim
expresses the primary; immutable `ModelRouteAttempt` records express actual provider attempts.
New settings cannot add/reorder routes on a retained dispatch. Recovery may narrow allowed routes.

### 8.2 Validation and error matrix

| Fact | Result |
|---|---|
| Expired/released lease, changed generation or lost heartbeat | `QueueLeaseLost`, both `QueueConflict` and `DeliveryQueuePending`; preserve checkpoint/worktree |
| Wrong token, another Task, immutable receipt drift | ordinary `QueueConflict`; never treat authorization failure as resumable lease loss |
| Expiry during lock wait or completion SQL; heartbeat lost before commit | rollback completion and next-step publication |
| Artifact accepted before Task transition | resume from accepted receipt under original validation, no repeated model call |
| Task advanced before queue finish | reconcile old item, separately claim next role |
| Knowledge route durable but wait uncommitted | reapply exact wait using the new valid owner |
| Knowledge wait committed without approved resolution | no model call/Task mutation; stay waiting |
| Interrupted/waiting supervisor | retain even clean worktrees, so surviving branch can be reopened |
| Independent verification active | original reservation still counts against Worker capacity |
| New/reordered fallback or ambiguous legacy effort | reject before constructing route clients |

### 8.3 Good / Base / Bad, tests and operations

- Good: lease loss returns recoverable pending, a new claim reopens the same worktree and reaches
  DONE through separate QA/Reviewer claims. Base: legacy terminal evidence is read without adoption.
- Bad: catch every QueueConflict as temporary, or use queue CLOSED as evidence of QA PASS.
- Wrong: remove all clean worktrees in `finally`; the interrupted Coder branch survives but cannot be
  recreated. Correct: clean only on a normal terminal result, retaining interrupted execution state.
- `test_worker_mysql.py`: role retry/progress/QA failure, accepted receipts, owner fencing, both crash
  windows, knowledge wait/resume, capacity handoff, heartbeat and lock/completion expiry rollback.
- `test_owned_execution.py`: subprocess loss termination, typed startup error, candidate not committed
  after ownership loss, per-Task process exclusion; `test_route_binding.py`: frozen route contract.
- Production-style test adapters must bind Artifact producer to the actual AgentDefinition, as real
  Codex/Responses adapters do; generic `agent_coder_001` templates are not valid under a team claim.
  Keep wrong-producer rejection and native progress/budget/recovery assertions, rather than weakening
  the ownership gate to accommodate a fixture.
- Production backend/joint e2e must observe real RUNNING claims and final receipts; live reader/DOM
  must preserve lease-vs-Task status distinction.
- Rollout, existing-data recovery and rollback: `docs/t046-worker-operations.md`. Never execute adopted
  nonterminal Tasks with the old binary or delete admission/history to bypass this boundary.

### 8.4 Bug analysis: lease checks are transaction boundaries, not timestamps

1. **Root cause (B/D/E)**: lifecycle code reused the timestamp captured before acquiring SQL locks as
   proof of current ownership. The local heartbeat check was only before the call; expiry or a failed
   renewal during completion could still publish CLOSED and the successor.
2. **Why partial fixes missed it**: owner token/generation checks reject a replacement owner, but do
   not prove the original lease is still alive after waiting. A post-return check is also too late
   because the transaction has already committed. Ordinary fast happy-path tests never crossed expiry.
3. **Prevention (DONE)**: separate deterministic event time from the trusted live ownership clock;
   check the locked expiry and heartbeat guard immediately before commit. Three injected-time MySQL
   tests verify rollback of the current item, lease release, step receipt and next-item publication.
4. **Systematic expansion**: accepted-artifact and Task-mutation transactions already recheck before
   commit; candidate finalization and subprocess execution use the same ownership guard. Exceptions
   must preserve worktrees, and recoverable lease loss must cross the production guard without being
   reclassified as a terminal invariant failure. Ordinary wrong-owner errors remain fail closed.
5. **Knowledge capture**: the signatures/matrix/tests above and production-team-host/live-team-view
   contracts document the behavior. There is no generic guides/template mirror in this repository;
   preserve this rule in the owning core spec. No production data rewrite is needed.
