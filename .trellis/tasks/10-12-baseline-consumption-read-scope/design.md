# 设计

`consumptions(queue, task_id)` 的整个同步调用使用已有 `source_inspection_scope()`。
内部仍打开新连接，执行原 SELECT，逐条调用原 `_decode`，并按原 binding sequence 排序。
现有 ContextVar 作用域只记忆 exact text/path 的纯秘密检测事实，最多 512 项/16 MiB；
退出或异常时复位。既有外层作用域可以嵌套复用，没有新的缓存实现。

不改变 JSON Schema、SQL、返回类型、队列 fence、执行身份、角色、批准或 verdict。
回归使用真实 Git/Plan/Binding 和完整 `_decode`，仅替代 SQL 连接，不接触真实数据库。
可观测的成本断言是完整源码 AST 解析次数，不使用不稳定的墙钟阈值。

验证矩阵包含完整成功读取与原 wire/hash、独立重复读取重新验证、修改完整正文/路径、
计划身份、SQL 行身份及摘要错误、查询异常清理、返回模型可回收。
