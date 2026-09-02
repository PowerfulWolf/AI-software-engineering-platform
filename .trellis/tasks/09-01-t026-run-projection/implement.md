# T026 Implementation

- 新增 projection models/projector 与六个 Draft 2020-12 projection schemas；
- 从 durable facts 重算 Task/Run/Agent/Lease 与 source-addressable timeline；
- 新增 transport-neutral `ReadOnlyProjectionApi`，拒绝非 GET 和非法分页；
- 不引入 HTTP framework、队列或数据库写端口，后续 dashboard 只消费该 seam。
