# Verification (2026-10-16)

Baseline: fab2cb6. Tests load this isolated worktree using PYTHONPATH=src and the main
checkout's existing virtualenv. No real provider/model calls. MySQL fixtures validate
ASE_TEST_MYSQL_DSN is dedicated test scope and run serially, never against production.

- RED backend: missing StoppedFailureProof import before implementation.
- RED wire: new guard test accepted stopped_failure_sha256=null (1 failed) before generator fix.
- RED UI: six new controls/old matcher tests failed before implementation.
- Public real-native/MySQL: `pytest -q tests/manager/test_stopped_failure_public.py`:
  **2 passed / 80.80s**, including same-Task public PAUSE/RESUME, fresh claims and independent
  QA/Review to DONE, ordinary budget, stale input/authority/scene refusals and preserved history.
- Schema: new unknown failure + old AUTH + repair regeneration:
  **45 passed / 29.75s**, including independently fresh generation, embedded guards and repeatability.
- Backend worker: 60 old AUTH/no-outcome/baseline tests passed. All 31 new cases verified over
  batches; first batch had 29 passed and a test expectation defect, corrected to refuse another
  purpose before Git preview; final targeted recheck **7 passed / 29.42s** included that case,
  live-stop expected exception, late raw artifact/receipt/route and absent-field canonical wire.
- Targeted node UI: **137 passed**, including 8 new cases; no full-suite claim.
- New typed history and real native-phase projection: **2 passed / 21.77s** outside sandbox.
  Initial sandbox owned process observation could not read boot identity; it was an environment
  refusal, then the authorized real process test passed.
- Ruff check/format/diff passed on changed files. Targeted mypy passed on backend/fixture/new
  tests (10 files), generator/schema tests (2 files), UI history/transport (4 files).
- Independent read-only review: no blocking backend, schema or UI finding. Confirmed final SQL
  callback reopens raw output/route/receipt/outcome/claim/real stop, ordinary-work only accounting,
  authority and cross-proof boundaries, absent-field canonical compatibility and capability10.

Production pre-deployment: all 120 previously tracked immutable history files remain unchanged;
195 immutable records now tracked in /tmp/ase-k1-before-stopped-failure-history.json. Current
K1 recovery Task remains IMPLEMENTING revision5 attempt2, WAITING_DEPENDENCY NONTRANSIENT_INFRA;
original failed outcome c09e52fc… and approved source 774e0a6… preserved. No direct SQL repair.

Independent reviewer additionally ran the new backend, new Schema and existing completed-output
fixture suites together: **143 passed / 146.90s**, without MySQL/provider/production access.

Real Chrome targeted new controls: **2 passed / 3.149s**, first platform check → sealed plan →
explicit consent → exact PAUSE, same-plan DOM/focus retained during polling, 390/1440px layouts,
changed-plan consent reset, detached controls and contract9 produce no POST. Full unrelated Node
suite did not terminate due to existing timers and is not claimed as passed; only targeted137.
