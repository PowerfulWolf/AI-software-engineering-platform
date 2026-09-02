# T026 Design

`ProjectionFacts` 是各 durable store 的 typed immutable 输入；`RunProjectionBuilder` 不持有
store、时钟或写端口，验证 ID/Task 引用/StateEvent contiguous stream 后构建 `ProjectionSnapshot`。
Run 由 allocation/evidence/artifact/evaluation facts 合并，Task timeline 汇总全部来源并按时间、
kind、ID 稳定排序。`ReadOnlyProjectionApi` 接受快照，提供 GET-only 列表/详情和分页。
