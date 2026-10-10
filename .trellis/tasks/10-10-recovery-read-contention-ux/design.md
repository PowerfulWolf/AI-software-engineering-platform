# 读侧设计

## 输入、输出与错误行为

`observedApprovedRecoveryOperation(request, operation) -> boolean` 只用于已有恢复请求的
展示。输入来自已加载 Request、Console Team 信息及独立成功读取的 Operations 列表。
以下全部成立才返回 true：

- Team busy/unavailable/timeout，Operations 本轮读取成功，Project 没有切换；
- 当前 Project、snapshot Team、Console Team、Operation Team 精确一致；
- 本需求的当前 Operation 为 RUNNING CONTINUE_DELIVERY，Project/Requirement 精确一致；
- approved_plan_sha256 为完整 64 位 SHA-256，存在同 Team/Project/Requirement 的已封存
  SUCCEEDED 审批来源，plan 摘要与本次已批准摘要一致；来源 checkpoint 与本次 intent 相同。

任何条件缺失均返回 false，沿用原始事实展示；没有异常宽松接纳或恢复控制权限。
requestNodeExecution 只对已保留 STOPPED/终态旧失败、没有新失败/等待/失效claim/活动Task
的原处理分支追加这个只读观察条件。输出仍为 paused PREPARING_EXECUTION，文案说明
请求处理记录尚未结束、没有新的角色执行事实；不声称 Coder 执行或恢复成功。

## 数据与控制分离

buildDetail 的当前概览同时显示两条独立事实：平台的当前恢复请求尚未结束，Team 数据
暂不能核对。读取问题提示改用“新操作暂不可提交”，避免把已接收的 Operation 误说成暂停。
该说明参加 overview 的 keyed signature，读取恢复时移除说明，同时保留展开的已保存正文。

canControlCurrentTeam、当前 Project、capability、active Operation、精确批准、旧回调
提交校验没有变化。历史 Operation/Request/Task 不写回，读取失败不重写状态或 hash。

## 验证矩阵

| 输入 | 展示结果 | 控制结果 |
| --- | --- | --- |
| 三种 Team 读取问题 + 当前精确已批准恢复记录 | 中性“平台正在处理恢复”，读取问题单列 | 所有新操作暂停，旧批准回调拒绝 |
| 未读 Operations、外来 Team/Project/Requirement、错误摘要/来源 checkpoint | 不采用该观察分支 | 原 gate 保持拒绝 |
| 终态 Operation、新真实失败、知识/业务/最终确认、失效claim | 原当前事实优先 | 原 gate 保持 |
| Team 读取恢复 | 移除读取问题，保留保存正文 DOM | 重新核验已有控制契约 |

## 存量与回滚

没有后端、Schema 或持久化事实变化，无需改库。静态前端更新并刷新后按已有只读事实
重算展示；原审批和恢复执行不重放。回滚 app.js 的观察分支和概览说明即可。
