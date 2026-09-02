# T026：事件驱动只读 Projection 与 Read API

`RunProjectionBuilder` 是纯函数：输入已经从 SQLite、ArtifactStore、EvidenceStore、Evaluation
Store、WorkforceStore 和 HandoffStore 读取并校验的 `ProjectionFacts`，输出可重算的
`ProjectionSnapshot`。它汇总 Task、Run、Agent、Lease 和稳定排序的 timeline，不写入任何来源。

`ReadOnlyProjectionApi` 是 transport-neutral 的 GET-only seam，提供 `/api/v1/tasks`、`runs`、
`agents`、`leases` 列表/详情、过滤与分页。POST/PUT/DELETE 一律 405；未知路径 404；分页错误
400。API 接受快照而非可写 store，因此不会迁移 Task、修改 verdict 或执行命令。

Projection 在构建前拒绝重复 ID、未知 Task、冲突 run identity、断裂 StateEvent 流和 naive
`as_of`；Lease 状态只能依据显式时钟计算，缺省为 UNKNOWN。每个投影项保留 source URI、digest
和源 ID，dashboard 可据此回链 durable facts。
