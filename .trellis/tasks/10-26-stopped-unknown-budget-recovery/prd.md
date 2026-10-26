# Recover an exhausted Task with an actually stopped UNKNOWN Coder

## Goal
Continue the existing K1 Requirement using latest main and the complete retained draft after
a genuine ordinary-budget exhaustion. Old invocation outcome remains UNKNOWN; no Requirement
replacement, budget rewrite, verdict fabrication or direct production SQL repair.

## Requirements and scope
Add a separate typed stopped-unknown settlement on public HANDLE_DELIVERY_WAIT. It may end
the exhausted original IMPLEMENTING Task with an audited BLOCKED event and atomically close
its unique waiting WorkItem. A new dedicated recovery source feeds the existing exact
coder_recovery approval and successor Task path within the same Requirement. Full draft and
inherited reapply inputs remain mandatory. Frozen ProductSpec, source history and accounting
remain unchanged; only a newly approved plan grants successor execution.

Allowed production paths: domain/stopped_unknown_budget.py, manager/stopped_unknown_budget.py,
existing stopped_budget_settlement/delivery_wait/production_host wiring, work_queue/execution_store.py,
recovery/models.py, stopped_unknown.py, native.py, current.py, entry.py, baseline_source.py and
workspace_snapshot.py if required, multi_directory/purge_state.py and purge.py. Corresponding
Schema generation scripts/schemas, docs, Trellis task/specs and focused tests are in scope.

## Acceptance
- v1 failed-no-output and v2 completed-zero-exit-output-present stop shapes retain strict existing
  proof semantics; absence of outcome/route/artifact/receipt and present owned-session-empty proof
  must be independently verified. Output presence never establishes success.
- Task lock and MySQL owner/Task/claims fences reject active claims, late publication, drift or
  unbounded source. Atomic Task/event/queue mutation and crash replay consume no new work allowance.
- Source reader validates pre-terminal proof against original snapshot, and terminal state against
  the exact reducer event. Normal terminal failed-route recovery remains strict.
- Existing exact RecoveryPlan approval creates a fresh authorized successor with complete reapply
  input and distinct Run/Context/claim. Independent QA/Reviewer use the same candidate SHA.
- Historical wire/digests remain unchanged when optional fields are absent. Physical Requirement
  deletion includes new typed records. Public GET remains read-only.
- Related regression, Ruff, strict mypy and isolated MySQL tests pass; independent review is clean.

## Existing data and rollback
K1 task_recovery_3a4325237347c8caf434d94379cce745 is IMPLEMENTING, attempt 11, work_attempt 10/10,
with run_dba89186b8a54fb58a22eaabe98c1957 genuinely stopped and no final outcome. Failed proposal
operation_09e67c93a0126508236392ecfdd875b1 stays FAILED. No attempt-12 reservation exists.
After deployment, fresh public INSPECT/HANDLE settles only that exact wait, then proposes and
approves a new recovery plan against current main. No production SQL helper or requirement reset.
Before new record consumption revert source commit if needed; after consumption retain compatible
readers and controlled pause. Never remove new facts or draft bytes for an old runtime to accept.
