# Continue an exactly stopped unknown Coder failure

Goal: safely resume the existing K1 recovery Task after a real FAILED outcome with no output,
while retaining all prior execution facts, legal draft and frozen budget. Implement a general
platform capability for this precise state, without a K1-specific override.

Allowed maintenance paths: src/ai_software_engineer/{domain,manager,work_queue,web_console,team_view,multi_directory}/**,
schemas/**, scripts/sync-legacy-rescue-schemas.py, tests/**, docs/**, .trellis/spec/** and this task.
Production Coder worktrees are read-only to maintenance. No SQL writes outside public services.

Acceptance: narrow typed proof; explicit engineering approval; same-base full legal input; one
ordinary-work reservation; PAUSE then latest-bound RESUME; fresh claimed execution; independent
QA/Review; failure/UNKNOWN/approvals remain unchanged; schema and UI capability gates; negatives
for mutation/live/foreign/late output/wrong authority/budget. Run targeted lint/typecheck, contract,
real native isolated-MySQL public test and browser controls. All tests keep production DB untouched.

Rollback: fab2cb6 before new record publication; thereafter retain compatible readers and forward
fix under controlled pause. Production recovery only after tests and independent review.
