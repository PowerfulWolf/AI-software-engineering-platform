# Implementation and verification

Status: implementation and incremental checks complete; independent review pending.

Owned files: recovery/native.py; recovery/baseline_source.py; necessary recovery/models.py,
entry.py, current.py and scope.py consumers; related recovery schemas and tests;
.trellis/spec/core/delivery-recovery.md; this task directory.

Other workers own native Python tooling and terminal workspace containment. Preserve their edits.
No production mutations or commits are authorized for this worker.

Trellis helper scripts are absent in this checkout. Task records and spec discovery use the
existing core/guides indexes without replacing a shared current-task pointer.

Implemented:

- Complete verified baseline chain and exact Team/Project/Repository/root contract; actual
  registry Project ID is passed from native discovery/inspection.
- Per-event revision, reserved-attempt and completion-time source epochs, plus original sealed
  invocation and required full Context verification.
- Paired optional source fields preserve legacy omission/digest and bind effective capture base;
  effective-base consumers include capture, scope, requested metadata and target ancestry.
- Root independently added matching JSON Schema paired-field constraints and workspace proof
  integration after the shared files were explicitly released.
- Read-only native SQL composition regression and scope committed-edit regression.

Verification:

```text
pytest -q tests/recovery/test_terminal_baseline.py tests/recovery/test_terminal_baseline_context.py
  tests/recovery/test_terminal_baseline_sql.py tests/recovery/test_baseline_wire.py
  tests/recovery/test_models.py tests/recovery/test_scope.py tests/recovery/test_authorization.py
  tests/recovery/test_scope_progress_history.py tests/recovery/test_protected_recovery.py --tb=short
93 passed in 14.23s

Strict mypy: 11 owned source/test files, no issues.
Ruff check/format: owned Python files passed.
git diff --check: passed.
```

A broader incremental run with test_native.py/test_current.py returned 100 passed / 5 failures.
All 5 were reproduced unchanged by replacing the reader seam with the actual HEAD original
native.py source loaded in memory (no checkout mutation): three progress fixtures stop before
source inspection with CoderSliceRejected/Task dispatch mismatch, invalid-output expects terminal
BLOCKED while current transient retry remains DELIVERING, and current recovery fixture omits the
Task semantic branch mapping. These are pre-existing fixture drift; the source gate was not
weakened to accommodate them. No full suite or real model call was run.

Existing data: no writes, approval, restart, Task reset, cleanup, commit or production operation.
Source compatibility alone does not authorize recovery; root owns the independent stopped-process
and complete ignored-workspace proof, production validation and user approval path.

Released shared ownership: recovery/models.py, entry.py, current.py, scope.py and
schemas/delivery-recovery.schema.json. Root may integrate workspace_snapshot without conflict.

Independent follow-up review:

- Terminal workspace helper preserves successful exact accepted-progress recovery and requires
  the original stopped-progress proof. A FAILED selected Run never bypasses the complete terminal
  stop/inventory audit merely because an earlier progress artifact exists.
- Raw SQL Task/event/claim/work-item indexes are checked against typed facts; historical claim row
  and CLAIMED event are included in the audit digest. Fresh before/after reads reject drift.
- Entry/current/plan integration binds the exact fresh snapshot, omits absent legacy fields, and
  uses read-only SQL plus the existing Task process lock without nested global authority locking.
- Independently reran test_workspace_snapshot.py, test_workspace_plan.py and test_baseline_wire.py:
  77 passed in 37.57s. No additional production implementation finding remained in this review.

Requested source/base combination regression:

```text
pytest -q tests/recovery/test_terminal_baseline_context.py::test_preserved_draft_terminal_context_keeps_real_source_and_capture_base_distinct --tb=short
1 passed in 7.33s
ruff check/format: passed.
MYPYPATH=src mypy --strict tests/recovery/test_terminal_baseline_context.py: passed.
```

This case uses a real isolated Git PRESERVE_DRAFT service binding with distinct execution source
and execution base. It verifies the sealed original invocation/full Context and source epoch;
rejects treating the base as the terminal event source; and verifies scope/capture retain both
committed candidate and dirty work while excluding the main README prerequisite update. The frozen
original Task is unchanged. Only temporary fixture directories are mutated; no production facts,
approvals, restart, cleanup, commits or model execution are performed.
