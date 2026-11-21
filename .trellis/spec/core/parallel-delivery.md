# Parallel Requirement delivery

The console executes Manager operations in **lanes**:

- `delivery:<delivery_id>` — every operation of one Requirement. The store already
  refuses a second active operation for the same Requirement, so one Requirement
  is always serial.
- `project:<project_id>` — Project-level operations without a Requirement
  (for example creating a Requirement).
- `team` — Team-level operations.

`ProjectConsole(max_parallel_operations=N)` lets the dispatcher claim work from up
to N different lanes at once; each claimed operation runs on its own thread.
`claim_next(busy_lanes=...)` skips lanes that are already running and never
caches a "waiting behind a busy lane" queue as idle. The default is 1 (the old
single-operation behaviour); the production host uses
`CONSOLE_PARALLEL_OPERATIONS = 3`.

Shared resources:

- Git: worktree/branch commands issued by this process are serialized by
  `_GIT_PROCESS_LOCK` in `git/worktree.py` (commands are short; Agent work is not).
- Per-operation diagnostics, pause scope and owned processes are ContextVars, so
  they stay per thread.
- The work-item queue opens its own MySQL connection per operation.

Tests: `tests/web_console/test_parallel_operations.py`.
