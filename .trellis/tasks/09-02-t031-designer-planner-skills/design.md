# T031 Design

Planner 是计划 Agent，Scheduler/ModelRouter 是其 read-only preview Skills 背后的 pure engines。
Project Manager `commit_dispatch` 使用同一 engines 重新校验，并通过最小 write ports 保存分配。
Preview 与 commit 使用不同 result types，避免建议被误当授权。

## Public boundaries

### Designer

- `DesignContextManifest` 携带 exact ProjectPreparation、ProjectProfile、ProjectSpecBaseline、
  ProjectRequest、approved ProductSpec/Approval；不复用 Delivery Task context；
- `DesignerAgentAdapter.run(DesignerAgentRequest) -> DesignerAgentResult` 只产出 TechnicalDesign 或
  typed failure；permissions 禁止代码、shell、ProductSpec/Approval 修改和 stage advancement；
- Designer service 校验 exact lineage、requirement/acceptance 全覆盖、adapter identity 和 immutable
  TechnicalDesign store read-back；adapter 后重验 current facts，成功 receipt 通过 CAS 追加
  `ProjectRequestRevision(status=PLANNING)`，不覆盖 Product 阶段的旧 revision。

### Planner preview

- Planner adapter 只产出 abstract ExecutionPlan；plan 固定 `Coder → QA → Reviewer`，只能包含 role、
  capability、risk、minimum brain tier 和 checkpoints，禁止 agent/model/provider/lease；
- `PlannerPreviewService.preview(...) -> PlanningPreview` 对 derived Task/WorkItem 的三个 phase 调用现有
  `PortfolioScheduler.match` 和 `ModelRouter.route`；preview store port 不存在，服务不得写任何 store；
- Planner 成功先保存包含唯一 plan/READY effects 的 durable receipt，再通过 CAS 追加
  `ProjectRequestRevision(status=READY_FOR_DELIVERY)`、plan 与 checkpoint；只有这一 exact handoff 可派生 Task；
- `PlanningPreview` 保存 plan digest、task/work-item identity、canonical workforce input digest、
  previewed_at/valid_until 和每 phase 的 typed AssignmentDecision/ModelRoutingDecision。它是建议 evidence，
  不是 Assignment/Lease/ModelSelection 授权。

### Project Manager commit-dispatch

- `ProjectManagerDispatchService.commit_dispatch(request) -> DispatchCommitRecord` 接收 exact stage chain、
  durable READY revision/Planner run/plan/checkpoint 和 PlanningPreview；current workforce facts 由 authority 读取；
- commit 先校验 preview 未过期、stage/plan/task lineage 和 current workforce digest，再以 commit time
  重新调用同一 Scheduler/ModelRouter；任何 phase refusal、preview drift、自我分配或容量不足都不能写；
- 三个 phase 全部成功并二次验证 READY/Planner handoff 后，才通过一个原子
  `DispatchAuthority.commit_if_current(record, expected_snapshot_sha256=...)` CAS 保存
  `Task + (RoleAssignment, TaskLease, ModelSelection) × 3`。store 采用 append-only exact replay，
  changed identity/tamper fail closed；生产 SQLite authority 在 Product revision fence 内提交，避免
  READY head 与资源占用之间的 TOCTOU；不直接运行 Delivery Task。

## Validation matrix

| Case | Required result |
|---|---|
| ProductSpec 未 APPROVED、design coverage/lineage 错 | Designer fail closed，无 design |
| Designer/Planner adapter identity 或 output 错 | typed invalid output，无下游 artifact |
| Planner preview | 只返回 evidence；zero store writes |
| ExecutionPlan 含具体分配字段或 phase 顺序错 | model/schema rejection |
| workforce/model route 无可行结果 | typed preview rejection，不伪造 plan feasibility |
| preview 过期或 current facts digest 改变 | commit stale error，zero store writes |
| Planner run/plan/checkpoint orphan、伪造或 routing 中变化 | full durable handoff rejection，zero writes |
| READY/workforce 在 commit fence 变化 | Product fence + authority CAS conflict，zero writes |
| commit 重算与 preview selection 不一致 | stale/drift error，zero store writes |
| all three phases selected | atomic append-only DispatchCommitRecord + NEW Task |

## Good / Base / Bad

- Good：approved ProductSpec → exact TechnicalDesign → abstract ExecutionPlan + feasible preview → Project
  Manager current-fact recheck → atomic three-role dispatch bundle and NEW Task。
- Base：没有满足 context/risk floor 的模型时 preview 返回 typed refusal，用户可更新组织 policy 后重试。
- Bad：Planner 直接写 Assignment/Lease、把 preview 当 authorization、把 agent/model 固化进
  ExecutionPlan，或 Project Manager 按过期 preview 部分写入两个 phase。

## Required tests

- Designer：context/permissions/adapter/service/store 的正反、Schema、replay、coverage、stale lineage；
- Planner：abstract plan、read-only preview、determinism、capacity/model refusal、workforce digest/expiry；
- Dispatch：current-fact rerun、stale preview、self-review、capacity/model refusal、atomic no-partial-write、
  exact replay/tamper 和 derived Task stage chain；
- targeted/full pytest、Ruff、strict Mypy、offline build、`git diff --check`。
