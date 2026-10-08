# Goal
旧 K1 第六轮只有真实 invocation start，原 final、stop、capture start 均不存在。
普通用户不能通过反复调查补齐这些历史事实。提供同一需求、同一 Task/branch/worktree
的受控工程现场救援，绝不把新工程观察伪装成原调用结果。

# Scope and constraints
复用 execution-baseline 的完整捕获、exact plan/authorization、append-only binding 和
owner-fenced queue consumption。新增独立 legacy_workspace_rescue purpose，不改变源基线或规范。
不操作生产 ASE、不审批/恢复需求、不重启服务/电脑、不写生产数据库。增量测试。
允许路径：domain/execution_baseline、manager/baseline*、manager/legacy_*、execution_baseline、
production_host/backend、work_queue/baseline、web_console/models/manager/transport、team_view/app.js
及工程历史、相关 schemas/tests/docs/spec 和专用增量 Schema 同步脚本。

# Acceptance
- 原调用仍 UNKNOWN；不创建 invocation outcome、original stop、interruption receipt 或假 progress。
- 可信 OS observer 采集本机 boot session/time，必须晚于原 invocation start。service restart、
  lease expiry、free lock、absent PID 均不满足。无旧 host identity 时独立工程批准必须明确确认
  原执行在当前同一设备、没有迁移/远程执行、原执行后已完成整机重启，且认可时钟依据；
  作为人工补证据审计，非自主恢复。
- 不满足前提时中文说明重启整台原执行电脑后再检查；不让用户核验 hash/lease/PID。
- 方案封存完整合法当前现场，精确绑定原 start/claim、Task/queue/source/native rules，前后复核。
  执行救援不改任何源文件/HEAD/index/branch，不更新业务范围，不丢草稿。
- 旧工作额度保持消耗；下一调用消耗下一工作额度，不退款、不伪造 transient failure。
- 新 WorkItem/Run/Context 真实 claim，独立 Coder→QA→Review gates 保持。
- 旧 digest/readers 兼容；所有新证据/授权/处理历史完整可读。
- public Console → Host → service → fenced consumption → native Coder 增量 fixture 验证。

# Rollback
未写入新版事实时，空闲停止服务后可回滚代码。已有新版 immutable 记录时保留兼容 readers
并向前修复；不清理现场、不重写旧历史。

# Read-only production findings
Task task_dc5cf0aee44e5ffe0cb600557204e0d0，Run run_9b76fb2865144f2abb6407923320ec4e；
原 start 2026-10-06T14:30:21.294710Z。无 final route/capture start/capture stop/receipt。
当前机器 boot 早于该 start，因此目前不能直接救援；部署修复后仍需用户完成真实 OS 隔离前提。
