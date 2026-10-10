# 恢复处理中与团队数据忙读分开展示

## 实证问题

当前CONTINUE_DELIVERY携带精确approved_plan_sha256，公开Operations GET已核验RUNNING /
sequence2/noresult；同时Team GET为503 TEAM_READ_IN_PROGRESS。requestNodeExecution用
canControlCurrentTeam作为“平台正在处理恢复”的展示门，忙读会使旧STOPPED/终态失败再次变为
当前红色阻塞。读取失败不能说明已接收的恢复操作失败或角色停止。

## 最小范围与验收

- 只修前端读侧，使用当前可读Operations中的精确Team/Project/Requirement/current Operation
  及已封存匹配审批来源；不从时间、日志或Intent推断真实角色运行、seed完成或恢复成功。
- Team busy/unavailable/timeout时保持“平台正在处理恢复”的中性paused展示，表示当前请求
  尚未返回结果；将控制刷新问题独立显示，说明新操作暂停、页面自动重新核对。
- 原canControlCurrentTeam、精确审批、活动Operation、Project切换和旧回调提交门禁全部保留。
- 未读Operations、外来绑定、无精确审批来源、终态命令或新的真实阻塞不能被该展示覆盖。
  业务确认、知识门、实际角色调度、失效租约保持原事实优先级。
- 先RED后GREEN；窄Node验证busy/unavailable/timeout、正反身份、仍拒绝旧批准回调、展示与
  流程/操作记录一致、旧history bytes不变。只跑受影响前端增量，不启动浏览器或安装依赖。
- 补齐 operation-progress 与 delivery-status 既有 harness 中明确的成功 Operations 读取、
  Team/Console/capability 与 Project 前提；保留原断言。HEAD 已独立复现 9 项基线失败，
  其中 8 项属于上述 fixture 漂移；剩余已回收租约展示问题单列 reaped-lease-ui 任务。

## 存量、部署、回滚

无wire/backend或持久化事实变更，无需改库。现有需求加载兼容静态资产并刷新后即可重新计算
展示，不重复批准或执行。部署由root安排，不为本任务操作生产POST、审批、工作区或重启。
回滚本次读侧分支和展示资产即可；原需求、Task、Operation及审批历史全部保留。
