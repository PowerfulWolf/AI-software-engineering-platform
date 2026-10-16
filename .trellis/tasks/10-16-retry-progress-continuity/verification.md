# Verification — 2026-10-16

## RED and GREEN

The actual service PAUSE/replay → independent RESUME → StoredCoderExecutionInputResolver →
RetryingOrchestrator request regression first failed: continuation_checkpoint_id was None,
expected art_progress_001. Command was the main checkout's existing venv Python with
PYTHONPATH=src, pytest tests/manager/test_stopped_failure_retry.py -k retains_checkpoint:
RED1 failed/31 deselected in5.14s; same test GREEN1 passed/31 deselected in5.49s.

Only new binding construction changes. The test verifies accepted checkpoint/paths, source,
permissions, budget and completed01→selected02. An unaccepted raw successor cannot advance
completed steps. Queue consumption/continue callbacks are idempotent test implementations;
this focused bridge test does not claim to exercise a new MySQL transaction implementation.

Five related suites: **56 passed /167.49s**:
test_stopped_failure_retry.py, test_baseline_history_inputs.py, test_execution_baseline.py,
test_paused_baseline_service.py and test_capacity_baseline_preserved_inputs.py. They use
temporary SQLite/Git/files and offline local subprocesses, no production data/provider.

Root separately ran existing public isolated-MySQL/native recovery tests serially:
`PYTHONPATH=src <main-venv>/python -m pytest -q tests/manager/test_stopped_failure_public.py`:
**2 passed /45.32s**. Test-only DSN identity is checked before fixture reset; no production DB
is used. This covers the existing public PAUSE/RESUME→same-Task independent QA/Review contract;
new accepted-progress inheritance is asserted by the targeted real service-to-runner bridge.

Ruff check/format, targeted source/test mypy and git diff --check pass. Independent read-only
review found no blocking issue; its separate verification passed10 items covering the real
continuation bridge, both source-changing modes, accumulated retirement and new successors.
The review's first fixture setup hit sandbox OS boot-identity denial; the authorized offline
OS-probe rerun passed unchanged. No full-repository test/typecheck claim.

## 存量数据处置

No Schema/SQL migration or historical rewrite is required. The two old K1 bindings retain
their original retirement meaning. Native attempt4 legally re-established completed01/02
in new progress art_coder_05714ae8093596356e007b54dc42490b. Read-only SQL confirms its
actual StateEvent acceptance, and the new attempt5 request selects03/04 while retaining01/02.
All195 original immutable-file SHAs remain unchanged. Exact references are in the sibling
stopped-failure task's production-recovery.md; no root-maintained K1 source patch was used.

The running service already has the previous safe-diagnostic fix. This additional producer
fix should load only at a real natural idle/wait boundary through controlled restart; do not
interrupt an ongoing healthy Coder or retire its latest checkpoint just to deploy maintenance.
After new facts publish, preserve compatible readers and use forward repair rather than
deleting bindings, accepted artifacts or audits. Final delivery still requires candidate
and independent native QA/Review; restored progress is not K1 completion.
