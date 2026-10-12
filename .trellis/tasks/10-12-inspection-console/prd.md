# Inspection Console after fault maintenance

Goal: restore verified front-end reading while the user has paused all delivery.
Scope: production Console composition, read-only Operation store, HTTP admission and a visible UI banner.
Allowed paths: web_console/{host,transport,store,inspection_console}.py; team_view/app.js;
related tests; this task; dedicated core/operations inspection-console docs.

Acceptance:
- ASE_CONSOLE_MODE accepts normal/inspection only; the validated durable maintenance marker always forces inspection.
- Inspection creates no TeamHost, Manager adapter, dispatcher, knowledge worker, store directory or database schema.
- Real ProductionTeamReader GET and complete Operation/model-call/preparation history remain readable.
- Every HTTP mutation is rejected as SERVICE_MAINTENANCE before parsing/submission; unsafe administration GET is disabled.
- Console manifest and visible UI identify inspection, delivery_ready=false, and do not tell the user to reconfigure.
- Normal behavior is unchanged. New inspection shutdown cannot prove any historical execution stopped.

Validation: focused pytest inspection/store/transport, focused Node browser tests, ruff and mypy.
Rollback: controlled stop the new reader instance, revert code; retain maintenance marker and original unknown execution facts.
Existing data: read-only; no SQL, Task, Operation, approval, run or worktree modification.
