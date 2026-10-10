# 原执行事实封存与基线更新闭环

## 目标

用户需要在原需求、原 Coder 分支和保留现场上更新已修复的平台源码，再明确继续。
PROPOSE_EXECUTION_BASELINE 应能复用已存在的真实事实收集器，封存完整合法的 v2 中断进度。
准备方案不继续需求、不修改预算/Task/queue、不调用模型。执行精确方案选择 pause，
用户审阅并批准真实规范变化后更新基线，显式 RESUME 才能继续原 Coder → QA → Review。

## 范围与验收

- 复用 DeliveryWaitFactCollector，不新建 seal-only API 或放宽 legacy containment。
- scope持有Task lock与SQL idle fence；避免第二层idle锁。exact 当前命令在封存前验证。
- 仅 source_rebind 未解决 EXECUTION_UNCERTAIN/PLATFORM_BUG 等原执行工程等待触发收集；
  EXECUTION_BASELINE_PAUSED 和普通已授权preflight不能盲读旧 start。
- 真stop + 完整合法源码无receipt可以生成一次可信receipt和proposal；重复准备幂等。
- 活/未知进程、缺cause/code、错误scope/claim/source、真实secret、完整输出均保持原拒绝。
- stale command不写receipt/Task/queue/Git/额度；成功结果不转换成失败重试。
- PAUSE阶段零模型调用；RESUME之后仍是同Task/branch/worktree和独立QA/Review。
- 仅增量tests；组织规范记录新增composition约束、错误矩阵与存量操作步骤。

## 验证与回滚

真实Git+fake adapter contract tests先red后green，现有公开Host基线pause流程回归。
Ruff、strict Mypy、diffcheck。无数据库迁移或历史改写。回滚仅代码，保留新sealed事实；
原用户仍能通过现有HANDLE或精确基线执行路径处理，不删除现场或新建需求。
