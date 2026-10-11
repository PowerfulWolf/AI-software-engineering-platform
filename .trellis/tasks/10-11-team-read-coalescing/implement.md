# Execution / validation log

Baseline: `8d494027bbbc3a97198dc410601fed11f5f9f91d`.
Branch: `task/team-read-coalescing`.
Checkout: `/Users/zhangjunshuai/workspace/code/ase-team-read-coalescing`.

Read workflow, core index, Python runtime, architecture/contracts, live-team-view, web-console,
read-memory-lifecycle, relevant docs and existing transport tests. This repository only has a
core spec package and no `.trellis/scripts/get_context.py`; use its actual core index directly.

No production/full-read probe, main checkout edit, deployment or durable fact mutation is allowed.

Contract-first result: the public same-Project three-request case failed on baseline with
`[200, 503, 503]` against required `[200, 200, 200]`. Implementation now passes this case.
The initial test render counter also counted the separate Console capability response; it was
scoped to the Team `as_of` wire field before accepting its read/wire/render-once assertion.

Final verification uses the existing Python 3.12 environment read-only, `-B`,
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=src`, and an external mypy cache. No dependency install.

1. `pytest -q tests/web_console/test_team_snapshot_coalescing.py
   tests/web_console/test_transport.py tests/team_view/test_baseline_snapshot.py
   tests/manager/test_verification_memory.py tests/web_console/test_preparation_progress.py
   -m 'not mysql'`: 97 passed, one necessary old preparation busy assertion failed (142.71s).
   The old test awaited a second same-key read before releasing its first held worker. Under the
   new contract it joins, then reaches the fixture's safety timeout. Root authorized changing
   only that probe to a different Project; no production admission workaround was added.
2. `pytest -q tests/web_console/test_team_snapshot_coalescing.py
   tests/web_console/test_preparation_progress.py::test_progress_http_remains_independent_while_team_reader_is_busy
   -m 'not mysql'`: 18 passed (4.49s), including all 17 final coalescing contracts and the repaired
   existing assertion. All 98 distinct relevant cases have passed incremental validation; the
   full first group was not repeated after the necessary test-only adaptation.
3. Scoped `ruff check`, `ruff format --check`, and strict `mypy` on `transport.py`,
   `test_team_snapshot_coalescing.py`, `test_transport.py`, `test_preparation_progress.py`: pass.
   `git diff --check`: pass. AST: 10 distinct test functions, no repeated names; parameterization
   collects 17 new cases. Two existing Starlette/httpx deprecation warnings remain unrelated.

The production coordinator is tested for weak snapshot/caller/failure-scope release, safe/unsafe
results, wire/render failures, owner and joined cancellation, timeout, repeated cancel/rejoin
callback bounds, owner-canceled two-waiter capacity, master cancellation before coroutine start,
before actual worker entry and after entry, scheduling failure, completion-before-notification and
late callback identity. Public ASGI tests cover same-key sharing, origin refusal, security headers
and other endpoint availability. Legacy direct `_team_snapshot(..., Lock())` success/failure
lifetime cases remain independently covered by `test_baseline_snapshot.py`.

Independent read-only review: `/root/recovery_read_cost/task_projection_reuse/sentinel_attack_review`
found the preparation assertion drift, which was fixed within Root's added allowlist. Its final
review reported no blocking finding across exact-key/slot/shield, immutable Response/body,
started/retired worker fences, fresh-read/identity cleanup and exception/callback retention. The
reviewer did not author code or repeat the test execution. Root also inspected the implementation.

存量数据处置：no database/Schema/journal/sidecar repair, Task reset, approval consumption or execution
change. Existing Requirement/Task/Operation facts remain valid. This patch is not deployed; future
loading waits until active execution and operations safely finish, then uses the existing controlled
service-restart path. Users refresh their original Project; existing approvals remain unchanged.

Limits: coalescing only reduces simultaneous same-Project busy errors; it does not reduce the
roughly nine-second serial read observed in production, diagnose a hang/leak or guarantee bounded
response size/process RSS. Same-key observers receive the original `as_of`. At most two additional
observers are supported, with other-key/full-capacity requests still busy. Old-generation network
buffers belong to the HTTP server, not the active-flight coordinator.

Rollback: in the isolated/integration checkout restore the scoped implementation/tests/spec to
`8d494027bbbc3a97198dc410601fed11f5f9f91d`, and load only through an idle controlled restart. This
restores immediate busy responses for concurrent same-Project callers and does not mutate any
durable data or relax approval/verdict gates. No commit/push/merge/deployment was performed.

Root integration (2026-10-11): applied the reviewed patch to main at 8d494027 while the native K1 run and all 314 Console operations were finished. Scoped integration validation: 58 passed (11.38s), Ruff check/format and strict mypy on all four affected Python files passed. No database or historical workspace changes. The deployment remains pending an idle controlled restart.
