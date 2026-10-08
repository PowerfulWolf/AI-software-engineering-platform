# Console 新操作与运行服务版本一致性

## Goal
修复新页面可展示“让平台处理中断”但运行中的旧服务拒绝 HANDLE、用户只看到英文输入错误的问题。

## Evidence
用户截图为“让平台处理中断 · 操作未被接受 / Operation input is invalid.”。只读检查确认监听
8765 的进程于 2026-10-06 启动，平台处理功能提交于 2026-10-08；当前服务 GET console 没有
supported_actions，而 GET app.js 已包含 HANDLE。隔离当前 transport 接受同格式请求，旧 union 拒绝。

## Scope
Console transport/static assets/control manifest、前端操作提交/等待提示、真实 HTTP/CJS/browser 回归、相关 spec/docs。

## Acceptance
- 应用启动时冻结静态资源；同一服务不会从后来修改的磁盘代码混入新页面。
- GET /api/v1/console 报告固定版本及支持动作；UI 仅向兼容且支持当前动作的服务提交。
- 老服务/缺少动作/读取失败不给旧后台发送新操作；中文说明请求未受理及空闲重启/刷新路径。
- HTTP HANDLE 真正通过 SubmitOperation 和 durable store；未知动作/非法字段拒绝且不回显输入或产生 Operation。
- 不重启真实服务、不审批/恢复/继续当前需求，不修改生产数据；只跑增量测试。

## Rollback / 存量
无需改库，422 请求未受理，不新增操作或消耗需求预算。用户待服务空闲加载修复后刷新原需求。
回滚代码时保留已有 Task、草稿、审批、不可变运行事实和处理记录。
