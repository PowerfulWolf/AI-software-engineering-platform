# 增量验证

- 真实隔离 MySQL：`tests/manager/test_public_context_capacity_baseline.py` 一轮、两轮容量
  等待均完成原 Task 的 Coder → QA → Reviewer → DONE；attempt=1，无 retry refund。
  一轮公开流程额外验证缺 receipt、完整重封异属 claim、缺 Context、已有 invocation、
  orphan/corrupt native stop/receipt/admission 和不可读取 native ledger 根全部拒绝；
  原 Task/events/queue/保留现场不变。
- 16 项 `test_execution_baseline_invocations.py` 与新
  `test_context_capacity_baseline_schema.py` 通过；原 preflight 多 claim/history 语义不变。
- 49 项 reservation、wait-fact、paused service、context receipt 测试通过。
- 25 项既有 baseline service / fresh repair schema regeneration 测试通过。三处内嵌 Facts
  的字段、正反 wire guard 和旧省略字段/hash 均校验；生成器重复生成保持相同结果。
- 改动 5 个 Python 文件 Ruff check/format、严格 mypy 通过，`git diff --check` 通过。
- 独立只读 review 补充发现并修复 no-start 时 orphan native stop 和不可读取 ledger 根
  不能视为缺记录；公开反例覆盖这些缺口。不跑全量测试。

存量数据处置：本分支不操作生产 DB、服务或 ASE 需求。真实 receipt 的非终态 Coder 等待
部署后通过原需求 source-rebind proposal → 精确 PAUSE → explicit continue；原终态 K1 仍
由其独立受控恢复服务核验，不能获得本路径权限。无自动重开、退款、审批或 verdict。

回滚：保持 receipt/Facts/proof/baseline 兼容 reader；已经记录新决定后保留审计历史和
worktree，优先前进修复。禁止删除 records、重置 Task、清空 Git 或直接改 SQL 绕过审批。
