# 2026-10-09 Console 慢读与间歇刷新失败诊断

本轮仅诊断：未修改运行代码，未重启服务，未写数据库、审批、队列或 Requirement 事实。基线 `ab5dead`，本机运行 Console PID 33041、端口 8765，配置来自 `self-iteration-ai.json`。诊断输出不包含凭证、SQL 正文、源码补丁或业务文档正文。

## 复现及测量

- 顺序 GET `/api/v1/team`：503，约 0.003 秒；响应机器码为 `TEAM_READ_IN_PROGRESS`，不是 `TEAM_UNAVAILABLE`。之后另一次 5 秒有界 GET 未在期限内响应。客户端超时不证明同步读 worker 已结束。
- GET `/api/v1/operations`：200，约 6.118 秒，响应 4,630,342 字节；GET `/api/v1/console`：200，约 0.0016 秒。
- 使用正式 `ProductionTeamReader`、安全 runtime.env 加载器和现有 READ ONLY SQL 事务，在独立进程读取同一实际 Project。未构造 TeamHost、Worker 或写 store。
- 无 cProfile 的快照读取与 to_wire：成功，25.927 秒，2 个 Requirement、25 个 Task。190 次 `Cursor.execute` 合计 0.266 秒，包含实际查询结果读取；不打印语句或结果正文。独立建连约 0.0136 秒，SELECT 1 约 0.0005 秒。
- 带 cProfile 的一次快照：27.545 秒；25 次 `engineering_history` 累计 23.702 秒。2 次 `bindings_for_task` 累计 17.828 秒；10 次 `plan` 累计 14.034 秒；128 次 `CapturedMutations.validate_capture`，8,448 次 mutation body 重建，14,848 次源文本敏感信息扫描。这些耗时互相嵌套，不能相加。
- 对正式 `_list_current` 的独立只读剖析：约 2.589 秒，290 个 Operation（214 SUCCEEDED、70 FAILED、6 INTERRUPTED），没有 QUEUED/RUNNING；870 条编号历史 JSON 共 5,806,039 字节，最大单条 2,182,787 字节。该测量跳过构造器和 flock，不创建目录或锁文件，不能把它当成 HTTP 锁等待耗时。此路径仍有16次 capture 校验、1,856次源敏感信息扫描。
- 服务 CPU 多次约 99%–118%。`vmmap -summary` physical footprint 一次约812.7 MB、后一次297.3 MB，峰值约1.1 GB；系统16GB RAM，自报free约41%，已有约8GB swap使用。不能仅凭RSS或历史swap断定泄漏/OOM，本次未看到当前进程持续增长至耗尽的证据。

以上为当前在线负载下的顺序诊断，浏览器轮询和后台线程未停止。cProfile 会增加开销，未与旧版做独占同负载对比；不把剖析总耗时当成无竞争的性能基准。

## 已确认的慢点及代码依据

1. **工程基线的重复完整校验。** `team_view/engineering_history.py::engineering_history` 读取 baseline-starts，再读取相同 plan；随后两次调用 `bindings_for_task`。`manager/baseline_store.py::bindings_for_task` 再通过 `plan/start/required_context` 多次重开同一捕获。模型入站和显式 `validate_integrity` 的 roundtrip 又递归运行 `ExecutionBaselinePlan.validate_plan`、`CapturedMutations.validate_capture`；敏感信息扫描进入正则、Python AST/tokenize。这些是真实安全检查，但相同事实在同一读取中被重复执行。
2. **空闲派发仍全量重放操作历史。** `web_console/core.py::ProjectConsole._run` 无工作时等待默认0.25秒，再调用 `run_once → claim_next → _list_current`。文件 store 在独占 flock 内重读每个 Operation 的全部编号记录，再筛选 QUEUED。虽然当前290个操作均已结束，仍重复反序列化和校验嵌套 baseline plan。HTTP list 的 shared flock 与此路径竞争，叠加CPU消耗；本轮未单独量化锁等待所占比例。
3. **前端错误归因不够具体。** `team_view/app.js::refreshSnapshot` 对非2xx Team响应只抛 `Error("read failed")`；无既有 snapshot 时显示“检查生产配置、MySQL、workspace”通用文案。它未区分已复现的 `TEAM_READ_IN_PROGRESS`、真实数据不可用和40秒客户端deadline。实际慢读仍占 admission gate，多标签页或超时后的请求可能被拒绝。没有记录实际标签页数量，不能把多标签页当作唯一根因。

MySQL是本次实际快照总耗时中的小部分，且已成功完整读取；不能把截图提示理解成数据库断连。内存可能影响系统性能，但本轮证据不支持把OOM或旧泄漏复发作为主要结论。

## 为什么此前修复仍不足

`10-09-console-read-reliability` 已验证减少 JointJournal、Evaluation和Task投影的重复读取。此前快照独占基准约3秒；它不覆盖此次新增保留草稿／更新基线后的嵌套完整捕获重放，也未改变空闲操作派发全量扫描。此次性能剖析中JointJournal history约2.492秒，而工程history约23.702秒，热点已不同。不能用不同负载的数值直接宣称旧修复失效。

## 后续修复建议（尚未实施）

- 在单次读取内部复用已完整验证的工程记录、plan/start/binding及捕获结果；消除重复 roundtrip，同时保持每轮对源bytes、digest、scope、审批和前驱链的检查。
- 避免空闲领取持续重放全部终态大记录；领取和完整历史展示的读取职责需要分开，跨进程排他、最新操作发现、历史完整性和精确派发必须继续成立。
- Team忙、读取超时与数据校验失败分别提示；忙时保留历史视图、协调重试，不提示用户重建需求、补审批或默认归咎MySQL。不能将旧视图当作当前操作权限。
- 增量回归需要覆盖实际baseline plan/capture、重复bindings读取、空闲无工作、被篡改旧记录、跨进程新增操作、多调用者busy和客户端超时后worker继续运行；不靠删除历史或放宽安全扫描降低耗时。

## 存量数据处置

无需改库、清理历史或重建需求。本轮没有启动模型或恢复需求；诊断不改变审批与执行事实。后续实现并验证修复后，再由维护者受控加载新服务；审批和接续仍遵守原exact授权。仅重启可能暂缓资源占用，不能消除这两处重复计算。

## 后续实现

诊断完成后，用户授权修复。实现采用单次同步读取内有界纯扫描复用、完整bytes清单重查的
空闲派发优化及busy/deadline安全展示；没有改Schema、审批或生产持久化事实。
修复后隔离只读快照约4.6秒，修复前同数据约25.4秒；完整wire除as_of外相等，源JSON清单未变。
运行实例未由本轮重启，不能把隔离测量当作已部署HTTP效果。
详细实现、增量验证、剩余风险和存量加载步骤见
[任务验收记录](../../.trellis/tasks/10-09-console-read-performance/verification.md)，
正式契约见[read-memory-lifecycle](../../.trellis/spec/core/read-memory-lifecycle.md)。
