# K1 frozen route transition recovery

## Goal

Continue the existing K1 Requirement using the configured Responses route after a retained Coder Task was dispatched to Codex CLI. Preserve its 13-file draft, immutable history and independent QA/Review.

## Scope and acceptance

- Refuse an incompatible route before consuming a paused same-Task baseline continuation. Keep its authorization, queue and Task facts unchanged.
- For the existing blocked child, verify the expired claim, no new invocation, exact latest baseline and complete retained draft under a task/queue fence. Close the orphan retry and settle the old Task without inventing an Agent result or refunding work.
- Prepare an exact, same-Requirement successor RecoveryPlan from the sealed draft and current registered `main` revision. Its new dispatch must select the configured Responses route and require independent approval, Coder, QA and Review.
- Reject active/unknown ownership, changed draft, extra files, missing records, route ambiguity, changed checkpoint or changed source. Preserve all original records and history.

## Working boundary

Platform base: `e09c41e5c6268e6bfb2d186967e8361094e480ab`. K1 source repository main now matches this revision. Existing Task: `task_recovery_f1932aacd0b41cfc046b7d493f00e393`; current checkpoint remains BLOCKED while the Task is IMPLEMENTING revision 5 with attempt 6. The sixth claim is EXPIRED and no invocation record exists. Latest sealed baseline captures 13 files, all still matching their saved SHA-256. A read-only `NativeRecoverySourceReader.discover_failed_coder` run reproduces the missing-identity rejection.

## Validation and rollback

Contract tests cover good, base and bad route/ownership/capture cases, including public Continue → exact plan → approval → new claim. Run focused pytest, Ruff and Mypy, then broader required checks. Publish only after controlled service pause. Rollback restores the previous service binary; immutable plans and settlements remain in history, and no old Task is resumed.
