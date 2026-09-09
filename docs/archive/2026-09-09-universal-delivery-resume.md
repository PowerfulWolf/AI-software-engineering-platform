# T047：Universal delivery resume

## 阶段目标

把 Product、Designer、Planner、dispatch、Coder、QA、Reviewer 与多仓联合交付的恢复收敛为一个
Project Manager 入口：`ase request resume DELIVERY_ID`。一个已经 admitted 的 Agent Run 仍坚持
at-most-once；Delivery 通过新计划、新 Run 或新 Task 向前继续，不改写旧终态。

## 已完成能力

- pre-Task 失败在 checkpoint 中记录 `failed_stage`，恢复时精确重入该阶段并复用前序封存产物；
- dispatch 已物化 Task、但 Runtime 在任何 Agent 接纳前停止时，`NEW / revision 0 / 无 candidate /
  delivering=0` 被识别为 Delivery 启动失败并直接重入；兼容未记录 `failed_stage` 的既有 checkpoint；
- Coder 无 candidate 时自动发现最后失败的 Run/Context、捕获保留 worktree，输出精确
  `RecoveryPlan`；批准后创建新 recovery Task 并串行执行 Coder→QA→Reviewer；若 recovery 或
  remediation Coder 再次失败，沿不可变 dispatch 祖先继续生成下一轮恢复 Task；
- Coder 已有 candidate 时生成独立 QA/Reviewer 验证计划；已 admitted 但结果不确定的 Run 不重放，
  后续 resume 生成新的验证计划；
- QA FAIL 或 Review REJECT 生成 digest-bound `ContinuationDispatchRecord`，将 sealed verdict 和受限
  candidate diff 作为新 Coder 必需上下文，产出 Candidate V2；
- recovery/remediation Task 终态早于 Delivery checkpoint 时，从 MySQL events 和 sealed artifacts
  零模型调用重建结果；原 Task、candidate 和 approval 全部保留；
- joint delivery 只恢复未完成子仓，保留 DONE 子仓，候选集合完整后才重新进入联合验收；
- live team view 将 candidate verification 显示为 QA/Reviewer 工作，并显示仓库目录、分配、模型、
  Run、阻塞和报告；continuation 显示为 remediation 工作。

公开恢复命令只接受可选的 exact plan digest + audit reference。低层 `recovery *` 与 `verify-*`
继续存在，但定位为诊断和 break-glass，不再是日常必经步骤。

## 关键不变量

1. Agent Run 至多调用一次；不确定结果不会成为重放同一 Run 的许可。
2. Coder、QA、Reviewer 使用不同 Agent、Context、Run 与隔离 worktree；没有角色独自裁决自己的工作。
3. 计划、批准、dispatch、invocation、verdict、checkpoint 与 Artifact 都是 digest-bound 组织事实。
4. source/preparation/policy/knowledge/candidate 漂移一律 fail closed，不静默放宽规范。
5. `resume` 不 merge、不 push、不 deploy，也不修改目标项目主 checkout。
6. 只有完整的 pristine Task 事实集合可以推断“尚未接纳 Agent”；已有 Task 进度、candidate 或
   Delivery attempt 继续走原生 Task 接管或失败 Coder 恢复，不能靠旧 checkpoint 猜测。

## 验证证据

- Ruff format/check：通过；
- Mypy strict：`src + tests` 共 319 个文件通过；
- 离线 pytest：967 passed；
- 真实 Git + MySQL pytest：47 passed；
- 合计：1014 passed（由操作者执行完整回归确认）；
- `UV_CACHE_DIR=/private/tmp/ase-uv-cache uv build --offline`：sdist 与 wheel 构建成功。

真实 MySQL 回归包含：失败 Coder 自动发现与恢复批准、恢复 Coder 再失败后的第二轮恢复、
RATE_LIMITED verifier successor plan、QA FAIL 到 Candidate V2、process-loss 后终态 Task 接管、
joint child 保留、验证工作与精确 QA Run 的看板投影。测试全部使用离线 scripted model，没有消耗
真实模型额度。

后续真实使用发现一个恢复分类缺口：dispatch 已发布且 Task 已物化，但 Runtime composition 在
Coder admission 前失败。旧 controller 只对 `task_id=null` 尝试阶段重入，随后把这个 pristine
Task 误送到失败 Coder 恢复并报“identity missing”。修复以一条可复现的 controller 回归锁定当前与
旧 checkpoint 两种形态；根因是“Task 已存在”被错误等同于“Coder 已运行”。

## Bug Analysis：pristine Task 被误判为失败 Coder

### 1. Root Cause Category

