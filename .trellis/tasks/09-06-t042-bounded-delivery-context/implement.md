# T042 implementation / verification

- Scope: platform bug repair, not autonomous feature delivery. No model invocation this task.
- Repro: archived round-2 required project.profile passed to actual FileRunContextBuilder with
  temporary root and fixture Task. 1.03s, ContextBudgetExceeded; 69,062 chars / 17,266 estimated tokens.
- Regression first: runtime composition 32,000 case failed while 12,000 rejection passed, proving
  the cap was not propagated. Added marker-heavy real discovery regression (1,500 source files).
- Profile retains all native rules/build systems and full-profile digest; original immutable model
  unchanged. Only language inventory becomes count/three sorted examples; kind distinguishes projection.
- Runtime field/schema and FileRunContextBuilder budget seam are explicit; low-level default unchanged.
- Archived required sources plus exact Task/dispatch replay read-only: profile 18,240 chars,
  base contexts 18,868–19,107 tokens. No actual Coder/QA/Reviewer report was available or fabricated.
- Existing real Git/MySQL offline host delivery verifies selected budget in all four persisted contexts.
- Cross-layer check: production → RuntimeConfig → RunContextBuilder → FileContextBuilder → manifest;
  sources remain required, no policy/worktree/state guard change, no new dependency/DDL/CLI command.
- Additional finding: failure wrapper preserves an old Task snapshot after runtime exceptions.
  Actual MySQL PLANNING/revision1 differed from child failure snapshot NEW/revision0. Recorded in the
  external observation log. Added budget-specific existing BlockedResult routing, tested red in all
  four roles (4 failed /1.33s), then green. Production MySQL fixture verifies snapshot BLOCKED/revision2
  and delivering attempt1. Other unexpected-error reconciliation remains separate follow-up.
  Terminal round2 remains BLOCKED and cannot be silently restarted; no manual history editing.
- Follow-up: whole prompt/provider token accounting and input admission before costly stages. Local
  character estimates deliberately do not promise future artifacts/tool schemas will always fit.
- No matching template tree or shared-guides directory exists in this repository; core spec is authority.
- Rollback: revert this isolated repair; do not modify prior requests, approvals, manifests or attempts.
- Final gates: full MySQL suite 770 passed /113.74s; Ruff check and format (464 files), strict mypy
  src/tests (256 files), uv lock --check, uv build and git diff --check passed. No model quota used.
