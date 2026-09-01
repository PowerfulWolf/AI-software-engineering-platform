# T010 Verification

- `RetryingOrchestrator` 保持单进程、串行 Coder → QA → Reviewer，不创建 DAG 或队列。
- timeout/provider/invalid output 在 `Task.max_attempts` 内重试当前 role；每次调用前 attempt
  写入 SQLite，重启后从事件最大值恢复。
- QA FAIL 和 Review REJECT 的 finding 只通过持久化 Artifact 进入下一次 Coder Context；新
  implementation-report 不覆盖旧 Artifact，且声明 `supersedes` 与 finding parent。
- budget exhaustion 返回 `BlockedResult`，追加 BLOCKED event，保留最后 finding Artifact；平台
  内部不变量破坏追加 FAILED 并停止。
- T009 的 QA checkpoint 可以关闭数据库后由 T010 继续到 DONE，已确认 Artifact 不重复消费。
- 185 个测试、ruff 和 strict mypy 全部通过；完整 lock/build/diff 检查在提交前执行。
