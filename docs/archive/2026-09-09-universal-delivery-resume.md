# T047：Universal delivery resume

## 阶段目标

把 Product、Designer、Planner、dispatch、Coder、QA、Reviewer 与多仓联合交付的恢复收敛为一个
Project Manager 入口：`ase request resume DELIVERY_ID`。一个已经 admitted 的 Agent Run 仍坚持
at-most-once；Delivery 通过新计划、新 Run 或新 Task 向前继续，不改写旧终态。

## 已完成能力

- pre-Task 失败在 checkpoint 中记录 `failed_stage`，恢复时精确重入该阶段并复用前序封存产物；
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

## 验证证据

- Ruff format/check：通过；
- Mypy strict：`src + tests` 共 319 个文件通过；
- 离线 pytest：965 passed；
- 真实 Git + MySQL pytest：47 passed；
- 合计：1012 passed；
- `UV_CACHE_DIR=/private/tmp/ase-uv-cache uv build --offline`：sdist 与 wheel 构建成功。

真实 MySQL 回归包含：失败 Coder 自动发现与恢复批准、恢复 Coder 再失败后的第二轮恢复、
RATE_LIMITED verifier successor plan、QA FAIL 到 Candidate V2、process-loss 后终态 Task 接管、
joint child 保留、验证工作与精确 QA Run 的看板投影。测试全部使用离线 scripted model，没有消耗
真实模型额度。

## 当前边界

- provider 已 admitted、Task 尚未形成可信终态的歧义窗口返回 `WAITING_HUMAN`，不会盲目重调；
- Dashboard 的 execution liveness 仍是 `UNKNOWN`；逐角色常驻 Worker/SSE 在线状态另行立项；
- Reporter、自动 merge/push/deploy 不属于 v0.1，本阶段只交付候选 commit 和可审计证据。

Git 基线：本记录所在提交。
