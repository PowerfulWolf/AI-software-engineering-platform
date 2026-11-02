# Completed Responses refusal recovery

## Goal

Restore the original K1 Requirement after its Responses Coder returned a sealed
`write_file/PARENT_NOT_FOUND` policy failure. The old Task, Run, claim, failure and
worktree remain immutable. A new exact same-Requirement recovery plan must use
the released nested-write capability and a fresh Responses Coder, then independent
QA and Review.

## Scope and acceptance

- Distinguish a completed synchronous Responses tool refusal from an unknown
  start-only invocation and a native process failure. Never fabricate a native
  `capture-stop` or infer a budget refund.
- Audit the exact route, invocation outcome, terminal Task/queue facts, complete
  unchanged worktree inventory, existing lock and current source twice before
  binding a recovery snapshot. Any missing, changed or ambiguous fact rejects.
- Continue through the public exact Plan and approval path. K1 ProductSpec,
  Design, Plan, prior candidate and previous Task remain unchanged.
- A later start-only or ambiguously completed Run cannot borrow this exact
  historical result; new refusals require their own sealed route and outcome.

## Allowed paths and validation

Recovery source/snapshot models, exact Schema generator/output, relevant tests,
this task record and `.trellis/spec/core/delivery-recovery.md`. Validate focused
red/green tests, public same-Requirement fixture, Ruff, Mypy and Schema checks.
Rollback disables the new proposal path while preserving all historical facts;
no existing record is rewritten.
