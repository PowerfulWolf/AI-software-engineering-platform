# K1 Responses source-module write refusal and terminal recovery

## Goal

Allow a Coder to edit an explicitly approved source module whose package is named `artifacts`, while preserving the ban on role-owned delivery artifacts, verdicts, state, Trellis, and unauthorized paths. Recover K1 from the completed `write_file/PATH_DENIED` Run through a new audited Task, without replaying or rewriting the failed Run.

## Scope and acceptance

- Diagnose the exact immutable K1 run and write policy. The rejected request path was not persisted; do not assert it was the approved source module without proof.
- A real `PolicyBoundToolRegistry.write_file` test must reproduce rejection of Task-approved `src/ai_software_engineer/artifacts/accepted.py` before the fix and acceptance after it.
- Protected artifact/verdict/state outputs, `.trellis`, QA production writes, Reviewer writes, symlinks, and Task-denied paths remain rejected.
- A completed Responses `write_file/PATH_DENIED` Run with an unchanged complete worktree inventory and only previously approved Coder draft can produce a same-Requirement RecoveryPlan. It must require a fresh engineering decision and a new Task/Run, preserving original outcome and the complete inherited patch. A genuinely unauthorized attempted write must never be performed or reclassified as success.
- K1 ProductSpec, TechnicalDesign, ExecutionPlan and candidate remain frozen. New Coder must still undergo independent QA and Review.

## Allowed paths

`src/ai_software_engineer/tools/registry.py`, `src/ai_software_engineer/recovery/{workspace_snapshot,workspace_records,models,entry}.py`, `schemas/delivery-recovery.schema.json`, `scripts/sync-recovery-workspace-schema.py` if needed, `tests/{tools/test_registry.py,recovery/test_workspace_snapshot.py,recovery/test_workspace_plan.py,recovery/test_responses_terminal_public.py}`, `.trellis/spec/core/{python-runtime,delivery-recovery,responses-wire}.md`, `docs/architecture/contracts.md`, and this task directory.

## Verification and rollback

Run focused registry, Responses and recovery tests, Schema regeneration check, Ruff, Mypy and isolated MySQL/Git public recovery fixture. Inspect the exact production K1 Task and draft before any public Continue. Rollback code to the prior platform main only before a new recovery decision; after publication preserve all append-only facts and repair forward.
