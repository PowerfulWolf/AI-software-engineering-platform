# Contract

新增 preserved_verification_context(plan, contexts, verifications) -> tuple[ContextSource, ...]。
只读取精确失败 manifest 的 source:remediation.verification，typed 解析其引用并从已有 store
重新读取校验完整记录；重建 source_id、原 URI 和完整脱敏正文，required=True、priority=2。
原始候选补丁已进入 capture seed/reapply，不重新读取旧 dirty worktree。
RecoveryPlan wire 未变，其 failed_context_id 已内容寻址绑定该来源。

Good：QA FAIL → remediation Coder failure → approved recovery → finding 完整传递。
Base：普通失败 Coder 没有该 section，返回空。
Bad：跨 Delivery、伪造正文、错误 role/Task、截断、已通过 completion，effect 前拒绝。

NativeRecoveryEntry 在 run_prepared_allocation 前将本 required 来源与已有 parent/prerequisite
sources 组合。预算由现有 builder fail closed；没有旧 verdict 重写或新 model authority。

原生 Task 的 source:artifact.<id> QA/Review 输入由同 Repository 的 read-only FileArtifactStore
重验；首次输入必须属于失败 Task。保留为 Coder-only recovery.feedback.<id>，后续恢复的
content-addressed failed manifest 绑定该历史来源，仍重验 artifact/URI/完整脱敏正文。
这不是新 Task 的 input_artifacts，也不会迁移或解释原 verdict。普通旧 Context 没有 verifier
反馈时保留原行为；来源指向缺失记录时 fail closed。