- **B — Cross-Layer Contract**：Delivery checkpoint、MySQL Task 与 Agent Run 三类事实之间缺少
  “已物化但尚未 admission”的显式分类；controller 用 `task_id` 是否存在替代了运行事实。
- **D — Test Coverage Gap**：已有测试覆盖 pre-Task 失败与 Coder 失败，但没有覆盖两者之间的
  Runtime composition 窗口。
- **E — Implicit Assumption**：默认 Task 的存在意味着 Coder identity 必然存在。

### 2. Why Earlier Coverage Failed

单元路径分别证明了 dispatch materialization 和失败 Coder recovery，却没有通过公共 controller
组合两层；新 `failed_stage` 也无法自动修复历史 checkpoint 中缺失该字段的问题。

### 3. Prevention Mechanisms

| Priority | Mechanism | Action | Status |
|---|---|---|---|
| P0 | Runtime classification | 只凭 `NEW + revision 0 + no candidate + delivering 0` 完整事实集合判定未 admission | DONE |
| P0 | Public-path regression | controller 同时覆盖当前与 legacy checkpoint，并断言 recovery/verification 零调用 | DONE |
| P1 | Executable spec | 在恢复矩阵中单列 Task materialization 与 Agent admission 的边界 | DONE |

### 4. Systematic Expansion

后续增加任何恢复分支时都必须区分“业务对象已创建”“运行已接纳”“运行已完成”三个时点。不得以
Task、Assignment、Lease 或 route 文件中任一单独存在来推断其他事实；先走可重放的原生 Runtime
reconciliation，再决定是否需要 recovery plan。

### 5. Knowledge Capture

- `.trellis/spec/core/delivery-recovery.md` 已加入契约、验证矩阵、Good/Base/Bad 和测试点；
- 本项目没有 `src/templates/markdown/spec/`，因此没有可同步的规范模板；
- README 已补充操作者可见的恢复行为。

完整回归还暴露了一个测试环境隔离问题：
`test_missing_production_config_fails_without_traceback` 曾继承操作者真实 `ASE_CONFIG`，使“缺少配置”
场景可能实际启动生产 Host。该测试现在将 `ASE_CONFIG` 显式绑定到临时不存在文件；测试不得依赖
开发者是否已为日常平台运行配置环境变量。

## Bug Analysis：追加式 child checkpoint 被误判为事实漂移

### 1. Root Cause Category

- **B — Cross-Layer Contract**：联合父 checkpoint 保存的是 child 的已提交观察值，原生 child journal
  保存的是持续追加的当前事实；read/recovery 层错误地把二者当成同一个 mutable latest pointer。
- **D — Test Coverage Gap**：已有测试覆盖相等 checkpoint 和损坏 checkpoint，没有覆盖“父记录合法
  落后、child 已继续”的正常恢复窗口。
- **E — Implicit Assumption**：用 latest digest equality 代替了 append-only ancestry 校验。

### 2. Why Earlier Coverage Failed

单仓恢复、联合交付和看板各自测试都能通过，但没有让 child 在父 checkpoint 发布后继续追加。
因此原生恢复已经产生了正确新事实，看板和联合来源校验却同时拒绝该事实；验证计划又因绑定瞬时
Delivery checkpoint 摘要而被无意义作废。

### 3. Prevention Mechanisms

| Priority | Mechanism | Action | Status |
|---|---|---|---|
| P0 | Shared ancestry predicate | 统一使用 exact record-at-sequence 判断 checkpoint 是否属于当前已验证链 | DONE |
| P0 | Cross-layer regressions | 覆盖 joint parent lag、native recovery lineage 和 verification plan continuity | DONE |
| P1 | Executable spec | 明确 committed observation 与 mutable latest pointer 的区别及拒绝矩阵 | DONE |

### 4. Systematic Expansion

所有 append-only 聚合之间的引用都要先判断语义：如果引用代表“当时观察到的事实”，比较 ancestry；
如果引用代表“不可再变化的完成结果”，比较 exact latest。不得默认把跨聚合引用实现成 latest equality。

### 5. Knowledge Capture

- `.trellis/spec/core/live-team-view.md`、`multi-directory-delivery.md`、`delivery-recovery.md` 已同步；
- `docs/contracts.md` 已补充操作者可见行为；
- 本项目没有 `src/templates/markdown/spec/`，因此没有可同步的规范模板。

## 当前边界

- provider 已 admitted、Task 尚未形成可信终态的歧义窗口返回 `WAITING_HUMAN`，不会盲目重调；
- Dashboard 的 execution liveness 仍是 `UNKNOWN`；逐角色常驻 Worker/SSE 在线状态另行立项；
- Reporter、自动 merge/push/deploy 不属于 v0.1，本阶段只交付候选 commit 和可审计证据。

Git 基线：本记录所在提交。
