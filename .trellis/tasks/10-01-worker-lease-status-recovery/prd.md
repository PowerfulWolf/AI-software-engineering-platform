# 恢复任务执行与当前状态

目标：继续 ai-project K1 的原生交付，并保证 Requirement、Task、成员和 Manager 提示反映相同的当前事实。

## 已复现问题

- 恢复计划 `48183639b355e838eb1d26e265d2f00ad34fd3088e1267a6482372db8fb76c40` 已批准且新 Task IMPLEMENTING。
- Worker 心跳止于 2026-10-01T00:49:37Z，租约 00:50:37Z 过期，Operation 因 QueueLeaseLost 失败。
- API 仍返回 DELIVERING；旧 Manager PROPOSE_RECOVERY 被页面解释为“等待恢复审批”。

## 范围与允许路径

`team_view/{reader.py,queue_reader.py,app.js}`、`work_queue/`、`agents/execution.py`、`knowledge/runtime.py`、`manager/production_backend.py`、必要的 `recovery/` 恢复边界、`web_console/{manager.py,models.py}`、`scripts/ase-console-service.sh`，以及对应 tests、schemas、docs、Trellis 规范。只按证据扩展实现范围。

## 验收

- 活动 successor 覆盖旧诊断；DONE/CLOSED 不显示旧审批阻塞。
- PROPOSE_RECOVERY 不等于真实待审批；只展示当前 exact checkpoint 的审批。
- 已过期 RUNNING 租约显示执行中断，保留 Task IMPLEMENTING checkpoint，不伪造终态或在线状态。
- 续约问题有可重复的增量测试；不通过延长 TTL 掩盖未证实原因。
- 通过原生队列/恢复继续现有 Task 或精确批准的安全 successor；保留 8 文件与所有历史。
- 独立 QA、Reviewer 验证；仅跑相关增量测试。

## 存量与回滚

不直接改生产数据库、审批、Task 或 verdict。投影修复只需重启/刷新。执行恢复须校验 invocation、route、worktree、claim 后使用平台入口。回滚代码时保留现有 facts 与 worktree；不删除新审计记录。
