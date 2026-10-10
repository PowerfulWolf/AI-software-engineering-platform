# 正式恢复批准的最新执行边界（2026-10-10，只读诊断）

## 对象与结论

- Operation：operation_bacb1b32b242923bc2d4dbad68818733。
- 原 Requirement：delivery_multi_8a5103309c232515bcf733947d32830365dd02c6。
- 精确批准 plan：edc70b3d943c52d85a079da433d43934f84e5c284f3c0dbbd74b09ae5a63a2c3。
- 恢复 Task：task_recovery_edc70b3d943c52d85a079da433d43934。
- 服务仍为 PID 63772，未进行维护、重启或运行时注入。

09:31 的首批诊断定位到 dispatch 已提交、seed 尚未封存。后续持续只读核验已经看到
完整 seed、实际 Task/claim 和 invocation，详见下表；不能把早先缺记录的观察继续描述成
当前未启动。目标 Coder worktree HEAD 仍为批准的 5d121a107fbbd7b5d1341ce4aff8bfc6ecb32874。
三阶段预分配仍不能代替实际 QA/Reviewer 执行。

## 有时间边界的证据（均为 UTC）

| 观察时间 | 只读事实 |
| --- | --- |
| 09:24:06 | macOS sample：1 秒、10 ms 间隔、88 次样本，物理 footprint 原报告为 1.6G、峰值 2.7G；主线程主要在 kevent，活跃 worker Thread_41014528 有 37/88 样本为 Pydantic → Python regex subn/search，另见 SHA 与 JSON 工作。 |
| 09:24 前后 | ps 的进程 CPU 约 116%，五线程中一个活跃 worker 约 98%；它不是所有线程均空等的状态。 |
| 09:24:59 | 公开单 Operation GET：RUNNING、sequence 2、updated_at 为 08:09:55.064273、精确 approved_plan_sha256 相同、无 result/error_code；完整 ps 父子树扫描未见该 PID 的子进程。 |
| 09:25:46 | 公开本 Operation model-calls GET 返回空列表；这仅表示该记录没有已保存调用诊断，不能单独证明未执行或已停止。 |
| 09:27:05 | 通过 FileRecoveryStore.get_task_record 完整验证 plan/授权/封存绑定：record SHA 06fae2a5b0ab27cfb7c5696b9536aea262e6eebac295432cd18f5d09db286b03；不可变输入为 NEW/attempts=0，目标 5d121a1；typed get_seed/get_invocation 均 RecoveryRecordMissing。 |
| 09:28:06 | MySQL START TRANSACTION READ ONLY：新 Task 不存在，work_queue_items/claims 为零；精确 dispatch_commit_edc70... 已存在。这与此前 09:06 尚无 dispatch 的诊断不同，已有可核验进展。 |
| 09:28:54 | RecoveryDispatchRecord 的 Schema/digest/SQL 列身份与 plan/task-record 绑定通过；dispatch SHA 74a3f68dacf21cb06bf539695c7be1574f93fd2af972a871808bb3a8de9b89ce，record.committed_at 为 09:14:01.555157，包含 coder/qa/reviewer 三阶段预分配。该字段是记录内时间，不推断 SQL 实际可见时间。 |
| 09:29:49 | 精确目标 worktree 无路径 symlink、.git 存在；受控只读 git rev-parse HEAD 为完整批准基线 5d121a1。没有执行 git status、diff、修改或重置工作区。 |
| 09:31:04 | 再次 typed get_seed/get_invocation 均为 RecoveryRecordMissing；这两项的最新核验仍未见封存记录。 |
| 09:34:29 | typed get_seed 完整核验通过；SHA 17d95bf8c9fc47e0b5caf948be9dad37529aa42b1a165789639cd7bbff81eb28，27 个保留业务文件、完整 343,129-byte patch，未搬入历史环境文件。 |
| 09:36:09 | READ ONLY SQL 实际 Task 已 IMPLEMENTING / attempts 1 / revision 2，真实 Coder WorkItem RUNNING 与 ACTIVE claim；不是预分配 lease。 |
| 09:51:56 | READ ONLY SQL Task 仍 IMPLEMENTING / attempts 1 / revision 2，heartbeat 09:51:52.845044，expiry 09:52:52.845044 UTC。 |
| 09:51:57 | typed get_invocation 完整 lineage/digest 验证通过，SHA 8ccbbe105a6868484cbf5d53f6c134ce29bfcc4800c04ba0bedb959cd9923203。这是新 provider 调用准入，不是实现/验收结论。 |
| 09:52 前后 | ps 完整父子树核验：PID 63772 真实子进程 codex 13186，含其 code-mode-host 13946 和 Python 24314；没有读 argv/环境/provider 正文。实际模型执行已启动。 |

