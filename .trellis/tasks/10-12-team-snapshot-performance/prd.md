# Team snapshot 完整恢复记录读取优化

## 目标和复现

`ProductionTeamReader.snapshot()` 已拥有纯 source inspection scope，但尚未拥有完整恢复记录的
typed decode scope。同一个实际 `_TaskReadSnapshot.read` 的 engineering、queue 与 interruption
投影复用 binding prefix 后，仍把同一 `ExecutionBaselinePlan` 和 `BaselineOperationStart`
各解码两次。这是确定的重复读取 CPU 工作，不是模型调用或运行事实停滞。

隔离复现使用真实文件 stores 和 `_TaskReadSnapshot.read`；仅 SQL、run facts 使用既有 fake port。
首次 snapshot 的 Plan/Start 完整文件各读取 2 次、完整解码各 2 次、authority 解码 2 次；timeline
保留全部 4 条记录。没有接入生产、模型或共享测试数据库。

## 范围

- 仅 `team_view/reader.py` 的公开同步 snapshot 增加嵌套 `recovery_record_read_scope()`，保留
  现有 `source_inspection_scope()`、错误转换与 `_snapshot` 读投影。
- 复用既有 fixed decoder、512 entries / 32 MiB aggregate bound 和 deep-copy isolation。
- 不缓存当前 authority、Task、lease、permission、READY、成功结论；不持久缓存跨 HTTP 请求。
- 不增 summary API，不截断历史、Context 或补丁，不改变 SQL/角色执行/审批/恢复状态。

## 验收

1. 同一个真实 Task 投影的 Plan 解码一次；完整文件仍各重读两次，Start/authority 仍各解码两次。
   Start 的 engineering history 普通 list 不绕进 fixed decoder，保持原完整列表契约。
2. 下一次 snapshot 重新读取、解码；返回的完整 wire、history 和磁盘 bytes 不变。
3. scope 中返回的 nested metadata 不可污染下一次读取；完整新字节、同大小/mtime 篡改、
   缺失 authority 和符号链接都维持 fail closed。
4. 成功、校验异常和读取异常之后 scope 清空并 reset；HTTP 错误仍脱敏，不残留 typed model。
5. 仅跑相关增量 pytest、Ruff、strict mypy 和 diff check，并独立 review。

## 存量数据处置与回滚

不迁移 SQL/journal，不改 Requirement、Task、Operation、审批、receipt 或工作区。待当前操作/角色
结束后通过受控空闲重启加载修复，刷新原需求即可。回滚只移除新增 scope，恢复重复解码成本，
全部 durable bytes、SHA 和历史保持。
