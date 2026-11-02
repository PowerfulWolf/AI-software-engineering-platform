# Implementation and live recovery record

## Production diagnosis, 2026-11-03

The public approval Operation `operation_7fa77d530f1be7cefac9882259687dc2` succeeded and sealed a new Task. Its Coder allocation and actual model route were `codex/gpt-6-sol` Responses; the knowledge-intent model call succeeded. Run `run_2412aa04ae59413dbd24a10cfeed9d70` then returned a bounded `POLICY_VIOLATION` with `read_file/NON_UTF8_FILE`, and the new Task and parent Requirement became `BLOCKED`. No candidate or QA/Review was produced. The exact requested path is absent from the durable bounded error, so the operator cannot correctly tell a file owner which path to convert. The original Run, Task and approval remain immutable.

The direct cause is the Responses adapter's fatal classification of every typed tool refusal except `FILE_NOT_FOUND` and two command execution failures. A non-UTF-8 read at an **allowed** path does not violate path or role policy. The registry already refuses the binary content; returning the typed refusal to the model gives it a chance to select a text file without expanding permissions.

## Patch and feedback loop

`tests/agents/test_responses_boundary_diagnostics.py::test_non_utf8_allowed_file_refusal_is_returned_to_coder_without_policy_failure` uses a real committed binary Git file and a scripted two-turn Responses transport. Before the patch it failed `assert 1 == 2`: the adapter ended the Run before the model could receive the refusal. After adding `NON_UTF8_FILE` to the adapter's observational refusal set, the same test passes and asserts the second turn contains `REJECTED/NON_UTF8_FILE` without the binary payload. Existing forbidden QA path/command tests still end in `POLICY_VIOLATION`.

The adapter contract is recorded in `.trellis/spec/core/python-runtime.md`. No Schema, database or UI protocol changed.

Validation: 54 Responses adapter tests passed outside the restricted process sandbox. Ruff check and format passed, full `mypy src` passed in 420 modules, and `git diff --check` passed. A broader sandboxed run had three unrelated owned-process stop observation failures; rerunning those Responses tests with process inspection available passed all 54. `tests/tools/test_registry.py` has the previously observed environment-dependent owned-command error-text mismatch (`group state is unknown` versus `owned command session stop remains unknown`), unrelated to this adapter change.

## Existing data disposition and release gate

The current blocked K1 Task is not edited in place. A read-only `NativeRecoverySourceReader` probe resolved the exact failed Run and Context at base `480c3512`; the inherited approved reapply inputs have lengths 72,535, 0 and 14,863 bytes with matching SHA-256. After publishing and controlled restart, recheck the source, stopped facts, full worktree/capture inventory, registered repository revision and frozen ProductSpec/Design/Plan. Submit one public Continue, review its exact Plan, then independently approve a fresh Task. Coder → QA → Reviewer must run with their separate role allocations. If a source or inventory hash differs, stop before approval and preserve the current history.

Rollback point: `480c3512019c83dedc942a82f1c716bc64ddf422` via controlled service replacement. The old K1 Run and Task remain auditable under either version.
