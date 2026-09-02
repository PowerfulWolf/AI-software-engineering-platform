# T031 Design

Planner 是计划 Agent，Scheduler/ModelRouter 是其 read-only preview Skills 背后的 pure engines。
Project Manager `commit_dispatch` 使用同一 engines 重新校验，并通过最小 write ports 保存分配。
Preview 与 commit 使用不同 result types，避免建议被误当授权。
