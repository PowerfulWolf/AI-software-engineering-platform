# Implementation checklist

- [x] Preserve BLOCKED Task and dirty worktree; no manual candidate adoption.
- [x] Identify the prompt compilation boundary as the deterministic test seam.
- [x] Add and run a failing exact Coder completion-budget test.
- [x] Rank and test competing hypotheses.
- [x] Implement the minimal prompt contract.
- [x] Assert recovery passes the exact total/reserve contract to every Codex role.
- [x] Update production/Codex code-spec and root-cause record.
- [x] Run focused, integration, full, lint, type, lock, build, and diff gates.
- [x] Prepare an auditable commit for local main sync without push.
