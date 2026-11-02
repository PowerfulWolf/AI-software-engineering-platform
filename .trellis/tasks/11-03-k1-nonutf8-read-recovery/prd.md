# K1 Coder non-UTF-8 read refusal recovery

## Goal

Keep a harmless, typed refusal to read a non-UTF-8 file inside a permitted repository path from terminating a Responses Coder run. Preserve the refusal and let the Coder choose a different input. Recover the original K1 Requirement through an exact, independently approved successor after the platform repair.

## Current facts

- Approved recovery Operation `operation_7fa77d530f1be7cefac9882259687dc2` sealed Task `task_recovery_83fe12ea23dab6848635d07a8de62f7f` at platform revision `480c3512019c83dedc942a82f1c716bc64ddf422`.
- Coder Run `run_2412aa04ae59413dbd24a10cfeed9d70` selected `codex/gpt-6-sol` Responses and ended with `POLICY_VIOLATION: Responses tool request rejected: read_file/NON_UTF8_FILE`. Task and parent Requirement are `BLOCKED`; no candidate or QA/Review followed.
- The exact requested path is not in the bounded durable error. Do not infer it from the repository or rewrite the old Run.

## Scope and acceptance

- Change only the Responses adapter's handling of the typed `NON_UTF8_FILE` read result, with a real tool-registry + scripted Responses regression. The registry must still refuse binary content; path and command policy refusals remain fatal.
- Verify the Coder receives a `REJECTED/NON_UTF8_FILE` tool output, can make another model call, and no bytes or path leak into the bounded Agent error.
- Document the new boundary in `.trellis/spec/core/python-runtime.md` and the existing-data recovery path in `implement.md`.
- Before live K1 Continue, establish the exact stopped/terminal source, full current Git inventory, frozen K1 artifacts, new platform revision and matching RecoveryPlan. Use only the public interface for the separate approval and new Task. Keep Coder, QA and Reviewer independent.

## Validation and rollback

- Focused adapter and tool tests, Ruff, Mypy, schema checks, then relevant recovery fixture and release checks.
- Roll back to `480c3512019c83dedc942a82f1c716bc64ddf422` by controlled service replacement if the patch regresses role boundaries. Preserve all K1 Task, Run and Operation history.
