# Incremental verification

All Python checks used the shared venv executable with `PYTHONPATH=src` in the
isolated checkout. Mypy additionally used `MYPYPATH=src` and the external cache
`/tmp/ase-completed-output-rescue-mypy`; the shared venv editable install points
at main, so these path overrides are required. No full test suite was run.

## Implementer results

| Check | Result |
| --- | --- |
| `pytest tests/manager/test_completed_output_rescue.py -q --tb=short` | 5 passed in 36.56s; new tests were red before implementation |
| `pytest tests/manager/test_execution_baseline.py tests/manager/test_execution_baseline_reservation.py tests/manager/test_baseline_wait_fact_collection.py tests/manager/test_completed_output_checkpoint.py tests/contracts/test_baseline_pause_schema.py -q --tb=short` | 101 passed in 197.81s |
| `pytest tests/contracts/test_repair_schema_generation.py tests/contracts/test_local_legacy_rescue_schema.py -q --tb=short` | Final regeneration-contract run: 20 passed in 3.72s |
| `pytest tests/contracts/test_repair_schema_generation.py tests/contracts/test_local_legacy_rescue_schema.py tests/contracts/test_baseline_pause_schema.py -q --tb=short` | After independent review: 27 passed in 3.61s; published/fresh embedded Binding regressions were red before the generator fix |
| `pytest tests/web_console/test_transport.py -q --tb=short` | 40 passed in 8.95s, including contract version 5 |
| `node --test tests/team_view/engineering-wait.test.cjs` | Final review-fix run: 97 passed; full historical three-missing-item and real retained-DOM reconciliation regressions were red before their fixes |
| `NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules node --test tests/team_view/browser/task-detail-reading.test.cjs tests/team_view/browser/completed-output-rescue.test.cjs` | 7 passed in 12.39s; no browser errors |
| `NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules node --test tests/team_view/browser/completed-output-rescue.test.cjs` | Final UI review-fix rerun: 3 passed in 4.14s; no browser errors |
| Scoped `ruff check` and `ruff format --check` | Passed; 14 checked Python files already formatted |
| Scoped strict mypy with source/test paths | Passed, no issues in 10 source files |
| `git diff --check` | Passed |

The broad 101-test backend run predates the final pre-consumption proof/inventory
recheck. That final callback was included in the final lint/type checks; Root
repeated the public same-base SQL test on that revision with 1 passed,
10 deselected in 51.12s. The latest new
regeneration assertions and binding else-gate were included in the 20-test
Schema result.

The local same-base tests cover command/Schema validation, real Git unchanged
HEAD/bytes/full inventory, PAUSE and replay, wrong purpose/mode/base, exact
binding proof mismatch, and old canonical binding compatibility. The test for
inheriting an earlier native-rule epoch stubs the previously validated historical
reader and uses the real new proposal/authority/workspace/store-validation
services. It is a narrow lineage-inheritance unit test, not a public durable
old-epoch approval simulation.

DOM/browser tests cover visible target-free preparation, typed ineligibility,
stale/capability/foreign-scope rejection, exact prepared plan vs historical
handling, exact vs unrelated active RESUME, and same-Project ownership
navigation. Browser POSTs are fixture-only and do not contact production ASE.
The final reconciliation regression operates on the retained DOM via
`reconcileViewChildren`: unknown-stop advice and controls become historical
after preparation, the detached HANDLE callback is rejected, read-only INSPECT
and exact PAUSE work, and foreign proof invalidation restores truthful fallback
while rejecting the retained approval.

## Independent public service verification

Root performed these serial MySQL tests using the test-scoped safety gate and
no production writes. See `root-verification.md` for independent details and
the final callback rerun result.

- `completed_output_same_base_pause_resume`: 1 passed, 10 deselected, 48.90s
  before the final callback recheck; final rerun 1 passed, 10 deselected in 51.12s.
- Existing `completed_output_unavailable_pause_resume`: 1 passed,
  10 deselected, 62.18s.

The public fixture begins with a real owned native runner, seals the proof,
proposes via public Host, requires exact human PAUSE, exercises SQL crash/replay
before and after commit, then RESUMEs into a new Coder and independent QA/Review.
It checks authority, wrong scope/revision, workspace/index drift, normal work
budget/no refund and matching candidate revision. Root owns this test file;
the implementer did not alter its independent verification.

## Limits and residual risks

The new purpose applies only to exact completed output unavailable facts. It
does not recover known timeout/provider failure, unknown stop, missing evidence,
unapproved policy changes or an illegal/changed draft. Historical report content
remains unknown. These exclusions are intentional and are shown as prerequisites,
not converted to accepted output or a false success verdict.

The implementation has not been deployed. Existing production data is untouched;
the public recovery sequence is recorded in `implementation.md`. A compatible
reader must remain available once new-purpose records have been persisted. The
full suite remains the user's optional validation, per the incremental-test
preference.
