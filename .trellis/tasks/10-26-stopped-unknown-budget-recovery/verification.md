# Verification and release evidence

## Regression feedback
The initial public native/MySQL regression reproduced the exact bug: a completed zero-exit
Coder with output present and no durable outcome consumed its frozen work allowance; public
HANDLE returned PLATFORM_ATTENTION and could not expose a lawful recovery plan. A separate
ordinary stopped-failed settlement could not be reused because no failed outcome existed.

The fix runs the narrow UNKNOWN settlement before generic interruption receipt reconciliation.
The generic reconciliation and ordinary failed-route recovery remain unchanged.

## Checks completed
- Shared offline wait/recovery/authorization/legacy/schema suite: 179 passed, 8 MySQL deselected.
  Command: PYTHONPATH=src <production>/.venv/bin/python -m pytest -q -m 'not mysql'
  tests/manager/test_delivery_wait.py test_stopped_budget_settlement.py test_stopped_unknown_budget.py
  test_stopped_unknown_budget_deletion.py test_stopped_execution_rescue.py (with full tests/manager/
  paths), tests/contracts/test_stopped_unknown_budget_schema.py, tests/recovery/test_stopped_unknown_source.py,
  test_context_capacity_source.py, test_context_capacity_entry.py, test_authorization.py, test_native.py,
  test_current.py (with full tests/recovery/ paths), and tests/contracts/test_stopped_execution_schema.py,
  test_repair_schema_generation.py.
- New Source/Schema/audit/physical-deletion regression group: 20 passed.
- Exact owned-stop embedding inventory and new source schema: 14 passed. The embedding inventory
  now explicitly includes the new UNKNOWN settlement and the two already published rejected
  candidate schemas; unknown/missing/replaced inventories still refuse all writes.
- Original shared MySQL settlement/CAS/rollback/publication fences: 10 passed.
- Public UNKNOWN recovery positive case fully passed: actual native start/owned empty stop,
  preserved output-present/absent outcome, exhausted budget HANDLE, exact replay, updated main,
  full conflicting coder_reapply patch, exact approval and successor Coder/independent QA/Review
  to the same Requirement DONE and one shared candidate SHA. All live provider clients were
  blocked by the test fixture. This case took about 5m40s due repeated complete source/Git
  verification. Its command was interrupted after the positive dot while the next case began;
  the command exit was 2, not a claimed all-green run.
- Final public late raw artifact cases, including injection immediately before real SQL settlement:
  PYTHONPATH=src <production>/.venv/bin/python -m pytest -q --tb=short
  tests/manager/test_stopped_unknown_budget_public.py -k 'not deliver': 2 passed, 1 deselected,
  11.42s, exit0. Both retain original Task/events/queue/claims/draft and create no new model call.
- Ruff check + format: all 23 changed Python files passed before final public test-only addition;
  test owner separately checked its final file. Strict mypy: all 23 changed Python files passed.
- Independent read-only reviewer: no blocking findings; independently reran 17 Source/Schema cases.
  Reviewer did not access production, localhost, credentials or MySQL. git diff --check passed.

## Stored K1 facts before release
Existing parent delivery_multi_bb78e2316afca47d005384542f685174535b69db remains active.
Task task_recovery_3a4325237347c8caf434d94379cce745 stays IMPLEMENTING at revision11,
work_attempt10-of10, attempt11; WorkItem work_ae560e72201fe9c6c5362575a2d5b2ee4b8347eca7dbd6cb4ad87af31df56f86
is WAITING_DEPENDENCY/EXECUTION_UNCERTAIN, no new attempt12. Original
run_dba89186b8a54fb58a22eaabe98c1957 stopSHA35ccec8ebe433da8968b55ff9868f15de0500b6c40d1483682160c972e1a6ee9
remains completed/zero/output-present with owned_session_empty proof and no outcome/route/artifact.
Public read on 2026-10-26 confirms the original revision/disposition; production main was ec67fb4.
No production SQL repair or Requirement replacement has occurred.

## Existing data disposition and rollback
After controlled release, use fresh public HANDLE for the exact original wait, then CONTINUE
to prepare the same-Requirement RecoveryPlan against latest main, and separately approve its
exact digest under the user's engineering delegation. Preserve original frozen product/counters/
UNKNOWN history and full retained draft. All operations and engineering approvals must remain
auditable. Actual K1 completion still requires real candidate-bound QA/Review and the registered
live verification capabilities; isolated tests never count as K1 E2E evidence.

Rollback point before new record consumption: ec67fb4545499cb08402579342cdbfbb03942a54.
After consumption keep compatible UNKNOWN settlement/recovery readers and controlled pause;
never delete sealed records, rewrite old Task budgets/outcomes or reset dirty worktrees.

## Follow-up: independent investigation publication

The first real public HANDLE succeeded but exposed a producer omission: the
`delivery-waits` handling referenced an investigation only embedded in the
`delivery-preflight` settlement. The complete Team reader correctly refused it
with 503/RECORD_NOT_FOUND. Four red tests reproduced the exact
`engineering_history.py:485` path for initial/replayed v1/v2 stop facts.

Both initial publication and exact replay now seal the unchanged independent
investigation before its handling. No read fallback, schema change, SQL repair,
refund or history rewrite is introduced. The existing immutable store refuses
conflicting proof bytes. The first recovery/read regression run passed85 tests;
final validation and public stock recovery are recorded below after execution.

Stock procedure: controlled release while execution is idle, read current parent
journal checkpoint, submit a new public HANDLE operation with the original exact
five fields and a new Console idempotency key. It revalidates settlement/current
stop/Git facts before restoring the missing proof. Then verify public summary and
continue the same Requirement. Reusing the earlier operation key does not repair
the dependency because it returns the cached result.

Rollback: preserve the newly published immutable dependency and all settlement
facts. It is readable by the preceding release; reverting only this producer
change would reintroduce the omission for future settlements.

Final follow-up checks before release:
- Complete UNKNOWN / read-history / snapshot / recovery-source regression:85 passed.
- UNKNOWN group including new conflicting-proof negative:14 passed.
- Ruff check and formatting, strict Mypy(two Python files), git diff --check passed.
- Independent read-only review found no blocking correctness/permission issue;
  import ordering was corrected and the suggested conflicting-proof test added.
