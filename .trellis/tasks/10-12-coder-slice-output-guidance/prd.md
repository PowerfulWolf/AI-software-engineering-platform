# Coder 切片输出指导与诊断

## Problem and scope

The deterministic gate already forbids a complete candidate while a frozen Coder slice
has deferred steps. Both ordinary and Context prompts supply only the work_slice JSON,
while native prose asks the Coder to implement the complete approved plan. The prompt
does not explain how a partial slice must report inherited completion, selected work and
deferred work. Native rejection currently collapses CoderSliceRejected into GIT_CONTRACT.

This is a independently reproducible prospective defect. The subcause of the existing
production K1 GIT_CONTRACT remains unknown; its ephemeral provider output is unavailable.
This change must not retrospectively claim that production failure was a slice failure.

## Acceptance

1. Real Request and Context PromptBuilders share machine-level guidance derived from the
   typed CoderWorkSlice. Native compilation inherits the same guidance exactly once.
2. Deferred work requires coder-progress. Existing completed steps remain completed; new
   completed IDs belong only to selected steps. Remaining includes all deferred and
   unfinished selected steps. Existing drafts alone cannot prove deferred completion.
3. A slice with no deferred work may emit implementation-report only when the complete
   implementation and required verification actually finish. No candidate is synthesized.
4. Real native adapter + Git rejection retains the dirty draft and input HEAD. Identified
   slice errors disclose only fixed typed classes and output hash/byte count, never provider
   prose, dynamic IDs, exception strings or chain-of-thought.
5. Legacy requests without work_slice and non-Coder roles retain previous semantics.
6. Existing rejection gates, schemas, retry/approval history and immutable facts stay intact.

## Verification and rollback

Run only the new scoped agent tests and related planning/agent regressions, then scoped
Ruff, strict Mypy and git diff --check. No database, production API, models or service restart.
Revert the dedicated commit to roll back; no durable data migration is needed.

## 存量数据处置

Do not modify old Task, Operation, failure, outcome, source, artifact, approval or attempt
records. New guidance applies only to future model input, and typed diagnostic applies
only to a freshly observed typed gate failure. Root delivery supervision remains responsible
for the original Requirement's existing public exact investigation/recovery flow; this patch
does not authorize a new recovery path or retry an unknown old result.
