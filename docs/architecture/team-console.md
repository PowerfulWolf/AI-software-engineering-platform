# 工作台数据、接口与边界

面向维护 Console、读侧投影和 HTTP 接口的开发者；页面使用见[团队工作台](../user/team-console.md)。

## 数据链与接口

```text
Team manifest + 选定 Project 的 requirements journal + Repository 原生 checkpoint
                      ↓
MySQL 一致性只读事务：Task / StateEvent / Dispatch
                      ↓
Artifact / Evaluation / ModelRouteAttempt + 组织 AgentProfile
                      ↓
ProductionTeamReader → TeamSnapshot → GET /api/v1/team → 工作台

浏览器 typed intent → POST /api/v1/operations → append-only ConsoleOperation
                                              ↓
                                  Manager application ports
                                              ↓
                                     上述 Delivery durable facts
```

父需求尚未写回 child 时，由批准的联合文档确定性派生 native delivery ID，读取最新 Task。
文件 prefix 先于 MySQL snapshot 捕获。读侧不调用 prepare、reconcile、register 或 Team Host，
不创建 stores/schema、不扫描代码、不调用模型、不写 checkpoint。记录不一致返回 503。

HTTP 仅绑定 loopback，校验 Host/Origin，关闭 CORS/缓存，采用 CSP 与 textContent。
查询开放 assets、`/api/v1/team[/<team>]`、`/api/v1/console`、`/api/v1/operations[/<id>]` 和受控
administration status/settings；交付写入口是 typed JSON `POST /api/v1/operations`，限制 64 KB 并
先持久化再异步执行。管理面另有 Project、知识、write-only 运行变量和 MySQL probe 的 typed
`/api/v1/admin/*` 边界。未知路径 404，错误不泄露 DSN。
没有任意文件路由，不应通过反向代理公开到局域网或互联网。这不是带认证的多用户站点。

Operation 持久化允许完整恢复结果，使用独立 16 MiB 实际 UTF-8 JSON 字节准入限制，
包含 JSON 转义和缩进；读写对称，模型调用诊断仍独立限制 16,000 bytes。
该政策不扩展 capture/wire 字段，不改变历史摘要或序号。超过预算或记录校验失败时不返回
部分列表；operations list/detail 返回中文 `503 OPERATION_STATE_INVALID`，无原输入或异常。
非法/不存在操作 ID 仍返回404。Console readiness不被改为配置缺失；浏览器禁用交付并在
需求内显示原因。现有大型合法记录通过兼容读取恢复，无需迁移或改写。

正式 wire contract：[team-snapshot.schema.json](../../schemas/team-snapshot.schema.json) 与
[console-operation.schema.json](../../schemas/console-operation.schema.json)。
旧 DashboardRenderer / ReadOnlyProjectionApi 仍为纯、transport-neutral 的基础组件，
静态 snapshot 工具和 `ase team serve` 只用于只读兼容；日常 socket 由 `web_console.host` composition 持有。

## 后续边界

执行器 heartbeat/started/finished 与失联识别；上游岗位统一成员分配；Operation 分页/增量读取；
安全的 macOS Keychain / Linux Secret Service 与登录启动适配；远程多用户场景进入实施前还必须有
认证、授权和审计设计。当前不引入 Reporter、复杂 DAG、成本大屏或远程控制面。
