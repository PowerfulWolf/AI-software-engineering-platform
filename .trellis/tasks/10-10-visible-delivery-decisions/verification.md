# Verification

## Incremental automated checks

- Red: `node --test --test-name-pattern='current exact approvals|detached exact approval|pause shows its saved source' tests/team_view/engineering-wait.test.cjs`
  → 3 failed before implementation for the intended defects; 3 passed afterward.
- Red: `node --test --test-name-pattern='team, multi-directory requests' tests/team_view/ui.test.cjs`
  → 1 failed before implementation for native disclosure visibility; 1 passed afterward.
- Red after independent review: `node --test --test-name-pattern='current exact approval remains|every exact approval kind' tests/team_view/engineering-wait.test.cjs`
  → 2 failed for nonblocked ancestor folding and prerequisite-repair consumption; 2 passed afterward.
- `node --test tests/team_view/ui.test.cjs tests/team_view/engineering-wait.test.cjs`
  → **58 passed**, 0 failed, approximately 0.21 seconds.
- `node --check src/ai_software_engineer/team_view/app.js` → passed.
- `git diff --check` → passed.

Only the two affected Node files were run. No full repository tests or production operations.
The project has no frontend package lint/typecheck entry; syntax plus executable DOM contracts
are the relevant existing gates. The referenced `.trellis/scripts/get_context.py` is absent, so
package/spec discovery used the repository's root/core indexes and relevant actual guidelines.

## Manual and independent verification

Browser authentication is unavailable. Native disclosure semantics and real incremental
reconciliation are covered by the Node DOM harness, but live browser layout, keyboard focus and
visual acceptance are **not verified** in this session. Read-only independent code review pending.
Independent read-only reviewer found the nonblocked ancestor fold and prerequisite-repair
consumption omission; both were reproduced red, corrected and independently replayed green.
Final reviewer result: no additional implementation blocker; actual browser visual acceptance
remains outside this session's verified evidence.

## 存量数据处置与回滚

Read-side only: no SQL, journal, immutable approval or old result migration. Load compatible repaired
assets while service idle if needed, refresh the original K1 detail, then use its current exact
approval/pause continuation. Refresh does not itself approve or restart delivery. Revert UI changes
and refresh to roll back while preserving all facts/history/progress and native QA/Review gates.
