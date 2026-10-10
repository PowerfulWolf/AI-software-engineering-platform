# 增量验证

## 回归证据

1. STOPPED + terminal BLOCKED + current exact approval 的最小真实结构先 RED：2 项因标题仍为
   已阻塞失败；基础修复后 Green，受影响 3 文件最初 90 项通过。
2. flow 当前审批、RUNNING 平台恢复、显式 Product/final 确认优先级先 RED：3 项失败；修后
   3 项 Green。
3. 独立 review 发现旧 STOPPED + fresh READY/RUNNING queue 和残留审批 callback 漏项。两个
   current-role 用例及 queued 无旧按钮用例先 RED：3 项失败；共用 decision 门后 6 项对应场景
   Green。既有 stale-read 审批 fixture 从已经派发的 READY 队列改为真正可审批的终态 STOPPED；
   不削弱其读失败/保留 callback/读恢复零自动审批断言。

最终命令（仅增量）：

```sh
node --test --test-reporter=spec tests/team_view/engineering-wait.test.cjs tests/team_view/product-execution.test.cjs tests/team_view/historical-child.test.cjs
node --check src/ai_software_engineer/team_view/app.js
git diff --check
```

结果：**94 passed，0 failed，约 0.25 秒**；syntax 和 whitespace 检查通过。不跑全量。

## 独立复核

`/root/coder_python_tooling_fix` 最终只读复核 current approval / platform recovery / fresh queue
三个窗口、精确 Project/checkpoint/能力门、所有展示与旧 DOM handler 的统一 actionable
decision、显式产品确认优先、新 failure/wait/expired 优先及不可变历史，**无 remaining
blocker**。独立执行 6 项对应 Node 用例，6 passed，约 95.5 ms。

## 生产只读核对与限制

已使用公开 GET + 本地真实 app.js VM 核对同一原 K1：

- Project `project_ai-project_034252eb3595`。
- Requirement `delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`；同 Project 同标题只 1 个。
- 原 Task `task_dc5cf0aee44e5ffe0cb600557204e0d0` 保持 terminal BLOCKED。
- 准备 Operation `operation_21f68edbb63ecf9eb72f5c2af21f3654` 已 SUCCEEDED；旧方案指向
  `1133811`。当前 UI 显示待工程确认与批准并继续，原第 8 次失败只在历史；事实 bytes 不变、
  submitted=0。集成更新目标版本后须重新准备精确方案，旧方案不能拿来批准。
- Team busy 曾由公开 GET 证实为 503 TEAM_READ_IN_PROGRESS；已单独 4 项窄测验证保留旧
  snapshot/展开文档/草稿、撤销旧控制并中文说明自动重试，不猜测 Agent 已停止。

没有执行生产审批、重启、需求创建、数据库写入或提交。CUA 不可用，没有视觉验收；部署后的
当前 UI 和同一原需求完整公开恢复→真实 Task→QA/Review 由 root 继续验收。本任务阶段为
independently_verified，部署验收与统一提交尚由集成流程收尾。
