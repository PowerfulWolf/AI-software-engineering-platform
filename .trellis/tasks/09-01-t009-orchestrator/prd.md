# T009 — Serial Orchestrator Happy Path

## Goal

把现有 Task 状态机、SQLite repository、ArtifactStore、Context Builder 和
FakeAgentAdapter 串成第一个可审计的应用层闭环，使一个 fixture Task 以单次 attempt
依次完成 `NEW → PLANNING → IMPLEMENTING → QA → REVIEW → DONE`。

## Requirements

- 提供 `SerialOrchestrator.run_task(task_id) -> DeliveryResult` typed seam；CLI、模型
  SDK 和具体供应商不得进入该服务。
- 每个角色运行前构建 role-scoped ContextBundle，并把 manifest ID、权限、输入
  Artifact IDs、输入 revision、输出 Schema 和 timeout 写入 AgentRequest。
- 只接受 Orchestrator plan、Coder implementation-report、QA PASS、Reviewer APPROVE；
  所有 Artifact 必须 seal 后通过 ArtifactStore 持久化，再供下游读取。
- 每个状态变化都通过 `build_event` 和 TaskRepository 提交；`DONE` 事件必须引用
  同一交付链上的四类 Artifact。
- Coder request 的 `source_revision` 表示输入基线；Coder 输出的
  implementation-report 可以指向新的 candidate revision，但 `content.commit_sha`
  必须与 Artifact `source_revision` 完全一致。QA/Reviewer 仍必须与 candidate 完全一致。
- 校验 Task acceptance criteria 在 plan、implementation-report 和 qa-report 中完整覆盖，
  校验 Artifact task、role、run、kind、context、parent lineage 与独立 run identity。
- T009 对 Agent failure、QA FAIL、Review REJECT fail closed 并停止在当前 checkpoint；
  retry、BLOCKED 路由和中断恢复留给 T010。

## Acceptance Criteria

- [ ] 一个真实 SQLite repository + 文件 ArtifactStore + FakeAgentAdapter fixture 通过
  `SerialOrchestrator.run_task` 到达 `DONE`。
- [ ] repository 持久化 5 个顺序事件，最终 revision 为 5；重新打开数据库后仍可读取
  `DONE` 快照和完整事件流。
- [ ] ArtifactStore 持久化 plan、implementation-report、qa-report、review-report，且
  lineage 为 `plan → implementation → qa → review`。
- [ ] 四次 Agent Run 使用唯一 run ID、四个确定性 Context Manifest，并按角色只接收
  允许的上游 Artifact。
- [ ] Coder 可从 base revision 产出新的 candidate；QA 与 Reviewer 只能审查同一 candidate。
- [ ] 缺角色定义、Agent failure、非法 verdict、criterion 缺失、revision/context/lineage
  不一致都产生 typed orchestration error，不能推进下一状态。
- [ ] Ruff、strict mypy、完整 pytest、lock、build 和 diff checks 全部通过。

## Out of Scope

- QA FAIL/Review REJECT 重试、attempt 计数持久化、中断恢复、真实模型 adapter、真实 Git
  candidate 检查、并行/DAG、队列、向量库、自动 merge 或部署。

## Rollback

回退单个 T009 commit；T009 不迁移 SQLite schema，不修改已有 Artifact wire schema，也不合并
或清理任何候选 worktree。
