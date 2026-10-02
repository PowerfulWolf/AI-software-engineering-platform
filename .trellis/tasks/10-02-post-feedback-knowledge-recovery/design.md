# Contract

`require_clean_coder(spec: WorktreeSpec) -> None` 为 GitWorktreeManager 的只读校验：已有worktree
用recover/inspect验证HEAD、branch、dirty；已清理的semantic branch必须精确revision和removal
marker。不得创建worktree或改变ref。

`require_unchanged_pre_provider_candidate(config, environment, sidecar, checkpoint, runtime,
implementation) -> None` 在 NativeCandidateSourceReader 发现post-feedback Coder状态后校验：
exact final feedback→BLOCKED / allowlisted knowledge reason、紧邻attempt、artifact identity；
accepted implementation的sealed successful Coder route一致且无更晚Coder运行；无active worker；
manager-owned Coder checkout/branch仍是完整candidate。先有完整artifact provenance再运行该门。

当前attempt唯一 `KnowledgeConsultationInput` 必须绑定 same Task/Coder/Team/Project/Repository/
candidate/base Context/snapshot，重算 `input_sha256=digest({task: pre-block Task, context: full base})`
和 `run_knowledge_<digest(context_id,snapshot)[:32]>`。该完整base必须含原feedback且不存在对应
`consultations` 成功记录。KnowledgeRunContextBuilder只有consult返回并追加knowledge.consultation
后才允许调用adapter；因此它是调用前来源证明，不能仅靠错误字符串或缺完成route推断。
Review REJECT同时绑定terminal-tail的exact qa_passed parent，报告不得supersede另一轮。

Good：QA FAIL→Coder知识TIMEOUT且clean removal→新精确候选验证审批。
Base：普通终态verifier仍原行为。
Bad：真实Coder运行、dirty/ref漂移、missing marker、未知reason、active claim→原有拒绝。
不生成虚构failed_run，不变更Schema/state机，不使用旧verdict批准新candidate。
