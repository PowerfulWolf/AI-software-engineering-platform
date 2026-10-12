# Team snapshot 的同步完整记录解码范围

## Scope / signatures

`ProductionTeamReader.snapshot(project_id: str | None = None) -> TeamSnapshot` 只读 Team/Project
durable facts。一次同步调用同时拥有 `recovery_record_read_scope()` 与既有
`source_inspection_scope()`；嵌套存储读取可复用完整、已验证 immutable record 的 typed 解码。
复用契约和固定 decoder 见 [recovery-record-read-scope.md](recovery-record-read-scope.md)。

## Contracts

- 不改变 `_snapshot`、SQL READ ONLY snapshot、完整 history、Task/queue 投影、返回 Schema 或
  `TeamReadError` 的脱敏错误。范围内没有模型调用、Host 初始化、审批或状态写入。
- 每个原 store 消费仍执行完整 regular-file/no-symlink 读取、原 size limit 和全字节 SHA。
  Plan/Start/Context 仅在 path/kind/exact class/key/full-byte hash 全相等时复用 fixed typed decode。
  不以 mtime/size、已有成功或文件存在代替完整验证。
- 既有 scope 的 512 entries / 32 MiB 是 aggregate 原字节+typed serialization accounting；
  它不是总 Python heap/RSS 上限。溢出仍完整解码校验，不缩短或拒绝原合法历史。
- 每次返回深拷贝；历史 Task nested metadata 不可污染私有模型。当前 authority、Task、lease、
  SQL/Git/process、permission、READY 或可继续结论保持原观察，不能进入该 cache。
- 调用成功、读取失败和 validation 失败时清空 owned scope 并 reset ContextVar。下一次 HTTP
  或 snapshot 重新完整读取和校验。没有 reader-instance/global cache，不扩大并发。

## Validation matrix / Good, Base, Bad

| 输入或生命周期 | 预期 |
| --- | --- |
| 真实 Task 的 engineering/queue/interruption 消费相同 Plan/Start | Plan decode 1 次；Plan/Start 各完整文件读 2 次；Start/authority decode 2 次；全部 history 保留 |
| 下一次独立 snapshot | 新 scope，Plan 重新 decode 1 次，完整读取和 Start/authority 观察照常增加 |
| 同一返回 nested metadata 被修改 | 后续完整读取返回原事实，私有 typed model 不受影响 |
| 暖 scope 后同大小/mtime 的 Plan 篡改 | 新全字节 SHA 触发重新 decode 并拒绝，不复用旧成功 |
| 暖 scope 后原 authority 删除或文件换为 symlink | 原读取/权限错误，snapshot fail closed |
| scope budget 为零 | 所有合法完整事实仍可读，各消费独立 decode，不截断历史 |
| 成功、validation failure 或 read failure | owned cache entries/bytes 为零，ContextVar reset；HTTP 503 仍脱敏 |

Good：降低重复 schema/完整模型解码，同时保留原完整字节与当前授权观察。Base：空 snapshot 或
零 cache budget 维持原只读结果。Bad：跨轮询冻结 READY、拿 mtime 当完整 hash、删历史或缓存审批。

`engineering_history` 的普通 `records.list("baseline-starts", BaselineOperationStart)` 保留原完整
列表 decode；它不能仅为了减少计数而借用 fixed key-reading port。本范围的实际收益是重复 Plan
解码由 2 次降到 1 次，而不是所有模型各一次。后续需要优化其他消费必须先定义其明确读取契约。

失败模式：底层已经存在安全复用 seam，并不表示实际公共入口已拥有它。只对 store 单测或只数
binding-prefix 调用会漏掉同一投影中剩余的模型解码。应从公开同步入口驱动真实完整消费者，
同时统计 decoder、完整原文件读取和当前 authority 读取，再选择最小拥有范围；不能按预期收益
改写断言、扩大 cache 到未获准模型，或把有限 fixture 优化称为端到端延迟/内存泄漏结论。

## Tests / existing data / rollback

`tests/team_view/test_snapshot_record_scope.py` 使用真实临时 sidecar stores 与 `_TaskReadSnapshot`
投影，仅 SQL/run facts 用既有 fixture 隔离。断言实际 decoder 和 full-read 次数、完整 wire、
磁盘 bytes、篡改拒绝、copy isolation 与 scope 释放；不设可移植 latency/RSS 断言。
同时保留 baseline snapshot、engineering/task read snapshot 和通用 recovery scope 增量回归。

存量数据处置：不改 SQL/journal/审批/Task/Operation/receipt/worktree，不新建需求。当前操作和角色
结束后以受控空闲重启加载，再刷新原需求。回滚移除新增 snapshot scope，恢复重复解码成本，
原 durable bytes/SHA、完整历史和执行前提不变。
