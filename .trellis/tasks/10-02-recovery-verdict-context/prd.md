# 失败 Coder 恢复保留封存的验证修复要求

## Goal

原生 verification remediation 的 Coder 在 provider failure 后保留改动，精确批准 recovery
必须保留已封存 QA/Review 的具体 finding、criterion、evidence 与候选身份。

## Reproduction

K1 task_continue_9c79c687b1d9e7bf16974a069b6d4339 的失败上下文
ctx_0eaeb5e1ec34b0152c64a27762d77eff1b1b40d0c749f75965145ddddc24fc1d
包含 source:remediation.verification / finding_qa_legacy_corruption_unrecorded。
批准 plan d4abeb12 后的新 Coder 上下文
ctx_50636d61dc6fa339d021d5dcf95fd3e5431e8fbc8e8a4f2bf2445354f2ec3843
缺少该来源。只读断言已失败。代码恢复入口仅重建 parent、prerequisite、recovery.origin。

## Scope / allowed paths

- src/ai_software_engineer/recovery/context.py、entry.py、remediation.py
- tests/recovery/test_recovery_verdict_context.py、test_verification_environment.py fixture
- .trellis/spec/core/delivery-recovery.md 与本 Task 文档

## Acceptance

- 从 RecoveryPlan 已绑定的 failed_context_id 读取原始 Coder manifest，校验 Task/role。
- 缺少验证来源的普通旧任务保持兼容；存在来源时必须恰好一个且完整。
- 从 scoped FileRecoveryStore 重验 exact completion 或 executor prerequisite，以及批准与入场链。
- 比较 scope、URI、脱敏后完整正文；拒绝跨 Delivery、篡改、截断及已通过的 completion。
- 下游 receives required ContextSource，不截断、不提升 128k 预算、不复用旧调用。
- 原生 Task 内的 QA/Review artifact 输入同样保留为 Coder-only 历史反馈，跨代重验正文。
- 独立增量测试和审查通过；当前活跃 QA 无重启、无注入、无 Task/SQL 改写。

## Existing data / rollback

历史 Context、Task、审批、candidate 全部保留。已运行的丢失上下文不补写；本轮新候选继续原生
QA/Review，如失败则正常回派，新 recovery 才加载修复。无 SQL migration。
回滚平台提交并在无活动 role 时重启；保留所有持久事实。

## Verification

Focused pytest remediation/prerequisite/reapply context tests；Ruff、增量 strict mypy、diff check。
禁止全量 pytest。
