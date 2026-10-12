# Team snapshot 性能研究（2026-10-12）

## 已观察事实

尚未升级的旧服务，选中 Project 的 `GET /api/v1/team` 实测 15.58 s / 2802572 bytes；
全局 operation-summaries 约 0.10 s。一次 RSS 观察为约 682 MiB；不能把单次 RSS 当作
无泄漏证明，也不能把旧版本的端到端耗时归因于尚未部署的 capacity 修改。

既有 read-memory-lifecycle 文档曾记录 225 个历史 JSON / 253531912 bytes，这是旧测量，
不是今天的新采样。本次研究只读，不输出正文、DB rows、DSN、API key，也不更改运行事实。

## 静态热点

- `team_view/reader.py::ProductionTeamReader.snapshot/_snapshot` 每个 GET 新建 JointJournal；
  `_JointHistorySnapshot` 只复用同次调用的完整历史。`multi_directory/store.py::history/
  _validated_history` 下一次 GET 仍需逐文件 fresh read、SHA、Schema 和 predecessor 校验。
- `team_view/engineering_history.py` 的 baseline 分支完整 decode 内嵌 Plan 的 start，再读
  standalone Plan。`BaselineBindingSnapshot` 首次读取 bindings 时又读 Plan、Start、authority、
  patch 和 native-rule epoch。当前 snapshot 没有 `recovery_record_read_scope`，固定可信
  Plan/Start codec 可在同一调用内减少重复 decode，当前授权判断仍必须独立新验。
- `_snapshot/_read_task_details` 向列表返回完整 Product/Design/Plan/role Artifact 文档；
  `_merge_task_history` 保留 timeline 又重发为 execution_history，即使没有历史 Task 也重复。
  findings/tests/details 与文档正文还存在重叠；尚未测量各字段占比。
- `web_console/transport.py::_TeamSnapshotReads._read` 顺序执行 snapshot、to_wire、render。
  gate/coalescing 应覆盖完整同步 worker 生命周期；扩大并发不会降低读取本身的成本。
- `team_view/app.js` 整 snapshot 的 JSON.stringify 比较及 detail/content signature 包含全部
  documents/history。现有 DOM reconciliation 保留阅读状态；5 s 轮询在上次完成后安排，
  超时会退避，不能误报为每 5 s 叠加无限请求。
- `_active_successor_dispatch` 对同 Repository 多次读取并 decode 全部 dispatch_commits；
  可研究同一只读 SQL 快照内复用已验证前缀，但当前尚无其耗时或规模测量。

## 本轮小步修复

在同步 `ProductionTeamReader.snapshot` 内，嵌套已有 `recovery_record_read_scope` 与
`source_inspection_scope`。固定 Plan/Start codec 仍逐次 fresh 读取完整 bytes、核验 SHA，
只复用同 scope 内相同 bytes 的 decode，返回隔离 deep-copy。现有限制是 512 entries / 32 MiB
raw+typed serialized 计账；这不是 Heap/RSS 上限。结束和异常时释放，不跨 HTTP 缓存。

不复用 SQL、Git、Lease、current Task、authorization、process absence 或 READY 结论。
不缓存 raw list 代替键/Schema 验证，不删历史、不新增大小拒绝、不扩大 worker 并发。
这一步不消除首次解码和完整历史读取成本，只有顺序实测后才能声称端到端改善。

## 后续接口方向

单独引入版本化 typed summary：当前状态/工作/阻塞行动/owner、角色队列摘要、最近独立
验收反馈、文档 ID/SHA、history count。详情接口按精确 Project/Requirement/Task 取完整
文档与历史；分页游标绑定 owner 和不可变 prefix，完整历史可读取和导出。保持原 v0.2
完整接口，不把裁剪后的 summary 偷换成原 snapshot。

Summary/detail 都携带 checkpoint/task revision、source、scope、as_of。前端用 fresh summary
更新操作可用性；详情保留阅读位置和已加载历史。审批仍提交 exact digest，服务器重新验真；
旧详情不能授予继续权限。减少 body 仅降低 wire/JSON/前端成本，不等于 15.58 s 全部解决。

## 增量验证、存量与回滚

新测试先统计真实 Team→engineering history→binding 的固定 decoder 次数，验证 fresh
bytes/hash、nested-copy isolation、scope 成功/异常释放；第二轮读取须重新 decode，历史
损坏和新增尾部必须可见。相关模块：joint_history_snapshot、task_read_snapshot、
baseline_snapshot、engineering_snapshot、run_attempt_cache、team_snapshot_coalescing。
不跑全量测试。

升级后在无并发 GET/无模型操作的窗口顺序采样 endpoint、reader、SQL、to_wire、render
时间及响应 bytes；只输出 requests.documents、tasks.documents、timeline、execution_history、
runs/queue 的 aggregate count/UTF-8 bytes，不输出源文或 heap/core dump。

本轮读取优化无数据迁移、审批消费、Task reset 或新需求。只在受控空闲维护窗口加载；
回滚保留所有 capacity 新记录的兼容 reader，不能删除原 Artifact、Event、Operation、Plan。
