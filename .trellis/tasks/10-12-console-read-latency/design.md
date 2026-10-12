# Design

复现：只读 summary 发起后 150ms 读 exact detail，summary 200/3.550s，detail
503/0.006s，固定 TEAM_READ_IN_PROGRESS。独立详情 cProfile 16.690s，包含两轮
_read_snapshot；工程历史 7.197s、Joint history 5.979s、baseline bindings 4.198s。

1. 将 ProjectView 统计装配延迟到仅 full/summary 输出需要它时。详情使用已核验 selected
Project 的完整事实；结束再用独立 SQL/文件观察获得 exact TeamDetailSource，保持原 fence。
2. _TaskReadSnapshot 在同一 SQL transaction 内保存 compact projection 的 state artifact IDs。
完整正文重新使用原 accepted artifact 校验函数读取原文件及 receipt/claim；工程状态取已核验
同一 exact projection，避免重复装配。下一 snapshot 完全重新读取。
3. summary 对固定 busy 同样有限重试，延迟 1/2/4 秒、原 40 秒总时限；每轮验证 scope owner，
取消/导航停止，真实 TEAM_UNAVAILABLE 不重试。单 worker admission 不改变。

实际串行测量确认上述装配优化降低工作次数，却不足以降低端到端耗时。继续针对采样中
重复读取的完整 NativeRuleEpoch 使用既有全字节 scope：新增固定 native-rule-epoch kind，
仅 exact NativeRuleEpoch 可使用；每次仍读完整原文件并计算 SHA，注册前完整校验 epoch
摘要和 key。该版本是 immutable 历史正文，当前批准/规则引用、Task 与绑定仍独立核验。
预算继续与 Plan/Start/Context/Joint edge 共用 512 entries /32 MiB，不新增跨请求缓存。

第二个实际热点：`NativeRuleEpochBody.bounded_redacted_body` 的完整 clean 正文反复扫描，
既有 source inspection scope 的 512 项被短小 generic 字段提前占满，正文无法复用。
为完整封存正文新增固定 pure-redaction 读取入口；与原 scope 共用 512 项/16 MiB，只允许
无敏感匹配的完整正文事实优先于 opportunistic generic 字段，source/patch 继续优先。
仍绑定完整文本和精确 pattern 集；有匹配、容量不足、规则变化或文本变化均完整扫描。

允许路径：reader.py、app.js、对应 tests/team_view、相关 core specs、本任务目录。
扩展允许路径：read_record_scope.py、manager/baseline_native_rules.py、对应 tests/recovery。
Schema/API/durable payload 不变，无数据库迁移或新需求。
