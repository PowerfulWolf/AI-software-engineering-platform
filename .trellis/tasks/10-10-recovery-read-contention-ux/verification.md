# 验证记录

## 本次恢复观察回归

RED：修改前运行 `node --test --test-name-pattern='fresh exact recovery remains processing'
tests/team_view/engineering-wait.test.cjs`，3 项均失败，实际为“已阻塞”，期望为
“平台正在处理恢复”。

GREEN：新增 6 项窄回归全部通过，覆盖 busy/unavailable/timeout、身份/审批/终态反向矩阵、
真实等待/失败优先及实际 buildDetail 读取说明和正文节点保留。旧批准回调没有提交，保存的
Request/Task/Operation bytes 完全一致。

## 既有 fixture 基线

在临时目录使用 git show HEAD 导出的 app.js、operation-progress.test.cjs 与
delivery-status.test.cjs 独立运行原文件，28 项中 19 通过、9 失败；与改动工作树失败一致。
完整本机证据：`/tmp/ase-ui-head-baseline.log`。临时代码树随后删除，未替换共享代码。

最小补齐 harness 的成功 Operations 读取、Console/Team/能力、Project 前提后，8 项恢复
通过，没有删改任何断言。第 9 项是现有已回收租约被误当活动调度的展示问题，单列到
`10-10-reaped-lease-ui`，其修复与本次 Team 读取修复分开审查。

## 最终增量

```sh
node --test --test-reporter=tap tests/team_view/engineering-wait.test.cjs tests/team_view/product-execution.test.cjs tests/team_view/operation-progress.test.cjs tests/team_view/delivery-status.test.cjs
node --check src/ai_software_engineer/team_view/app.js
git diff --check
```

四个受影响前端文件共 120 passed、0 failed；语法检查与 diff 检查通过。保存输出：
`/tmp/ase-recovery-ui-incremental.log`。没有跑全量、浏览器、真实模型、生产 POST 或重启。

限制：Operation RUNNING/sequence 2 不提供角色进度或超时事实，故只显示记录尚未结束；
本修复没有新增恢复服务进度 API。实际浏览器视觉与焦点验收仍受连接故障限制，不能用 Node 结果代替。

## 独立审查

`baseline_resume_contract` 完成只读独立审查，未发现阻断问题。审查确认观察分支绑定当前
Team、Project、Requirement、完整 plan SHA 与本次审批来源 checkpoint；新的等待、失败和
业务确认仍优先，原提交门禁没有放宽。独立窄回归 11 passed、0 failed，包含旧回调拒绝。
实现与增量验证已完成；等待当前生产操作安全收尾后部署，不为前端更新截断已接纳执行。
