# K1 accepted progress parent attachment

Date: 2026-10-29. Platform base: `4211dd86f04850775147ce4f478e71f317346c0c`.

## Goal and scope

The original K1 `coder_reapply` RecoveryPlan `b06bffe70284000da954ea92ef7196a282f2ac1c99d795964715cc1ab80bc037`
has an accepted first Coder progress Artifact, but its second Coder claim expired
before a model start. A stale parent Delivery cursor incorrectly proposes a
first-execution interruption approval and then rejects the already accepted
progress. Attach the parent cursor to the existing Task and let normal queue
reaping and owner-fenced dispatch continue the same Requirement.

Allowed implementation paths:

- `src/ai_software_engineer/recovery/{entry,resume,bounded_input}.py`
- `tests/recovery/{test_pending_execution,test_bounded_reapply_input}.py`
- `.trellis/spec/core/delivery-recovery.md`
- This task record.

No ProductSpec, Design, Plan, candidate, runtime sidecar, production database,
Schema or role verdict is modified by this patch. `bounded_input.py` changes
only the incorrect equality between queue Task revision and Coder attempt, and
the incorrect equality between initial role step and later publishing claim
generation. Publication still binds the immutable step, exact original claim,
source, Run, assignment and receipt digest.

## Acceptance and verification

1. An accepted progress requires a sealed Artifact, accepted queue publication,
   Task continuation event, complete first invocation outcome, exact approved
   Plan and consumed source schedule.
2. Current no-start proof scans invocation, model route and native capture stores
   by WorkItem and Task attempt. A writable or unknown old claim refuses attachment.
   Expired original and reaper-generated claims remain historical.
3. Parent attachment is read-only with respect to Task/queue/sidecar and yields
   `DELIVERING`; the next public Continue uses normal reaper/dispatch. No new
   first-Run approval or fabricated stop/outcome is created.
4. The K1 production read-only checker returned `NativeRecoveryPending` at Task
   revision 5, with the Task/queue SQL digest and all 5,479 sidecar file contents
   unchanged before/after. Current event tail is `coder_requested_continuation`
   attempt 1 → `coder_continuation_queued` attempt 1 →
   `coder_continuation_resumed` attempt 2. The second WorkItem was RUNNING with
   one expired ACTIVE claim; it had no known native/model invocation fact.

Validation commands from the repository root:

```text
.venv/bin/pytest -q tests/recovery/test_bounded_reapply_input.py
.venv/bin/pytest -q tests/recovery/test_pending_execution.py -k 'durable_progress or durable_accepted_progress or accepted_progress_reattaches'
.venv/bin/ruff check src/ai_software_engineer/recovery/{entry,resume,bounded_input}.py tests/recovery/{test_pending_execution,test_bounded_reapply_input}.py
.venv/bin/mypy src/ai_software_engineer/recovery/{entry,resume,bounded_input}.py
git diff --check
```

The complete `test_pending_execution.py` file currently has seven pre-existing
failures in fixture paths that call `require_current_plan` before this new
branch. Those failures do not exercise `pending_progress_continuation`; the
targeted regressions above are the release evidence for this patch. Full suite
and public K1 continuation are separate release gates.

Final local check: the four related test files above reported **66 passed,
7 deselected** when only those seven existing cases were excluded. Ruff check,
Mypy on all three changed source files, Ruff format check and `git diff --check`
passed. A clean archive of base `4211dd86` reproduced the same seven failing
case IDs in `test_pending_execution.py` (16 passed, 7 failed), so they are not
introduced by this patch. The new durable accepted-progress/claim/native-route
matrix has 10 passing cases, including RELEASED claim with a future original TTL.

## Existing data and rollback

No production fact was changed during diagnosis. Release the platform code by
controlled idle restart. A public Continue on the original K1 attaches its
existing recovery Task to the parent Delivery cursor; one further Continue
may be needed after the reaper's retry delay. Keep the old accepted progress,
claim and UNKNOWN history. If public continuation does not pass exact current
facts, stop and inspect the reported durable mismatch; do not reset the Task or
recreate the Requirement.

Rollback point is platform base `4211dd86f04850775147ce4f478e71f317346c0c`.
If a new parent checkpoint has already been attached, do not run the old binary
against that cursor. Pause new Continue operations and restore the fixed binary;
no migration or inverse database operation is required.
