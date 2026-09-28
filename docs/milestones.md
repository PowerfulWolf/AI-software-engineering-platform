# 当前路线与待验收事项

本页只维护尚未完成或需要重新核实的工作。当前已实现能力见
[README](../README.md)，工程状态见 [任务索引](../.trellis/tasks/README.md)。
原 M0–M9 和首批任务清单保存在 [旧路线快照](archive/2026-09-19-foundation-roadmap-snapshot.md)。

## 当前事项

2026-09-28 更新：当前真实需求已由 ASE 完成 DONE；Manager 候选验收协调、Reviewer-only
恢复及项目切换修复已发布到 `v0.1.2`。详细缺陷与边界见
[本轮平台复盘](archive/2026-09-28-ase-delivery-retrospective.md)。后续优先级如下，历史待核实项不自动关闭。

| 事项 | 已有基础 | 未完成范围与证据 |
|---|---|---|
| P1 自动知识收集闭环（下一项） | report observations、显式 collect/批准/发布/前端/后续检索 | accepted checkpoint 自动触发、增量幂等与失败恢复；上游角色和 Manager 经验生产者；[演进任务](../.trellis/tasks/09-25-team-evolution-audit/task.json) |
| P1 Manager 全阶段前提协调 | 候选验证 incident、当前探测、精确提案/审批、执行器与恢复 | 将同一职责贯穿 Product/Design/Planning/Coder，不能宣称当前已通用于所有阶段 |
| P1 通用能力扩展（知识闭环之后） | Swift/UI 受控 adapter，SKILL 设计提案 | 隔离验证、独立评审、版本化注册/授权、监控/回滚；禁止自行扩权 |
| 组合回归与运行质量 | Git/MySQL/CLI/GUI/历史兼容回归已存在 | 分层 CI、其余 CLI 角色权限审计、知识效果追踪、投影延迟与路由健康、依赖弃用；见本轮复盘 |
| 逐角色后台 Worker 集成 | T046 持久 WorkQueue、Dispatcher、Lease | 已接入 bounded RuntimeSession step、真实 claim/heartbeat、Artifact receipt 与 native capacity adoption；独立 supervisor 进程和多 Task 并发仍待单独验收 |
| Reporter | 底层 Evaluation/Handoff | [T033](../.trellis/tasks/09-02-t033-delivery-reporter/prd.md) 暂停，尚未决定独立 Agent 或确定性服务 |
| 显式交付恢复的真实验收 | 已有离线恢复、重应用与候选复核 | [T044](../.trellis/tasks/09-06-t044-explicit-delivery-recovery/task.json) 仍列新精确计划、人工批准与真实 Coder/QA/Reviewer 验证 |
| Requirement 独立源基线验收 | 已记录实现与复核准备 | [任务记录](../.trellis/tasks/09-15-requirement-source-baseline/task.json) 仍要求完整 localhost/MySQL 检查，不因代码已存在而抹掉剩余项 |
| 旧工程记录核实 | PRD/设计/实现正文保留 | [待核实目录](../.trellis/tasks/README.md#legacy-tasks) 尚无完整状态证据；不从文件名推断完成 |

这里列出的运行边界不授权自动执行真实模型、变更审批或放宽平台策略。新的能力先定义范围及验收。

## 历史编号说明

历史“统一恢复”与后来的 Planner 都曾使用 T047。原记录中的编号保留，引用时同时使用唯一目录名：

- 旧统一恢复：[universal-delivery-resume](../.trellis/tasks/universal-delivery-resume/prd.md)，
  [历史归档](archive/2026-09-09-universal-delivery-resume.md)。
- 新 Planner：[09-17-t047-planner-agent-evolution](../.trellis/tasks/09-17-t047-planner-agent-evolution/task.json)。
- Planner、主动知识和增量索引的已完成记录见
  [T047–T049 交付归档](archive/2026-09-19-t047-t049-continuation.md)。

新增任务使用唯一 ID/slug；已接受的旧编号不静默改写。
