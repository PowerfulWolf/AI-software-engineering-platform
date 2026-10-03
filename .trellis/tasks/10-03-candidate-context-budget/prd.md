# 修复生产候选验证上下文预算不足

## Goal
让生产 QA/Reviewer 能够在完整候选差异必须进入提示的契约下，处理大型但仍处于受控上限内的候选提交。当前生产交付固定 128,000 input token，K1 候选完整差异与既有 QA Context 合计超过上限，QA 在模型调用前被归类为 POLICY_VIOLATION 并使需求阻塞。

## Requirements
- 提升生产交付的明确 Context 上限到 256,000 input token，保留完整候选差异、来源 SHA 和最终提示预算校验。
- 同步候选验证、生产 Host、恢复计划相关规范与文档，说明这是版本化的平台容量契约，不允许截断、静默扩容或伪造 verdict。
- 保留旧 Task、候选提交、未执行 QA 的失败 Run 和审批历史；新验证必须使用更新基线后的新精确计划。

## Acceptance Criteria
- [ ] 生产 ContextBudget 的 max_input_tokens 为 256,000，QA/Reviewer 最终提示仍执行完整预算校验。
- [ ] 128,000 以下的既有正常流程和小候选行为不变；超出新上限仍稳定拒绝且不调用模型。
- [ ] 候选源、Context manifest、schema/hash 和状态机契约无漂移。
- [ ] 增量候选源、Context、生产后端和相关恢复测试通过；不运行全量测试。
- [ ] `.trellis/spec/` 和 docs 记录 failure mode、存量数据处置、回滚方式。

## Technical Notes
- 只修改平台主 checkout；候选需求的历史 worktree 不直接编辑。
- 目标仓库当前绑定 clone 基线为 48b8a0f，平台修复推送后需 fast-forward 到新主分支，再创建新的验证计划。
- 回滚只回滚平台容量修复并保留 sidecar 事实；不得重置 Task 或覆盖候选。
