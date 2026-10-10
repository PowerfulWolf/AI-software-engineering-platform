# 正式恢复批准的最新执行边界（2026-10-10，只读诊断）

## 对象与结论

- Operation：operation_bacb1b32b242923bc2d4dbad68818733。
- 原 Requirement：delivery_multi_8a5103309c232515bcf733947d32830365dd02c6。
- 精确批准 plan：edc70b3d943c52d85a079da433d43934f84e5c284f3c0dbbd74b09ae5a63a2c3。
- 恢复 Task：task_recovery_edc70b3d943c52d85a079da433d43934。
- 服务仍为 PID 63772，未进行维护、重启或运行时注入。

最晚已核验的持久化边界已经从 Task 输入封存推进到精确 recovery dispatch 提交；目标
Coder worktree 存在且 HEAD 为批准的 5d121a107fbbd7b5d1341ce4aff8bfc6ecb32874。
截至本次最后 seed/invocation 检查，两者仍未发布。新 Task 尚未写入 tasks，尚无新
work item 或实际 claim。不能把三阶段的预分配记录视为实际 Coder/QA/Reviewer 执行。

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

现有服务日志的最新启动记录是 PID 63772，未提供本次恢复内部阶段日志。因此已接受请求
持续 RUNNING 的原因可以描述为“仍未完成 seed 前的准备/记录发布”，不能描述成“已启动
Coder”、模型无响应、已成功恢复或旧执行一定未停止。

## 当前安全下一步与存量处置

保留同一个精确批准和所有现场，由 root 通过有界的只读事实核对等待 seed、invocation、
实际 Task/claim 或明确失败结果。现已有 dispatch 进展，不重复提交批准、不另建需求、不
清空 worktree、不在仍有活动 Operation 时强停服务。已提交的读取优化需由 root 在安全
维护边界加载；这份诊断没有热替换已运行进程的代码或把目标基线改成未批准的提交。

不存在本诊断引起的持久化数据修改或迁移。SQL 只读事务结束后 rollback/close；读取
凭证只经已有 write-only 配置 store 和连接端口，不输出 DSN、API key 或 provider 正文。
本次原生采样只含调用栈/映像，不含变量数据；摘要已写入本文件，临时 sample 随后删除。
未新增测试或运行全量测试：这是运行事实诊断，非代码修复。
