# 终态候选在准备摘要漂移后仍可进入验证

## 问题

Delivery 已经保留了 Coder 候选，但候选验证 sidecar 还没有当前候选的计划时，`request resume`
仍先调用旧的原生阶段重试。旧阶段绑定历史 preparation 摘要；项目准备事实发生合法更新后，
该调用返回基线漂移错误，导致新的独立 QA/Reviewer 计划无法生成。

## 目标与边界

- 只要终态 checkpoint 有 `candidate_revision`，恢复入口直接处理候选验证计划。
- 有已完成的验证结果时沿用既有完成、修复或重试路径。
- 没有当前计划时生成绑定当前事实的精确验证计划，并保留人工审批和独立 QA/Reviewer。
- 不修改旧 Task、Delivery checkpoint、候选 Artifact、审批、verdict 或 preparation 记录。
- 没有候选 revision 时继续使用原生恢复和 Coder recovery 流程。

## 验收标准

- 终态候选无当前计划且 preparation 已漂移时，不调用 `retry_interrupted_stage`。
- 恢复入口返回新的验证审批要求，计划绑定当前候选。
- 已有验证完成的候选行为保持不变。
- 非候选终态仍走原生恢复流程。
- 只运行恢复/验证相关增量测试、Ruff、格式检查和 `git diff --check`。

## 存量数据与回滚

无需迁移或修改 sidecar/MySQL。已有候选、旧计划和 checkpoint 原样保留；部署后从当前 Delivery
重新执行 `ase request resume`，批准新计划后再运行独立 QA/Reviewer。回滚只需恢复平台提交并在
空闲时重启 ASE，不能删除或重写新生成的计划。
