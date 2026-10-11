# 设计

## 契约

后端 GET `/api/v1/operation-summaries?project_id=P&delivery_id=D&page_size=25&cursor=C`
返回v0.1、team_id、scope、inventory_sha256、items、next_cursor、total_count、active、
active_complete=true。ETag需重新核验完整bytes，304仅复用既有同scope阅读页。
409 OPERATION_CURSOR_STALE不能拼接历史；503/无效scope/不完整active禁用操作。

## 读写分离

独立摘要页与完整详情cache。通用阅读使用scope/action/target accessor；完整proof/plan/
approval消费者只读真实full Operation。摘要定位字段只能选择单条完整GET，不能批准。
展示及六类工程写入口在await后重新取当前request/plan/proof并沿用原exact gates。
POST继续使用既有expected checkpoint/plan fences；不自动批准漂移后的新计划。

## 验证矩阵

Good：正常poll为summary/304，完整处理正文按需GET，审批展示/写前fullGET。
Base：旧manifest无summary能力，保留原GET兼容；大历史分页可完整到达。
Bad：外Project、旧digest、缺active集合、stale cursor、晚到callback均不能恢复控制。
独立fake HTTP/DOM先红后绿，相关现有readiness/engineering/recovery/notice回归。
