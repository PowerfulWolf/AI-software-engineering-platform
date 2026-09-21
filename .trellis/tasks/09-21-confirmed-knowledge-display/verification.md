# Confirmed knowledge display verification

## Result

Confirmed questions use `已确认的知识` for section/card state and `查看已确认的知识` for
the collapsed entry. Requirement state retains `待继续` to distinguish confirmation from resume.
The expanded view echoes the saved answer/source as safe text and preserves answer line breaks.

The previous section label was chosen only from the initial Team snapshot. When a detail GET
returned a saved resolution first, the answer appeared but its heading/entry stayed pending.
Now the same current request receives the verified read fact and the open section moves to its
resolution-specific cache key. Checkpoint, gap and cached-section guards prevent late responses
from changing a newer pending question. No approval, backend contract or delivery flow changed.

## Checks

- New and renamed DOM regressions first failed against the old code (4 failures), then passed.
- `node --test tests/team_view/*.test.cjs`: 37 passed.
- `.venv/bin/pytest -q tests/web_console/test_knowledge_resolution.py`: 3 passed, only existing
  dependency deprecation warnings.
- Ruff check/format check and strict Mypy passed (431 source files).
- `uv build --offline` and `git diff --check`: passed.
- Localhost served app.js and style.css SHA-256 values matched the edited checkout. The running
  server reads static assets on request, so no restart or delivery interruption was necessary.
- No real approval/resume/model call was issued. API+DOM validation is not a claim of manual
  visual browser acceptance. The full Python suite was not rerun for this static-only follow-up.

## Handoff

Refresh the browser to load the updated assets, then expand `查看已确认的知识` to inspect the
persisted answer and source. Only genuinely pending questions retain the approval form.
