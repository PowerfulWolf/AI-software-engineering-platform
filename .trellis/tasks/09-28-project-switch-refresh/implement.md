# Implementation Plan

- [x] Commit/push prior work and confirm clean baseline 321f15e.
- [x] Read current UI/polling, modal guards and relevant Trellis read-side/Console specs.
- [x] Converge PRD/design; user has explicitly requested implementation. No unresolved scope choice.
- [x] Add a deterministic held-poll → real picker click → completion regression; observe red.
- [x] Implement latest-intent single-flight draining and stale response/command guards.
- [x] Cover multiple clicks, failure/retry, manual refresh, wrong response and dirty composer.
- [x] Run `node --test tests/team_view/*.test.cjs`, focused Python Team/Console tests,
      Ruff, typecheck, diff check, and real localhost switching before/after refresh.
- [x] Capture root cause/contract and verification evidence; update task/index.
- [x] During review, reproduce/fix the Knowledge async publication boundary with a red→green test.
- [x] Subsequent user-authorized release committed/pushed the fix as `4d1e799`, tag `v0.1.2`;
      stable task path retained per FORMAT.md, lifecycle index updated.

Inline only. No repository Trellis scripts or template mirror exist, so use the established
`.trellis/tasks/FORMAT.md` files directly. Business code/data and runtime secrets are out of scope.

See `verification.md` for commands, actual UI results and limitations. These are inline maintenance
checks, not an independent ASE QA/Reviewer verdict. No production delivery fact was changed.
