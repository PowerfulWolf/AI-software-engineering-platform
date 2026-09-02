# T031 Designer、Planner 与原子 Dispatch

## 阶段目标

在 T030 已批准 ProductSpec 之后补齐正式交付前的两个组织岗位和调度授权边界：Solution Designer
将 approved product truth 变成可验证 TechnicalDesign；Planner 将 design 变成抽象 ExecutionPlan，
并用 Scheduler/ModelRouter 做只读可行性预演；只有 Project Manager 使用提交时当前事实重算成功后，
才把 NEW Task 与三个 delivery role 的分配作为一个原子 bundle 保存。

## 已完成

### Solution Designer

- 新增 `ai_software_engineer.design` package：Task-free DesignContext、fail-closed permissions、
  provider-neutral Designer adapter、deterministic fake、application service 和 append-only records；
- `RunDesignerCommand` 携带完整 ProjectPreparation、ProjectProfile、ProjectSpecBaseline、当前
  ProjectRequestRevision、approved ProductSpec/Approval 与 exact SOLUTION_DESIGN authorization；
- Designer 只能输出 TechnicalDesign，不能写代码、运行 shell、修改 Product/Approval、创建 Delivery
  Task 或推进项目 stage；adapter timeout/provider/invalid output 都是不带 design 的 typed failure；
- TechnicalDesign 必须绑定 exact approved ProductSpec，并精确覆盖全部 requirement/acceptance IDs；
- 成功时追加 `ProjectRequestStatus.PLANNING` revision，不覆盖 T030 的 DESIGNING revision。

Designer 的完成点不是“design 文件存在”，而是：

```text
DesignRunRecord journal
  → PLANNING ProjectRequestRevision（expected-predecessor CAS）
  → TechnicalDesign
  → exact read-back
  → DesignCommitCheckpoint
```

同一 run 在 journal 后中断时可恢复缺失 revision/checkpoint，且不重复调用 Designer adapter 或
Project Manager stage advancer。只有 checkpoint 存在才表示 Planner handoff 完整。

### Planner 与 read-only preview

- 新增 `ai_software_engineer.planning` package：PlannerContext、least-authority permissions、
  adapter/fake、`PlannerStageService`、`PlanningPreview` 和 preview service；
- Planner context 精确绑定 PLANNING revision、ProductSpec/Approval、TechnicalDesign、Designer
  checkpoint 与 planning authorization，不伪造
  Delivery Task；ExecutionPlan 固定 `Coder → QA → Reviewer`，只声明 capability、risk、minimum
  BrainTier 和 checkpoints，不携带 concrete Agent/model/provider/Assignment/Lease；
- `PlannerStageService` 先写包含唯一 plan/READY effects 的 durable run receipt，再用 CAS 追加
  `READY_FOR_DELIVERY` ProjectRequestRevision、发布 ExecutionPlan 和 Planner checkpoint；fresh-process
  replay 不再次调用 adapter，也不能产生第二个 version-1 plan；checkpoint 写入和读取都会重建并
  核对 exact durable run，因此 orphan 或 forged checkpoint 不能成为 Planner 完成事实；
- `PlanningPreviewService` 只持有 pure `PortfolioScheduler` 与 `ModelRouter`，没有 store write port；
  它根据 NEW derived Task、READY WorkItem 和当前 workforce/model facts 生成有期限、带 digest 的
  `PlanningPreview`；
- preview 内的 Assignment/Lease/ModelSelection 只是建议 evidence。capacity 或 model route 不可行时
  返回 typed rejection，zero store writes。

### Project Manager commit-dispatch

- 新增 `ProjectManagerDispatchService.commit_dispatch(CommitDispatchRequest)`；输入包含完整 stage chain、
  exact durable READY revision、Planner run/plan/checkpoint、DELIVERY_DISPATCH authorization 和 preview；
- current workforce/model facts 由 `DispatchAuthority` 读取，不允许调用方自报；phase demand 由 Task +
  ExecutionPlan 机械派生；
- commit 重新派生 NEW Task，检查 preview time window、Task/WorkItem/ExecutionPlan/demand lineage 和
  workforce snapshot digest，再对三个 phase 重新调用同一 Scheduler/ModelRouter；
