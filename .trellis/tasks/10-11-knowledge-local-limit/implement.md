# Implementation Handoff

状态：`review_ready`。核心实现、相关增量测试和局部质量门已完成；独立 review、统一提交/
推送及生产装载由 root 执行。本代理没有操作生产，没有代替业务或工程审批。

## 改动

- `domain/delivery_resolution.py`、`domain/delivery_disposition.py`：新增知识本地窗口等待/
  resolution、exact evidence、双 Requirement 身份及旧嵌套 wire 的 None 省略。
- `knowledge/invocation.py`、`knowledge/preparation_retry.py`：typed 完整 local-limit 结果、
  独立停止重读、只读 lookup index、immutable claim fingerprint、有界冻结窗口证据。
- `knowledge/runtime.py`、`knowledge/legacy_scope.py`：只按当前实际 claim 读取已消费
  timeout；复用 exact legacy gap/snapshot 归属，禁止仅靠 Task 命名放宽。
- `orchestration/retry.py`、`manager/delivery_wait.py`：专用非终态工程等待、精确调查/
  resolve 再核验、按旧冻结授权决定，工作预算/窗口耗尽不提供必败动作。
- `work_queue/execution_store.py`：MySQL fence 原子消费同 Task 工作额度、新 WorkItem/
  step/claim、幂等重放和已消费 `WAIT_RESOLVED` 有界窗口链。普通 provider 后继保留窗口。
- `manager/production_backend.py`、`manager/production_host.py`：生产 composition 连接
  当前真实队列 timeout 和同 Task idle-scope窗口读取，保留 native Requirement 归属。
- 4 个 owned test files：knowledge context、native invocation、shared scope、真实 MySQL
  知识续跑；Schema/前端/history分别由独立代理负责并交叉审查。

没有新增依赖或数据库 Schema。具体测试结果见 `verification.md`。完整契约、存量数据处置、
部署边界和回滚方式见 `.trellis/spec/core/knowledge-local-limit.md`。
