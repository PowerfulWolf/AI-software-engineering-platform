# 团队工作台

## 使用

按照 [生产配置](../operations/production-setup.md) 安装后启动本地 Web Console；未配置时可先在页面完成设置：

```bash
uv run ase-console
```

打开 **http://127.0.0.1:8765**（使用该地址，不使用 localhost 别名）。页面可以创建多目录需求、
与 Product Agent 讨论和批准、继续中断交付、批准 exact 恢复计划，以及领取 Candidate。
Ctrl+C 会停止控制台和它的后台 Manager dispatcher；已经提交的 Operation、Delivery、Task
和 Artifact 仍然持久化。页面每 5 秒读取已提交数据，不要求手工拼装 ProjectionFacts。
控制台页面和操作能力绑定本次服务启动。更新平台代码后，等待当前操作及角色执行结束，
在服务空闲时运行 `./scripts/ase-console-service.sh restart`，再刷新页面；仅刷新无法加载新的
后台操作。页面遇到版本不匹配会给出中文说明并阻止提交，原需求和已保存进度保留。
配置缺失时进入 setup 模式，设置和状态页仍可访问；端口占用时 CLI 安全退出。
Team 未准备、数据库不可用或记录校验失败时交付不可用并显示具体状态，
不伪装成空团队。真正空的已准备 Team 显示创建 Project/接单提示。

## 三条阅读路径

1. **团队成员**：Team 成员、岗位、启用配置、跨 Project 多项分配、当前岗位阶段、分配模型与历史任务。
   一个 Agent 不随项目复制，当前任务也不是单值字段。
2. **需求与交付**：所有选定代码目录/模块、只读参考目录、各仓进度和整体验收状态。
   点击需求看联合 ProductSpec、TechnicalDesign、ExecutionPlan、IntegrationEvidence，并执行当前唯一
   合法的 Product 回复、批准或继续操作。
3. **任务详情**：Task 状态、最近活动、阻塞、候选 SHA、时间线、实际模型路由尝试的结果、
   耗时和失败分类，以及已通过状态事件引用的 plan/implementation/QA/review 报告。
   单仓旧入口的上游文档暂提供 ID/digest 引用；联合文档和四类交付报告提供脱敏正文。

记录在调用完成或阶段提交后发布，不显示模型私有思考或未提交聊天。报告 SHA 指向原始已验证
事实，展示正文再次脱敏后不应拿展示字符串计算源 SHA。

遇到工程等待时，产品用户不需要检查 lease、进程号、补丁摘要或工作区。需求详情会直接显示
“让平台处理中断”，并给出当前原因、处理方、具体动作和复查时机。平台会在原 Task 的受控范围
内执行一次有界核验；若已具备冻结授权和完整事实，Manager 会交回原 Supervisor 继续；若记录
不完整，会保留现场并显示“平台需要维护”，不会把产品用户变成维护者。只有页面明确显示需要
工程职责决定时，才由有工程权限的维护者处理精确决定。重新检查只重新读取事实，不会补造执行结果。

## 不能混淆的状态

- IMPLEMENTING / QA / REVIEW 是交付 checkpoint，不是进程存活证明。
- 当前岗位由 Task 状态和 DispatchPhaseCommit 对齐；预分配 QA 不会提前标为正在测试。
- enabled、max_parallel_assignments 是配置，不代表在线状态或实时全组织容量占用。
- Project 过滤只影响需求与交付视图；Team 成员与总负载仍属于唯一 Team。
- 没有 heartbeat 时 execution_liveness=UNKNOWN，不能仅靠超时猜测进程失败。
- 分配模型来自 ModelSelection；实际调用模型来自 ModelRouteAttempt，降级记录不会被原始分配覆盖。
- 调用成功不等于 QA/Review gate 通过；一个子仓 DONE 不等于多仓需求 DONE。
- 上游岗位未登记为独立 AgentProfile 时，只在需求阶段显示，不生成虚构成员。

刷新失败保留上次画面并标记“旧数据”和成功时间；无变化的刷新不替换 DOM，有变化时保留已展开
历史/报告，避免阅读中每 5 秒被折叠。


数据来源、接口和安全边界见[工作台数据与接口](../architecture/team-console.md)。
返回[用户使用指南](README.md)。