- commit-time Agent 与 model semantics 必须和 preview 一致，且满足 capacity、independent review 和
  minimum BrainTier；任一 phase 拒绝时不会调用 store；
- 全部成功后再次检查 READY 与完整 Planner handoff，并只调用一次
  `DispatchAuthority.commit_if_current`。生产 `SqliteDispatchAuthority` 先持有所有 Product revision
  writers 共用的 fence，再以 `BEGIN IMMEDIATE` 在共享 workforce reservation 事务中 CAS snapshot，
  保存包含 NEW Task 与
  `(RoleAssignment, TaskLease, ModelSelection) × 3` 的 `DispatchCommitRecord`；
- 两个 authority 实例竞争同一资源时只有一个提交点可以生效；READY revision 不能在 Planner
  handoff 重验和资源提交之间插入，消除了 double-read 后仍存在的 TOCTOU；
- `FileDispatchCommitStore` append-only、exact replay，并通过 canonical digest envelope、dirfd、
  `O_NOFOLLOW`、write-all、exclusive hard-link 与 root/directory inode 检查拒绝篡改、short write、
  collision 和 path/symlink race。

## 关键不变量

1. Designer/Planner 是 organization roles，不进入 Delivery `AgentRole` 或现有 Task state machine。
2. Product approval、TechnicalDesign、ExecutionPlan、preview 和 dispatch 必须沿同一 project/request
   lineage 串联；不能从 Agent 隐式会话补字段。
3. ExecutionPlan 只有抽象 demand；PlanningPreview 是建议 evidence；只有 Project Manager 当前事实
   重算后的 DispatchCommitRecord 才是具体分配 bundle。
4. Coder、QA、Reviewer 必须是三个不同 Agent，且前一 phase 的 candidate Lease 在同次计算中立即
   占用 capacity。
5. 任一 preview/commit phase 不可行时，必须 zero partial writes；不能先写两个角色再等待第三个。
6. Agent 调用窗口后必须重验 current revision；dispatch routing 前后及 authority transaction 内都
   必须验证 exact durable READY revision/Planner run/plan/checkpoint，最终 workforce allocation 使用
   Product revision fence + SQLite CAS。

## 验证范围

- Designer：完整 project knowledge context、permission widening、adapter terminal behaviors、run conflict、
  exact Product lineage/coverage、PLANNING revision、journal/checkpoint 中断恢复、store tamper/symlink；
- Planner：Task-free context、permission boundary、adapter replay/failure、abstract plan rejection、
  READY_FOR_DELIVERY revision、plan/revision 中断 exact retry；
- Preview：determinism、collection-order canonical digest、phase demand binding、capacity/model refusal、
  zero store dependencies；
- Dispatch：current-fact rerun、expired/drift preview、commit-time capacity/model refusal、三角色独立、
  orphan/fabricated/stale Planner handoff、跨实例 workforce CAS、READY cross-domain fence、single-call atomic store、exact
  replay/conflict/tamper。

合并基线的最终 targeted/full pytest、Ruff、strict Mypy、offline build 与 diff check 结果由本阶段
integration commit 和 `.trellis/tasks/09-02-t031-designer-planner-skills/implement.md` 记录。

## 当前边界与下一阶段

T031 交付的是 Python application seams、deterministic fakes、canonical JSON Schemas 和外置 sidecar
append-only records。
`DispatchCommitRecord` 当前是 NEW Task + allocations 的原子 bundle，尚未直接写 TaskRepository、启动
现有串行 Delivery runtime，也不 merge/deploy。Planner stage 的 plan/revision 恢复依赖 durable
run receipt/checkpoint，而不是 adapter 内存或“再次生成同样结果”；跨进程边界必须使用
Designer/Planner context/run、preview 与 dispatch 的正式 Schema，不接受裸 payload。

T032 将把 prepare、Product confirmation、Design、Plan、preview、dispatch 与现有 Delivery runtime
组成“项目目录 + 需求”的统一、可恢复入口。T033 暂不执行。

本记录随 T031 集成提交归档；精确提交可通过
`git log -- docs/archive/2026-09-02-t031-designer-planner-dispatch.md` 查询。
