# Python/MySQL 精确候选验证实现

## 交付内容

Continue 的 `python_mysql_tests` 经 typed Console → Manager → Resume → CandidateVerificationEntry 生成新候选绑定计划。selectors 必须精确且覆盖原 Task 所有 criterion IDs；独立请求批准 exact plan digest 后，QA 与 Reviewer 各自执行固定 Python runner，使用独立短寿命 MySQL、专用 principal 和只允许精确 Unix socket 的 OS sandbox。未扩大 Agent shell 或原 Task 权限，不改业务候选。

计划和回执使用 Python/Swift tagged capability；Schema 生成器同步。STARTED、资源 INTENT/CREATED/CLEANUP_FAILED/CLEANED 均保留可重验审批和 invocation lineage。未知执行不重放；过期资源在下一次明确 Python 验证执行锁内精确清理。历史失败的未知 ID/hash 可由后续 CREATED 补全，既有字段冲突仍拒绝。QA PASS 后 Reviewer 中断支持新的精确审批与仅 Reviewer 恢复，原 QA bytes 不变。

## 增量验证

- 10 个相关模块：155 passed、4 skipped，11.72s。包含 Python 选择/发现/runner、资源/执行、旧 Swift、原生 admission、Reviewer 恢复与 Console wire/转发。
- 最后资源清理与执行回归：27 passed，4.66s。新增 created-but-not-started cleanup 覆盖，不启动/重放容器测试。
- 真实隔离 MySQL + macOS sandbox 单 fixture：1 passed，9.40s。真实验证 SQL、root/跨库拒绝、源码/deny 路径、socket 替换和 TCP 拒绝、TERM→KILL 收敛。
- Ruff check/format、17 个受影响生产文件 strict Mypy 与 git diff --check 通过；四份生成 Schema 由独立 QA 比对一致。
- 独立 QA 与 Reviewer 已只读验证历史清理链、进程组回收、凭证截断与生产 field 接线。它们是平台修复验证，不是 K1 原生 QA/Review verdict。

未运行全量测试，遵循用户增量测试要求。

## 存量数据处置

不需要 SQL migration，不重写 Task/预算/审批/verdict/旧 artifacts。K1 Task `task_recovery_e35017a761b1037b5a1318e151250922` 的 candidate 保持 `bd40ce051cf8f0fcc70009f493d8fd2cba32d833`。服务无活跃角色时重载，通过原 Continue 提交具体节点、新计划、新精确审批，继续原生 QA/Reviewer；不能复用已消费旧审批，也不重跑 Coder。

## 限制与回滚

Unix proxy 只证明 SQL 语义，不验证 TCP/DNS/TLS。已启动容器自启动起最多 1200 秒；create→start 崩溃可能留未启动对象/卷，依赖下一次明确执行按精确过期 intent 清理。此对象没有运行 SQL、候选凭证、host binds 或公开端口。回滚平台提交/禁用新 Python 提案，保留所有历史记录和候选，按精确 intent 收敛剩余资源；禁止批量删除。

当前状态：代码已验证，尚未生产激活；恢复结果在实际操作后追加。
