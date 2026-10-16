# Ownership and milestones

- Backend worker: domain, manager, queue proof/accounting/authority and unit/native fixture.
- Root: public Console capability, schema generator/guards, UI and documentation.
- Public test worker: real native+MySQL Console flow through independent QA/Review.
- Independent reviewer: read-only proof/fence/authority review before deployment.

1. Record precise contract and reproduce missing capability with failing targeted test.
2. Implement exact proof/authority/accounting, publish compatible wire guards and UI.
3. Run targeted tests, review, merge approved maintenance to main and controlled deploy.
4. Public K1 same-Task proposal/PAUSE/RESUME; verify immutable history and native progress.

Follow-up audit check: the explicit HumanAction recorder initially omitted the new purpose.
Before any production execute, add exact idempotent SUPPLY_EVIDENCE event binding the immutable
operator authority and failure proof, plus ADR HUMAN_INTERVENTION/public DONE assertions. This
is a separately verified forward repair. Production proposal may remain read-only/sealed.
