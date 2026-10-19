# Public recovery after allocation and before seed

## Goal
Lock down the existing public recovery contract for an interrupted preparation that has
an approved Plan, sealed Task, committed allocation and clean Coder worktree, but no seed
or invocation. Resume the same Requirement using existing approval and resources.

## Scope and ownership
The assigned worker owns one focused test module under tests/recovery and this task's
implementation/verification notes. Root owns this PRD/design, spec updates and integration.
Production source, Schemas, persistent production facts and all real K1 workspaces are
outside this test-only scope. Other maintainers share the checkout; preserve their work.

## Acceptance
- Interrupt after the real Coder worktree exists and before seed publication.
- Rebuild trusted service/Host and use public Continue without a new Plan approval.
- Preserve exact authorization, sealed Task, dispatch, assignments/leases and worktree.
- Create exactly one seed and one first invocation, with the original complete reapply
  patch in the required Coder context; no duplicate Task or budget reset.
- Dirty unseeded worktree or changed current facts fail closed without new invocation.
- Keep old failure facts and distinguish successful operation processing from delivery.

## Validation and rollback
Reuse existing native recovery fixtures and actual stores/Git. Use an independently
identified isolated test database only when necessary, serially under existing test safety
gates. Never connect to production or print DSN/secrets. Run the new tests, necessary nearby
increments, Ruff/format and strict Mypy for changed Python. Independent read-only review
must accept the tests before commit. If a source defect appears, report the exact red
case to root before changing production code. Rollback removes only the test/docs.
