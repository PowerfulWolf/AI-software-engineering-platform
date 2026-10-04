# 按当前候选限制验证计划恢复扫描

## 问题

`ase request resume` 为寻找当前候选的最新验证计划时，会对候选验证 sidecar 中的所有历史计划
逐个执行完整 `NativeVerificationFacts.validate()`。该校验会重新读取候选来源、Delivery checkpoint、
Artifact、Git 和策略事实；历史候选越多，恢复命令越慢并可能持续占用 CPU，页面无法继续交付。

## 目标与边界

读取每个计划时仍先通过 scoped `FileRecoveryStore.get_verification_plan()` 完成 Schema、摘要、
作用域及关联记录校验，然后只让 `inputs.candidate_revision` 等于当前已验证候选 SHA 的计划进入
完整事实校验。恢复查找保持只读，不改变任何 Task、StateEvent、Artifact、审批、verdict 或旧计划。

## 验收标准

- 旧候选计划不会执行重型事实校验，也不能被返回给当前候选。
- 当前候选的计划仍逐个执行完整 `NativeVerificationFacts.validate()`，按创建时间和摘要选择最新有效者。
- 任意历史计划的 Schema、哈希、作用域或关联记录损坏仍 fail closed，不会被候选过滤掩盖。
- 只运行恢复入口和相关验证记录的增量测试、静态检查与 diff 检查。

## 存量数据与回滚

无需迁移或修改 sidecar/MySQL。旧计划、审批、执行回执和 Delivery checkpoint 原样保留；部署兼容
代码后重新运行原需求的 `ase request resume`。回滚只恢复本次平台提交并重启服务。
