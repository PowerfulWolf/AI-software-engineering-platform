# 团队工作台

## 使用

先按照 [生产配置](production-setup.md) 设置 ASE_CONFIG 和 MySQL DSN，再启动本地 Web Console：

```bash
uv run ase-console
```

打开 **http://127.0.0.1:8765**（使用该地址，不使用 localhost 别名）。页面可以创建多目录需求、
与 Product Agent 讨论和批准、继续中断交付、批准 exact 恢复计划，以及领取 Candidate。
Ctrl+C 会停止控制台和它的后台 Project Manager dispatcher；已经提交的 Operation、Delivery、Task
和 Artifact 仍然持久化。页面每 5 秒读取已提交数据，不要求手工拼装 ProjectionFacts。
配置缺失或端口占用时 CLI 安全退出；公司未准备、数据库不可用或记录校验失败时页面报错，
不伪装成空团队。真正空的已准备公司显示接单提示。

## 三条阅读路径

1. **团队成员**：组织成员、岗位、启用配置、当前公司多项分配、当前岗位阶段、分配模型与历史任务。
   一个 Agent 不随项目复制，当前任务也不是单值字段。
2. **需求与交付**：所有选定代码目录/模块、只读参考目录、各仓进度和整体验收状态。
   点击需求看联合 ProductSpec、TechnicalDesign、ExecutionPlan、IntegrationEvidence，并执行当前唯一
   合法的 Product 回复、批准或继续操作。
3. **任务详情**：Task 状态、最近活动、阻塞、候选 SHA、时间线、实际模型路由尝试的结果、
   耗时和失败分类，以及已通过状态事件引用的 plan/implementation/QA/review 报告。
   单仓旧入口的上游文档暂提供 ID/digest 引用；联合文档和四类交付报告提供脱敏正文。

记录在调用完成或阶段提交后发布，不显示模型私有思考或未提交聊天。报告 SHA 指向原始已验证
事实，展示正文再次脱敏后不应拿展示字符串计算源 SHA。

## 不能混淆的状态

- IMPLEMENTING / QA / REVIEW 是交付 checkpoint，不是进程存活证明。
- 当前岗位由 Task 状态和 DispatchPhaseCommit 对齐；预分配 QA 不会提前标为正在测试。
- enabled、max_parallel_assignments 是配置，不代表在线状态或实时全组织容量占用。
- 当前公司视图不统计其他公司工作，不把公司范围计数当成组织总负载。
- 没有 heartbeat 时 execution_liveness=UNKNOWN，不能仅靠超时猜测进程失败。
- 分配模型来自 ModelSelection；实际调用模型来自 ModelRouteAttempt，降级记录不会被原始分配覆盖。
- 调用成功不等于 QA/Review gate 通过；一个子仓 DONE 不等于多仓需求 DONE。
- 上游岗位未登记为独立 AgentProfile 时，只在需求阶段显示，不生成虚构成员。

刷新失败保留上次画面并标记“旧数据”和成功时间；无变化的刷新不替换 DOM，有变化时保留已展开
历史/报告，避免阅读中每 5 秒被折叠。

## 数据链与接口

```text
当前公司 manifest + requests journal + projects 原生 checkpoint
                      ↓
MySQL 一致性只读事务：Task / StateEvent / Dispatch
                      ↓
Artifact / Evaluation / ModelRouteAttempt + 组织 AgentProfile
                      ↓
ProductionTeamReader → TeamSnapshot → GET /api/v1/team → 工作台

浏览器 typed intent → POST /api/v1/operations → append-only ConsoleOperation
                                              ↓
                                  Project Manager application ports
                                              ↓
                                     上述 Delivery durable facts
```

父需求尚未写回 child 时，由批准的联合文档确定性派生 native delivery ID，读取最新 Task。
文件 prefix 先于 MySQL snapshot 捕获。读侧不调用 prepare、reconcile、register 或 Team Host，
不创建 stores/schema、不扫描代码、不调用模型、不写 checkpoint。记录不一致返回 503。

HTTP 仅绑定 loopback，校验 Host/Origin，关闭 CORS/缓存，采用 CSP 与 textContent。
查询开放 assets、`/api/v1/team[/<company>]`、`/api/v1/console` 和 `/api/v1/operations[/<id>]`；唯一
写入口是 typed JSON `POST /api/v1/operations`，限制 64 KB 并先持久化再异步执行。未知路径 404，
错误不泄露 DSN。
没有任意文件路由，不应通过反向代理公开到局域网或互联网。这不是带认证的多用户站点。

正式 wire contract：[team-snapshot.schema.json](../schemas/team-snapshot.schema.json) 与
[console-operation.schema.json](../schemas/console-operation.schema.json)。
旧 DashboardRenderer / ReadOnlyProjectionApi 仍为纯、transport-neutral 的基础组件，
静态 snapshot 工具和 `ase team serve` 只用于只读兼容；日常 socket 由 `web_console.host` composition 持有。

## 后续边界

执行器 heartbeat/started/finished 与失联识别；上游岗位统一成员分配；Operation 分页/增量读取；
安全的 macOS Keychain / Linux Secret Service 与登录启动适配；远程多用户场景进入实施前还必须有
认证、授权和审计设计。当前不引入 Reporter、复杂 DAG、成本大屏或远程控制面。
