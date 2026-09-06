# T036 — 真实数据团队工作台

## Goal / confirmed scope

用户已采纳参考 Multica 的方案：团队为首页、需求视图、多目录范围、任务详情、阻塞原因、自动刷新。
不复制完整管理平台，不开发 Reporter，不允许通过 UI 调度、批准或改状态。没有 heartbeat 不声称在线。

## Acceptance

- [x] `ase team serve --port 8765` 从生产配置读取当前公司的真实数据，无手工 snapshot。
- [x] 一个组织 Agent 可关联多个需求/Task；区分分配、当前阶段与已结束，不虚构上游成员身份。
- [x] 展示联合需求的全部 selected paths、各仓进度、只读参考仓及集成状态；兼容单仓入口。
- [x] 子仓执行尚未回写父 checkpoint 时仍展示 MySQL 最新 Task 状态。
- [x] 详情可看时间线、模型分配、候选版本和可验证的产物引用。
- [x] 轮询失败保留上次画面且醒目标记过期；空数据给出接单入口提示。
- [x] 本地 GET-only，无任意文件服务、CORS、provider 调用或 store 初始化；校验 Host/Origin。
- [x] Schema/类型/测试/文档同步，真实 MySQL 集成验证读侧不写数据。

## Decision / research

参考站的任务、Agent、运行时页面支持成员→当前工作→历史执行的阅读路径。现有静态
DashboardRenderer 支持可信 projection，但没有生产数据入口。选择独立本地 HTTP composition
+ typed read model + 同源轮询，不改变旧 renderer 的纯函数契约。暂不引入 SPA 构建链或事件总线。
未来可增加 heartbeat/run lifecycle 后替换 UNKNOWN，不由 UI 推测进程健康或交付百分比。

## Workflow

`.trellis/scripts` 与 guides 目录不存在，手动维护任务文档。已确认方案，不重复需求问答。
允许路径：team_view 新模块、CLI、只读 store 打开接口、对应 tests/schema/docs/spec。
回滚：停止本地服务并撤回 T036 文件/入口；不修改生产数据库 Schema 或既有交付数据。
