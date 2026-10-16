# Re-enter public recovery for a stopped unknown Coder behind a blocked delivery checkpoint

## Goal

Recover the original K1 through the public Continue/baseline path after a raw owned-process
exception left delivery BLOCKED, Task IMPLEMENTING and one expired ACTIVE claim. Preserve
the same Task, branch, frozen source, full draft, accepted progress and honest UNKNOWN history.
The native exception-routing fix f3be38e alone cannot reach this stored state.

## Exact scope and non-goals

Add a narrowly gated public Continue re-entry using the existing typed
StoppedCoderExecutionProof. Reuse Dispatcher expiry/reclaim and Worker fenced wait/release;
do not add SQL mutation helpers, a generic BLOCKED retry or a new recovery purpose/Schema.
DurableInvocationControl must prevent another main Coder call. Subsequent recovery uses
existing STOPPED_EXECUTION_RESCUE, exact PAUSE approval then separate RESUME.

For newly produced same-base STOPPED_EXECUTION_RESCUE bindings, preserve accepted progress
as already done for STOPPED_FAILURE_RETRY. Historical retirement bindings remain immutable;
no reader reinterpretation or revival. New source-rebind/reapply still retire progress normally.

Allowed source: manager/stopped_execution_checkpoint.py, manager/baseline_production.py,
manager/production_backend.py, manager/delivery.py, recovery/resume.py and
manager/execution_baseline.py under src/ai_software_engineer. Allowed tests:
tests/manager/test_stopped_execution_delivery.py, test_stopped_execution_rescue.py,
test_stopped_failure_retry.py; tests/orchestration/test_baseline_history_inputs.py;
focused new tests/manager/test_stopped_execution_reentry.py if needed. Additional necessary
paths must be explained to root before editing. Root owns specs and task docs.

## Acceptance

- RED public real-native/MySQL fixture: original rawOwned leaves blocked delivery while Task
  remains IMPLEMENTING; public Continue reclaims the stopped expired claim without another main
  Coder invocation, then a fresh claim hits the durable guard and enters proper engineering wait.
- Require precise stopped proof, Task/checkpoint/step/source/scope/claim match, unique original
  WorkItem/claim, current expired lease and current original-session emptiness. Refuse live/newer
  claim, any route/result/output/receipt/raw original-Run artifact, drift or generic BLOCKED.
- Keep original files/Task/events/attempt/source unchanged throughout re-entry; later rescue
  consumes ordinary work once, pauses, resumes under new ownership, and independent QA/Review
  can complete. Do not call knowledge preparation a failed or unclaimed invocation.
- Service-to-runner regression proves accepted steps01/02 and exact continuation paths survive
  a newly produced same-base stopped rescue; later selected work excludes those completed steps.
- Relevant negative and historical retirement cases stay green. Ruff/format/strict Mypy and an
  independent read-only review are required. Isolated MySQL tests run serially.

## Existing data and rollback

No production SQL edits, retrospective cause/outcome, new Requirement, source rebase or direct
K1 checkout write. Original Run6 proof has been independently rechecked EMPTY_CONFIRMED using
the original proof on the host; this is not a new stop record. Deploy through a verified idle
controlled restart after review. Use fresh public facts for Continue, rescue proposal, exact
PAUSE and separate RESUME. Preserve all history and compatible readers on rollback.
