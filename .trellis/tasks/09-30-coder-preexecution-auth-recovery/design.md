# 设计

`is_prior_progress_source(route, task, checkpoint, events)` 是纯判定：仅允许相邻 attempt、
精确四事件尾部、共同 progress ID/基线和明确知识 AUTHENTICATION_ERROR/TIMEOUT。
Native source reader 同时读取 SQL 事件并在末尾重读，复用既有原审批链/dispatch/父需求校验。
上一 attempt 来源必须额外通过 sealed artifact digest、停机事实、当前 worktree inventory。
普通当前 attempt 的失败/budget-exhausted progress 恢复保持原契约。

`CodexCliStructuredModelClient` 使用 `--json`；只解析顶层 error.message / turn.failed.error.message，
有界读取最后 1MB、每行最多 64KB。item.completed 等自由文本不得产生 provider 错误。
无诊断 watchdog 仍为 TIMEOUT/local_execution_limit，真实 401/403 不 fallback。
JSON Schema 保留已持久化的三项 retry_of_* 字段以便只读审计；平台批准仍绑定完整捕获补丁与 current-facts verifier。

Good: accepted attempt 1 progress + attempt 2 knowledge failure，普通精确计划审批。
Base: 旧失败 route/工作额度耗尽 recovery 不变。
Bad: 无已接纳 progress、任意历史 attempt、后续模型执行、改写旧 Task 或伪造最新 Run。

原先“从未 provider admission”的扩展基于不完整事实，独立审查发现其 freshness 隐患；
已移除该生成/执行扩展，仅保留已落盘计划的读取兼容，旧未执行 Task 留在历史中，不用其旧 seed 覆盖最新 8 文件工作。
