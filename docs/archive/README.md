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

## 后续归档约定

一个阶段达到明确退出条件并合入 `main` 后，新增一份带日期的 Markdown 快照，至少记录：

1. 阶段目标和纳入的 Task；
2. 形成的可复用能力与关键不变量；
3. 自动化验证、人工验证和质量基线；
4. feature/integration commit；
5. 已知限制、遗留风险和下一阶段入口。

每个 Task 的详细需求、实现和验证仍以 `.trellis/tasks/<task>/` 为最细粒度证据；Archive 只做
阶段级汇总，不复制或替代 Task artifact。
