# 允许修复轮候选进入独立 QA/Review

## 目标

修复 QA/Review 打回后生成的 Coder remediation Artifact 无法进入独立候选验证的问题。

## 范围

- 候选读取与候选验证接受 `Plan → QA/Review finding → remediation Implementation` 的封存链。
- 保留首次候选、Coder progress、QA/Review 独立性和完整历史的 fail-closed 约束。
- 不修改存量 Task、StateEvent、Artifact、verdict、审批或目标仓库代码。

## 验收标准

- [ ] 最新 remediation candidate 可以生成精确 verification plan。
- [ ] QA/Reviewer 只读取同一 candidate SHA，并继续独立执行。
- [ ] 缺失、错误角色或错误 revision 的 feedback 仍在模型调用前拒绝。
- [ ] 首次 candidate 和 progress continuation 兼容。
- [ ] 只运行相关增量测试。

## 回滚点

回退平台提交并重启 ASE；保留现有 sidecar candidate verification 计划和失败记录。
