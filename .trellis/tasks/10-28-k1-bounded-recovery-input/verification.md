# K1 pre-Coder capacity wait repair verification

## Scope and live fact

The existing K1 recovery Task `task_recovery_b06bffe70284000da954ea92ef7196a2`
is `IMPLEMENTING`; its WorkItem is waiting on `CONTEXT_CAPACITY`. The public
`INSPECT_DELIVERY_WAIT` operation previously reported `CHECKPOINT_DRIFT` and
showed an unrelated verifier-capability action. A read-only replay of the exact
recovery-input inspection found one sealed, integrity-valid `ORCHESTRATOR`
Context for this Task, attempt 1 and source `58fed894a0e98854974b47a2ed4aa0d9115d469b`.
There was no same-Task Coder Context, invocation start/outcome, model route or
accepted Coder artifact; the original claim was unique and the seed worktree
was clean. The negative scan had treated the orchestration preparation Context
as a Coder Context. No production record was changed during diagnosis.

## Repair and validation

The recovery scan now admits only an integrity-checked `ORCHESTRATOR` Context
for the exact Task attempt and base revision. Other roles, mismatched attempts
or sources, invocation records and model routes still fail closed. The
investigation's `next_action` displays verifier capability details only when
`PREREQUISITES_UNVERIFIED` is an actual missing proof. The prerequisite receipt
digest remains in the investigation for audit.

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/manager/test_recovery_input_schedule.py tests/manager/test_delivery_wait.py`: **75 passed** outside the Codex sandbox, whose macOS process-ownership restriction prevents the full owned-process fixture from running inside it.
- `ruff check` and `ruff format --check` for the four changed Python files: passed.
- `mypy` for both changed production modules: passed.
- `git diff --check`: passed.
- Independent read-only review: no remaining safety or contract finding.
- Read-only inspection of current K1 facts with the repaired code: the exact recovery-input check passed and returned all three complete source references.

## Existing data and release gate

This repair needs no SQL migration or edit to the Requirement journal, Task,
WorkItem, Context, approved recovery Plan, patch sources or old UNKNOWN run.
After a controlled service restart, submit a fresh public
`INSPECT_DELIVERY_WAIT`. Only if it returns no missing proof and offers
`SCHEDULE_RECOVERY_INPUT` may an ENGINEERING-authorized public resolution
consume the original wait. This resumes the same Requirement and Task; it does
not imply a candidate, QA verdict or completed delivery.

Rollback before a schedule is consumed: pause new operations, use the controlled
service stop/restart path to return to the previous platform commit, and retain
all existing records. After a schedule is consumed, retain the schedule reader
and fix forward so its immutable decision remains auditable.
