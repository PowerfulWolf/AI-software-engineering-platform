# QA/Review 回派后的调用前知识失败恢复

## Goal / reproduction

K1 task_recovery_d4abeb12 的 candidate e41ffbb7 收到真实 QA FAIL，attempt2 在知识准备阶段
TIMEOUT，未调用 Coder，干净 worktree 被正常 cleanup。正常 Continue 和32节点受控验证提案
均被 NativeCandidateSourceReader 拒绝：candidate has newer interrupted Coder work that must be
recovered first。该判断把交付状态回派当成发生了新的代码执行；既没有失败 Coder run 可恢复，
也无法通过新精确候选验证获得正常 remediation。

## Scope / acceptance

- 只在 exact QA/Review feedback 后 AUTHENTICATION_ERROR/TIMEOUT，且 Task BLOCKED、attempt紧邻时
  允许重新提案 retained candidate；原 QA/Review 结论保持不变。
- 只读验证最新 candidate 的完整已接纳 implementation/model route、没有后续 Coder provider
  execution，没有有效 claim/RUNNING work item，Coder branch/worktree仍精确clean candidate。
- 读取当前attempt唯一封存consultation-input，重验binding、完整base Context、Task/feedback与input
  SHA，并证明该咨询尚未完成；adapter已进入后抛StructuredModelError必须拒绝。
- absent worktree 必须有 manager-owned exact removal marker，不能只信路径缺失。
- 新验证必须新审批、独立QA/Review；FAIL正常进入新基线 Coder，不修改旧Task/预算/审批。
- 真实 Coder 中断/dirty/未知失败继续要求原有恢复，无 shortcut。
- 增量正反契约、Git/isolated MySQL、独立检查通过；不跑全量测试。

## Allowed paths / rollback

src/ai_software_engineer/recovery/candidate_preflight.py、verification_native.py、progress_source.py
（共用稳定知识失败reason常量）；
src/ai_software_engineer/git/worktree.py；tests/recovery/test_resume.py、新helper tests、
tests/git/test_semantic_branches.py；.trellis/spec/core/delivery-recovery.md 与任务记录。
回滚平台提交并空闲重启；零生产 SQL 修复、零历史写回。
