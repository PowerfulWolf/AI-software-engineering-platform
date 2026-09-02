# 项目阶段归档

这个目录记录已经完成阶段的事实快照。它回答三个问题：当时完成了什么、通过什么验证、哪些
边界仍然没有完成。

文档职责保持分离：

- 根目录 [`README.md`](../../README.md) 描述当前能力、当前限制和最短使用路径；
- [`docs/milestones.md`](../milestones.md) 描述尚未完成的路线和执行顺序；
- 本目录保存已完成阶段的范围、任务、验证结果和 Git 提交证据。

Archive 是组织记忆的一部分，不依赖任何单个 Agent 的会话。历史事实需要更正时，应保留原始
结论并明确写出更正原因、日期和证据，不能静默改写已经发生的交付记录。

## 归档索引

| 日期 | 基线 | 范围 | 记录 |
|---|---|---|---|
| 2026-09-01 | `3ca68b4` | Bootstrap 至 T017；M0–M4 完成，M5 启动 | [v0.1 Foundation：T001–T017](2026-09-01-v0.1-foundation-t001-t017.md) |
| 2026-09-01 | `400ac04` | T018；组织 Workforce foundation，M5 组织层启动 | [T018 Organization Workforce](2026-09-01-t018-organization-workforce.md) |
| 2026-09-01 | `8d76ce2` | T019–T022；组织调度、项目发现、规范治理与 Runtime binding，M5 完成 | [T019–T022 Organization Runtime](2026-09-01-t019-t022-organization-runtime.md) |
| 2026-09-01 | `02b3183` | T023–T024；Evidence capture、typed tool protocol 与 Runtime evidence roots，M6 执行边界 | [T023–T024 Executable Delivery](2026-09-01-t023-t024-executable-delivery.md) |
| 2026-09-01 | `dff64ab` | T025；Python/Java/Go/TypeScript 任意目标项目串行交付 fixture matrix | [T025 Target Project E2E](2026-09-01-t025-target-project-e2e.md) |
| 2026-09-01 | `0d6f3ed` | T026–T027；事件驱动只读 projection/read API 与静态 dashboard | [T026–T027 Projection & Visualization](2026-09-01-t026-t027-projection-visualization.md) |
| 2026-09-02 | 本记录所在提交 | T028；Project Manager/Agent Skills 架构、Product/Design/Plan contracts 与用户确认门禁 | [T028 Project Manager Stage Contracts](2026-09-02-t028-project-manager-stage-contracts.md) |
| 2026-09-02 | 本记录所在提交 | T029；Project Manager prepare Skill、task-free baseline、Product gate 与阶段授权 | [T029 Project Manager Agent Skills](2026-09-02-t029-project-manager-skills.md) |
| 2026-09-02 | 本记录所在提交 | T030；Product Agent 需求澄清、人工确认、不可变事实与崩溃重放 | [T030 Product Agent](2026-09-02-t030-product-agent.md) |
| 2026-09-02 | 本记录所在提交 | T031；Designer、Planner read-only preview 与 Project Manager 原子 dispatch | [T031 Designer、Planner 与 Dispatch](2026-09-02-t031-designer-planner-dispatch.md) |

## 后续归档约定

一个阶段达到明确退出条件并合入 `main` 后，新增一份带日期的 Markdown 快照，至少记录：

1. 阶段目标和纳入的 Task；
2. 形成的可复用能力与关键不变量；
3. 自动化验证、人工验证和质量基线；
4. feature/integration commit；
5. 已知限制、遗留风险和下一阶段入口。

每个 Task 的详细需求、实现和验证仍以 `.trellis/tasks/<task>/` 为最细粒度证据；Archive 只做
阶段级汇总，不复制或替代 Task artifact。
