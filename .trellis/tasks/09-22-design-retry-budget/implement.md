# Implementation and checks

1. Define the executable budget contract and failing fake-provider/UI/config tests.
2. Implement shared typed policy, durable classified accounting and Host/Reader composition.
3. Fix recovery action priority, budget display and Settings fields; regenerate schemas.
4. Run only incremental tests plus lint/type checks; inspect changed paths (user: no full tests).
5. Record existing Requirement recovery steps and rollback; commit without fabricating QA/Review.

Context: core/python-runtime.md; core/production-team-host.md; core/multi-directory-delivery.md;
core/web-console.md; core/design-retry-budget.md; docs/operator-feedback-loop.md.
