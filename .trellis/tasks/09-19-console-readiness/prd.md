# Console readiness and apply feedback

## Goal / scope
Keep Settings and Status synchronized with the restarted Console and show apply success as a
bounded acknowledgement. Current live read-only endpoints report READY and restart_required=false.
No API schema, process hot reload, delivery policy or durable business facts change.

## Acceptance
- Ready metadata clears the setup warning, including when the Team projection is unavailable.
- A confirmed apply refreshes readiness and invalidates old dependency status.
- Success feedback expires or can be acknowledged; visiting Settings never resurrects historical success.
- Settings flags refresh after manual restart without overwriting unsaved form values.
- Status only requests restart when restart_required=true, and refreshes after readiness changes.
- A real setup/runtime failure remains visible; a failed request never implies readiness.

## Allowed paths
src/ai_software_engineer/team_view/app.js, tests/team_view/**,
.trellis/spec/core/web-console.md, .trellis/tasks/09-19-console-readiness/**.

## Verification / rollback
Node syntax and DOM contract tests, focused Python transport tests, Ruff/Mypy and diff checks.
Separate QA and read-only Review after implementation per AGENTS.md. Baseline b8983b8; revert this
frontend-only patch to roll back. No SQL/journal/approval/queue migration or manual rewrite needed.
