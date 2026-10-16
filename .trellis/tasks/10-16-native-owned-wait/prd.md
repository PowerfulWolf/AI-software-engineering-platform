# Native ownership uncertainty must preserve a fenced engineering wait

## Goal and observed failure

Original K1 Run6 has a real capture-start and real failed capture-stop at
2026-10-16T06:00:39.964648Z, but no final invocation outcome. The parent records
INVARIANT_VIOLATION / OwnedProcessesUncertain; its WorkItem remains RUNNING with an expired
ACTIVE lease, rather than a released engineering wait. Keep the complete source/history.

## Scope

Normalize genuine OwnedProcessesUncertain at the native runner/adapter boundary and fence
all such failures, including outer evidence-finalization uncertainty, into the supervisor's
existing EXECUTION_UNCERTAIN wait. Do not synthesize output, provider cause, receipt, progress,
candidate or verdict. A later proven stop does not prove why observation originally failed.

Allowed implementation paths: src/ai_software_engineer/agents/codex_cli.py,
src/ai_software_engineer/work_queue/worker.py, tests/agents/test_native_output_bounds.py,
tests/agents/test_codex_cli.py, tests/work_queue/test_owned_execution.py and
tests/work_queue/test_worker_mysql.py. Root owns
.trellis/spec/core/owned-session-stop.md, persistent-work-queue.md and this task directory.

## Acceptance and verification

- First RED: a real isolated native child suffers one injected active observation refusal;
  its actual stop/EOF is verified, the observer seals stop, and the typed execution uncertainty
  reaches the caller instead of a raw exception.
- First RED: raw owned uncertainty at an outer adapter/finalization boundary produces a
  fenced existing EXECUTION_UNCERTAIN wait and released lease, with unchanged Task checkpoint,
  accepted artifacts, attempt budget and no second invocation.
- Keep live/escaped/unreadable process refusals, original stop/save/EOF gates and generic
  non-owned exceptions unchanged. No provider retry/refund is inferred.
- Run focused existing native-output, ownership/finalization and queue tests, Ruff, strict
  affected-file mypy and diff checks; independent read-only reviewer verifies final changes.

## Existing data and rollback

Audit Run6 exact immutable facts and current process/claim ownership before deployment.
Use controlled idle restart and public recovery only. Existing invocation-start without
outcome must prohibit model replay. A fresh claim may record the existing honest wait;
any further draft recovery requires a concrete supported plan and exact authorization.
Never rewrite old stop/outcome/approval/Task or manually change SQL. Rollback while idle
retains all old and newly sealed ledgers and compatible readers.
