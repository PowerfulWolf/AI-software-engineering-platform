# T043 verification and post-mortem

- Real third-round route record: FAILED/POLICY_VIOLATION, duration_ms=580616, generic dirty-worktree
  failure. Outer adapter selected nonzero-exit branch, not its timed_out branch. Original output was
  discarded, so quota, permission, inner timeout and other causes cannot be distinguished retroactively.
- Tight loop: `pytest -q tests/agents/test_codex_cli.py -k partial_changes --tb=short` failed 1/0.54s.
  The injected runner returns quota text after writing a real Git worktree. Its known cause disappeared
  directly at AgentResult (before the route ledger), locating the bug at adapter classification.
- Fix preserves safe classifications/digests while retaining dirty-worktree refusal. Unknown is explicit;
  capture keeps the tail, and timeout partial output is bounded. Existing wire and fallback policy unchanged.
- Targeted regression: 11 passed /5.84s, strict mypy src/tests passed (256 files).
- No real model invocation for this repair; no changes to the feature worktree, candidate or old journal.
- Cross-layer check: invocation -> AgentResult.error.message -> existing ModelRouteAttempt result.
  No new dependency/DDL/permission/output schema. Diagnostics are fixed categories/numbers/hashes only.
- Full provider cause for round3 remains unknown; this fixes diagnostic loss, not the unproven original
  provider failure. Recovery of dirty terminal attempts requires a separate explicit contract.
- Core production spec contains executable contract, matrix and regression points. No template mirror exists.
- Rollback by reverting the repair commit, never by deleting dirty feature work or rewriting old facts.
- User later reported the 5-hour account quota was exhausted at that time; quota is now the most
  likely cause based on operator information, not a recovered provider diagnostic.
- Final gates: full MySQL regression 777 passed /119.85s, Ruff/format, strict mypy src/tests (256 files),
  uv lock --check, uv build and git diff --check all passed. No live-model execution in this repair.