09:58 的第二次 1 秒原生 sample 仍有 Pydantic、Python frame 与 lock 等待，但不含 Python
文件/函数，仍不能将具体线程归属为 Team reader 或恢复执行。临时 sample 完成后删除。

原 Task task_dc5cf0aee44e5ffe0cb600557204e0d0 在同一 READ ONLY 事务中仍为 BLOCKED、
revision 18、attempts 8、原始 base 0a562f4；其 8 个 work items 均 CLOSED、9 个 claims
均 RELEASED。原失败和执行历史没有被恢复动作重置。

## 能定位到哪里，以及仍然未知的部分

执行顺序是 allocate → open_coder → seed → invocation admission。已读 dispatch、目标
checkout 与尚缺 seed 的组合，把可核验边界限定到 dispatch 已提交而 seed 尚未封存的区间；
不能凭这些外部事实证明 open_coder 已返回，也不能断言 seed 的某一行正在执行。

原生 sample 显示服务正在做 CPU 密集的模型验证/regex 工作，未显示当前整个进程卡在
数据库或网络等待。它不包含 Python filename/function，也无法把活跃线程精确归属为
恢复 worker 或 Team reader；因此不能把这一秒的 regex 栈冒充具体恢复调用位置。
项目没有现成只读 Python 栈端点或 faulthandler 接口，本机没有 py-spy。本任务没有安装
远程内存工具、attach debugger、发送信号、读取 locals/heap/env，或暂停服务。

现有服务日志的最新启动记录是 PID 63772，未提供本次恢复内部阶段日志。09:31 时只能
描述为 seed 前的准备/记录发布尚未完成；09:52 已有 invocation 和实际 codex 子进程，
可以描述为 Coder 已实际启动，不能称实现完成或 QA/Review 已通过。原 Operation 的
sequence/updated_at 不是 Agent heartbeat，继续使用独立 claim/process facts 核验。

## Team 长时间忙碌的差分结果

独立研究对同一现有数据运行有界 `ProductionTeamReader.snapshot → to_wire → JSONResponse`，
只允许已有 READ ONLY 事务和 SELECT，不构造 Host、不初始化 SQL。5d121a1 约 6.855 秒，
HEAD 约 7.041 秒；两者均 2 个 requests、25 个 tasks、1,971,810-byte response。
200 个只读 SQL 共约 0.238/0.285 秒，baseline bindings 三次约 3.293/3.387 秒，journal
八次 history 约 1.846/1.808 秒。generic 扫描 32,741 次，HEAD 仅 2,255 hits（6.9%）。
这些数据没有证明多次 Team busy 是 generic/journal 性能导致；不能宣称加载
已有性能补丁就能解决该运行实例的 Team busy。生产在执行，两次 wire digest 不相同也
不能用于静态性能收益证明。下一步定位实际 worker 生命周期，保留现有执行。

现有 worker-owned gate 增量 seam 6 项通过，覆盖取消、读取错误和完整序列化后释放；
尚无 gate 丢失 release 或 reader 等待 execution flock 的证据。离线读取速度正常不能
证明当前 live reader 已停止，也不允许主动释放仍被其持有的 gate。

10:00:42 UTC 的公开 GET `/api/v1/team?project_id=project_ai-project_034252eb3595` 已真实
返回 200，用时 6.919 秒，as_of 10:00:42.544731。原 Requirement 为 DELIVERING，恢复
Task 为 IMPLEMENTING，execution 为 RUNNING/team，真实 Coder queue 为 RUNNING/LEASE_VALID；
旧 Task 仍终态且保留。此前多个有界 GET 的 503 并不能证明同一 reader 连续持锁；
也可能是多次正在进行的读取。没有持锁身份/起止记录时，不把“连续观察到 busy”写成
“单个线程小时级卡死”。本次 API 成功同时证明 gate 已允许并完成新读取，无需手工释放。
整体 7 秒的列表读取仍是体验成本，独立准备明细不能替代其性能改善。

## 当前安全下一步与存量处置

保留同一个精确批准和所有现场，由 root 通过有界的只读事实核对等待 seed、invocation、
实际 Task/claim 或明确失败结果。现已有 dispatch 进展，不重复提交批准、不另建需求、不
清空 worktree、不在仍有活动 Operation 时强停服务。已提交的读取优化需由 root 在安全
维护边界加载；这份诊断没有热替换已运行进程的代码或把目标基线改成未批准的提交。

不存在本诊断引起的持久化数据修改或迁移。SQL 只读事务结束后 rollback/close；读取
凭证只经已有 write-only 配置 store 和连接端口，不输出 DSN、API key 或 provider 正文。
本次原生采样只含调用栈/映像，不含变量数据；摘要已写入本文件，临时 sample 随后删除。
未新增测试或运行全量测试：这是运行事实诊断，非代码修复。
