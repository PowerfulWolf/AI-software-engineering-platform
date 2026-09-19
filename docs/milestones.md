# 当前路线与待验收事项

本页只维护尚未完成或需要重新核实的工作。当前已实现能力见
[README](../README.md)，工程状态见 [任务索引](../.trellis/tasks/README.md)。
原 M0–M9 和首批任务清单保存在 [旧路线快照](archive/2026-09-19-foundation-roadmap-snapshot.md)。

## 当前事项

| 事项 | 已有基础 | 未完成范围与证据 |
|---|---|---|
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
