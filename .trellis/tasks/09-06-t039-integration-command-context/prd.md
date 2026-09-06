# T039 — Integration command policy in Planner context

Real Planner attempt 3 passed coverage and failed the integration test-command guard. The old
response was not retained, so its exact argv is unknown. Deterministic context regression proves
the narrower integration policy is absent: Planner receives broad project build/inspection commands.

Share the existing immutable test prefixes/forbidden options between enforcement and context;
persist a typed safe rejection diagnostic (check index and argv digest only) on failed preflight.
Keep exact test predicate behavior, project allowlist intersection and attempt budget unchanged.
No feature code, relaxed commands, arbitrary error forwarding, forged approval or retry reset.

Allowed: multi_directory command helper/models/production/service, focused tests, specs/task notes.
Verify: initial context regression 4 failed / 0.46s; positive/negative command predicate,
service restart feedback, budget guard, full MySQL regression, Ruff/Mypy/build/diff checks.
Rollback: source parent cfca1e2; all historical checkpoints/executors retained.
