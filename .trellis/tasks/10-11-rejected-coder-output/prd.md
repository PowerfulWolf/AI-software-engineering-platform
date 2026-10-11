# 已停止拒绝产出的受控续跑

## Goal
当前K1 attempt4原进程真实completed且已有SUCCEEDED outcome，但coder-progress序号非法。
Task仍IMPLEMENTING、原工作区dirty，没有安全的公开恢复入口。补齐同Task的受控续跑，
保留全部原现场与拒绝历史；不能改写旧artifact、强制终态、重建需求或伪装timeout。

## Acceptance
- 通过原需求HANDLE_DELIVERY_WAIT公开入口验证并封存精确原调用和完整现场。
- 独立typed拒绝checkpoint及精确resolution；正常消耗1次工作额度，不退transient。
- 原Task/branch/worktree不变，新attempt/Run/claim，不接纳旧progress为候选或checkpoint。
- 拒绝产物保留原字节和publication receipt，仅排除精确ID，不排除合法祖先。
- 当前source/HEAD/index/完整inventory/授权/真实停止/队列claim/StateEvent均重新验证。
- 有任何漂移、未知进程、候选/verdict、预算耗尽、缺证据或policy问题均fail closed。
- UI中文说明原产出未通过、开发文件保留、下一轮重新整理报告，独立QA/Review仍必要。
- 先红回归；正反/边界测试、至少真实MySQL原子消费回归；不跑全量。

## Existing data
精确目标为task_recovery_8ca06fa0aec236ab940597ad1482bfc8的attempt4。
不改库/原outcome/artifact/stop/claim/事件，新增封存和决策事实，公开精确批准继续。
实际处理前后核对Task身份、attempt、分支、原文件inventory和不可变历史。

## Rollback
消费前可回滚新代码但保留新审计；消费后保持兼容reader/writer并向前修复，
不能裸回退到不认识新resolution的服务或删除授权/消费记录。
