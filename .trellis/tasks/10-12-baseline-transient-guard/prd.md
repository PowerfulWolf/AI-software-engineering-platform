# 源码基线接续不得把非临时失败记为临时故障

## 目标与范围

`ProductionBaselineFactCollector._reservation` 对已封存 outcome、没有 interruption receipt
的原调用，必须同时要求错误类别在 `TRANSIENT_CODES` 中且 `error.transient == true`，
才可创建 `provider_transient` 预留。错误类别不能单独证明故障可重试。

## 验收标准

- 真实 typed/store outcome 为 `PROVIDER_UNAVAILABLE / transient=false / FAILED / no artifact`
  时拒绝基线接续，不生成退款或下一执行身份；普通工作额度是否耗尽均如此。
- 四个已允许的临时类别均覆盖 true/false；真正 typed transient 可使用原冻结故障额度，
  保持普通工作计数，exact replay 不重复记账。
- 非允许类别即使标记 true 也拒绝。
- Task、原 outcome、retry facts 和 store bytes 在准备/拒绝过程中保持不变。
- 已有合法中断 receipt、AUTH 前提修复和独立 QA/Review 门不变。

## 允许路径与验证

允许路径见 `task.json`。先运行新参数化回归确认红，再补最小 guard；仅运行相关 reservation、
invocation 和 stopped-provider 测试，以及 Ruff、strict Mypy 与 diff 检查。

## 存量处置与回滚点

不改历史 outcome、Task、预算或数据库。未被接纳的非临时失败仍须工程调查，不能靠源码更新
获得临时故障退款。既有普通授权耗尽时不授权新的调用；合法恢复能力由独立任务负责。
回滚点为 `5d1ebc718f1b5ee17435615b8cdf55afefa64220`。
