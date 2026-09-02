# T028 Project Manager Stage Contracts

## 阶段目标

把产品从“Task 已经带验收标准才可运行”推进到完整团队接单前置链，并按最新组织模型统一为：

```text
组织通用知识库 + 项目 sidecar + organization-owned Agent Team + policy-bound Skills
```

Project Manager Agent 是团队领导；Product、Solution Designer、Planner、Coder、QA、Reviewer 与可选
Reporter 是组织成员。Scheduler/ModelRouter 作为确定性 engines 暴露给 Planner read-only preview
Skills，并由 Project Manager `commit_dispatch` Skill 在提交分配前重新校验。

## 已完成

- `ProjectPreparation`、`ProjectRequest`、`ProductSpec`、`ProductSpecApproval`、`TechnicalDesign`、
  `ExecutionPlan` frozen Pydantic contracts 与七份 Schema；
- exact ProductSpec 用户确认门禁：Agent 无法自批，REQUEST_CHANGES/旧 digest/跨 Request 均拒绝；
- Design requirement/acceptance exact coverage；
- v0.1 ExecutionPlan 固定 Coder→QA→Reviewer，禁止 concrete Agent/provider/model/Lease；
- `derive_delivery_task` 重验完整 lineage，把 ProductSpec acceptance criteria 原样投影到 NEW Task；
- 当前 sidecar assignments 架构成为唯一初始 layout v0.1，不保留项目尚未使用时无意义的 legacy
  migration contract；
- T029–T033 已拆成 Project Manager Skills、Product Agent、Designer/Planner、统一入口和 Reporter。

## 关键不变量

1. Agent Skill 是 typed/policy-bound facade，authority 在 deterministic service/policy/store，不在 prompt；
2. Planner 可以预演但不能提交自己的资源方案；Project Manager commit 必须按当前 facts 重算；
3. 用户批准、产品定义、技术方案、执行计划和 Delivery Task 都通过 immutable hash lineage 连接；
4. 目标项目只作为代码 cwd，所有 AI 元数据仍位于外置 sidecar/organization workspace；
5. 单 Task 继续串行 Coder→QA→Reviewer，不引入 DAG、向量库、后台队列或自动 merge。

## 验证

- 393 tests passed；
- Ruff check/format passed；
- strict Mypy：145 source files passed；
- offline sdist/wheel build passed；
- `git diff --check` passed。

## 下一阶段

T029 实现 `prepare_project` 等 Project Manager Agent Skills 与 project-level baseline compilation；
T030 接 Product Agent 和用户确认循环；T031 接 Designer/Planner preview + Project Manager commit；
T032 提供“项目目录 + 需求”的统一入口与跨语言 E2E；T033 再决定 Reporter 是否需要生成式 Agent。

本记录随 T028 集成提交归档；精确提交可通过 `git log -- docs/archive/2026-09-02-t028-project-manager-stage-contracts.md`
查询。
