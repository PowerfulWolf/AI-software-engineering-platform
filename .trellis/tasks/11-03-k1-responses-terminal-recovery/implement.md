# Implementation and release gate

The completed synchronous Responses `write_file/PARENT_NOT_FOUND` refusal is
now a narrow v2 terminal workspace snapshot. The original failed Run remains
`FAILED/POLICY_VIOLATION`, with its authentic route and invocation outcome;
the reader does not fabricate a native `capture-stop`. The v2 snapshot binds
the final route SHA and completion time only after the existing Task lock,
terminal SQL facts, no interruption receipt, unchanged complete inventory and
empty Git capture have passed two reads. Existing native v1 snapshot bytes and
stop requirements remain unchanged. A fresh same-Requirement Plan with a full
inherited patch requires `coder_reapply` before independent approval.

The public isolated MySQL fixture ran original Responses Coder refusal through
Continue, exact Plan and approval, new Task, independent offline Coder/QA/Review
and DONE: `tests/recovery/test_responses_terminal_public.py` passed (1 test,
248 seconds). This verifies ASE's public composition, not production model
availability or K1 acceptance. The test database's 13 fact tables were clean
afterward. Negative tests use freshly sealed routes and invocation outcomes to
check a different route or error, plus a changed inventory.

Additional checks on this tree: 108 non-MySQL focused recovery/Responses tests
passed (2 MySQL tests deselected); 85 workspace snapshot/Plan tests passed;
108 JSON Schema and route-transition contract tests passed; Ruff, `mypy src`
(420 source files), `git diff --check` and Schema regeneration parity passed.

## Stock data and deployment

No database or historical artifact migration is needed. Before publication,
the original K1 failed Task remains `BLOCKED`, its WorkItem `CLOSED`, and its
single Responses invocation has the exact sealed tool refusal. Production
audit of the untouched scene previously produced v2 snapshot SHA
`e3b31e32d4a436229285f597466116a2c657183fe356c4fa84ab95666a4fe968`.
Recheck Task/queue/route/outcome, current full inventory, empty Git capture,
inherited 72,535-byte patch, clean registered `main` and current model route
after a controlled service restart. If any source or target fact has changed,
do not approve a stale Plan or change the old Task directly. Use public
Continue once, inspect the generated exact Plan, independently approve it,
and follow the new Responses Task through QA/Review. Rollback restores the
previous service binary and preserves every old and new immutable fact; a v2
Plan must not be executed by a reader that does not understand its completion
proof.
