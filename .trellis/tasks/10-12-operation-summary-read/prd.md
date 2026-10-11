# 有界 Operation 只读摘要协议

## 目标与范围
新增 v0.1 只读摘要/分页/ETag，降低 Console 历史轮询的大模型分配与响应体；旧完整 GET、写入、claim、审批与事实不变。每次摘要请求在 shared flock 下重新读取、hash 所有历史 JSON bytes；仅复用全部原始 bytes 相同的有界摘要。缓存上限 512 条 / 2 MiB，不保存完整 Operation 或授权材料。

允许路径：web_console/{summary_models,summary_projection,store,core,transport}.py、schemas/console-operation-{summary,page,cursor,query}.schema.json、tests/web_console/test_operation_summaries.py、相关 spec/index 与本 Task。禁止生产主 checkout、注册仓、服务、SQL 或现有 journal 操作；不改 app.js。

## 验收
- 默认 25、最多 50 条稳定新到旧分页；project/delivery 过滤；cursor 精确绑定 inventory/scope/page_size，事实变化返回明确 stale；完整 scope 活跃集（最多 64，超限不可用）。
- 缓存命中仍完整重读/hash，历史同长度/mtime 篡改、链断裂、symlink 均拒绝；溢出完整读取，不裁剪历史。
- 摘要无 intent/完整 result/patch/plan/审批正文；仅阅读摘要，精确操作仍取完整详情并走原门禁。
- ETag 仅完整重校验后允许 304；分页响应硬上限 256 KiB。
- Python/Schema 一致，增量正向/负向/边界测试、Ruff/strict mypy 与隔离性能/内存计数通过。

## 验证与回滚
仅新增/相关测试；不跑全量。回滚移除 endpoint/摘要委派/feature 字段与前端能力探测，完整 GET 仍可用。

## 存量数据处置
无需 SQL migration 或重写历史；既有合法 journal 可直接只读投影。缓存不授权操作，不改变 Requirement/Task/approval/verdict/attempt/queue。部署等待生产空闲维护窗口。
