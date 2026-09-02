# T032 Implementation

## 已实现

- [x] 新增 `ase project start/reply/approve/resume/status` 与
  `UnifiedProjectEntryService`，每次业务接单只要求绝对项目目录和需求；
- [x] 新增 provider-neutral `ProjectDeliveryBackend` 与 application-host binding seam；宿主未配置时
  CLI 稳定 fail closed，不静默使用 fake Agent；
- [x] 新增 immutable `ProjectDeliveryIntake` 和 append-only `ProjectDeliveryCheckpoint` hash chain；
  PREPARING/Product-start 中断、intake-first 中断、重复 start 和 fresh-process resume 均从首次事实恢复；
- [x] reply/approve 使用 exact current checkpoint fence；stale approval 保证 zero effects；
- [x] backend 可把预期 provider/policy/output 错误分类为 `DeliveryBackendFailure`，facade 只持久化
  typed code 与安全摘要；未分类进程中断保留当前 checkpoint；
- [x] 新增 `DispatchTaskMaterializer`，从 `DispatchCommitRecord` exact-create-or-compare NEW Task，
  immutable collision fail closed；
- [x] 新增 `ExecutionPlanAgentAdapter`，把 approved organization ExecutionPlan 确定性转换为 Delivery
  PlanArtifact，不再次规划；
- [x] 新增严格 Git worktree recovery 和 `DispatchRoleWorktreeCoordinator`：校验 exact
  Agent/model/provider/Assignment/Lease；Coder 使用 frozen base SHA，QA/Reviewer 使用同一 candidate
  SHA 的独立 detached worktree，dirty evidence 不清理；
- [x] 增加 CMake/C++ fixture；Python、Java、C++ 从目录+需求通过 Product approval 到 DONE，目标项目
  文件保持不变；已有 Go/TypeScript delivery matrix 继续通过；
- [x] 同步 README、CLI/Runtime/Contracts/Git/Orchestration 文档、Trellis executable contract 与阶段
  archive。T033 保持暂停。

## 验证

- [x] `tests/cli tests/e2e`：27 passed；
- [x] `tests/git tests/role_workspace`：46 passed；
- [x] 全量 pytest：604 passed；
- [x] Ruff check：all checks passed；
- [x] Ruff format：384 files checked；
- [x] strict Mypy：207 source files, no issues；
- [x] offline sdist/wheel build：成功，产物验证目录为 `/tmp/ase-t032-dist`；
- [x] `git diff --check`：通过。

pytest 唯一警告是当前受限 workspace 无法写 `.pytest_cache`，不影响测试执行或结果。

## 当前边界

- T032 的验收是 provider-neutral application facade + deterministic fake-team offline E2E；仓库不会
  为生产默选模型、凭据或 fake Agent；
- application host 必须一次性绑定实际 organization-owned team composition；现有 delivery
  `OpenAICompatibleAgentAdapter` 只产出 typed artifact，真实模型通过受控工具修改任意项目仍需实用化
  阶段继续装配；
- 不自动 merge/deploy，不启动 daemon，不引入单 Task DAG、消息队列或向量库；
- T033 Reporter 按用户决定暂停，未执行。
