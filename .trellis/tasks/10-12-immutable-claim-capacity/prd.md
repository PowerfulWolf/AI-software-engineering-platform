# Immutable original claim and exact legacy capacity evidence

首次 QueueClaim 的 raw SHA 不应随 Worker heartbeat 改变。CLAIMED event 在同一事务保存完整首次 QueueClaim，reader 校验 event 索引、WorkItem、时间与 SQL allocation/worker/lease 全字段；仅 SQL 当前续租 expiry 可以不同。显式 null/非法 snapshot 拒绝，不能退回 legacy。

旧记录不重写：仅从可信精确 parent/legacy Task 知识 lane 的完整已结束 invocation、outcome、独立 observations、Context 和 frozen snapshot 验证首次 sealed QueueClaim。候选 snapshot 必须全部相同、raw SHA 精确等容量 receipt，且与真实 SQL 历史仅 expiry 不同。返回成功不获得 FAILED quiescence 权限；容量本身仍需完整 Context、权限、源版本与全部主调用 no-start 检查。

验收：真实多次 renew 后 original_claim 字节和 SHA 不变；旧RETURNED知识 snapshot + rawexact capacity 可读；无 snapshot、raw hash/归属/原权限/源码/Context/时间/任何非expiry字段不同、缺outcome/observation、显式损坏event均拒绝。保留所有原Task/分支/进度/预算/审批，旧verifier无独立完整snapshot明确拒绝。
