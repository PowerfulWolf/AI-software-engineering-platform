# 首个 Coder 知识咨询超时

## 目标

当前新 K1 Task 在 Coder 知识评估 120 秒本地窗口耗尽后进入 BLOCKED。没有 Coder 工作区、实现报告、候选或真实角色 route，只有接纳的 plan、Coder context 和已释放 claim。平台把 TRANSIENT_INFRA 一概映射为 RETRY_BUDGET_EXHAUSTED，并且既有 pre-execution restart 只识别二事件的上下文失败或启动故障，导致第一次知识超时不能继续。

## 范围与验收

- Delivery 知识咨询使用单一有界窗口规则：不超过角色既有 timeout，最高 600 秒；上游已批准 stage 窗口继续沿用。不改瞬态/工作额度，不无限重试。
- 本地知识时限是执行容量停止，不能冒充提供方故障或预算耗尽；保留 typed local timeout 的原因。
- 扩展 exact pre-execution plan 的 `restart_kind=pre_agent_knowledge_timeout`，只适用于原始 attempt 1、NEW→PLANNING→IMPLEMENTING→BLOCKED 的精确知识 TIMEOUT tail、原 plan、无 retry failure/accepted role artifact/role route/workspace/live claim/Worker lock。只读取 MySQL，所有矛盾 fail closed。
- 旧 Task 不重置；审核批准 plan digest 后通过 existing fenced continuation 创建新 Task。新 plan 显式绑定当前 preparation/base/branch/config/上下文；冻结批准 Product/Design/Plan 和历史完整保留。
- 联合 child 的原生执行仍使用冻结 backend；restart proposal 必须使用当前 target backend。精确批准新基线后，独立角色都运行同一新候选。
- Console 审批事实区分知识调用与真实 Coder 执行，中文解释。旧预算误分类只兼容读取，不改 sealed 历史。

## 验证和回滚

先写 role window、failure mapping、SQL proof/schema 的增量契约，再跑 isolated Git/MySQL 从首个知识超时→wrong/stale approval→current-base successor→独立 QA/Review→父 DONE。禁止全量或生产库测试。运行 Ruff、生产增量 mypy、Schema parity、diff。存量当前父/子用正式 Continue 生成新 plan、精确批准、继续；不得直接改库。回滚提交并在空闲时重启，保留 sealed 计划/授权/Task。
