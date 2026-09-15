# Implementation checklist

- [x] Add tests for distinct Requirement baseline worktrees and source-checkout advancement.
- [x] Route Product/Designer/Planner clients to retained baseline roots.
- [x] Replay sealed preparation and source revision into native child dispatch and recovery.
- [x] Replace mutable checkout reconciliation with retained-baseline verification.
- [x] Add Codex CLI support for additional baseline roots.
- [x] Update executable specs, Git documentation and README.
- [x] Run focused tests, Ruff and Mypy.
- [x] Run the complete non-MySQL regression and the affected MySQL integration suites.
- [ ] Re-run the complete socket/MySQL suite outside the restricted sandbox.

## Validation completed

- Ruff format/check: passed for all changed Python files.
- Mypy: passed for all changed source files.
- Focused unit/manager/web tests: 45 passed.
- MySQL source-baseline/recovery/joint-delivery tests: 9 passed.
- Complete non-MySQL regression: 1,161 passed. Seven unchanged localhost-server tests could not
  bind a socket in the restricted sandbox.
- A complete MySQL run was attempted; the sandbox later rejected localhost:3307. Its only real
  assertion failure was an outdated contract fixture, which was corrected and re-verified.
