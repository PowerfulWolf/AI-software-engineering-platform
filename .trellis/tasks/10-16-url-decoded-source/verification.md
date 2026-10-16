# Verification and exact original-data treatment

## Root cause and feedback loop

Public `HANDLE_DELIVERY_WAIT` operation `operation_9cf2c0a056d4813f302185c94c2ece3a`
reported WORKSPACE_CAPTURE_REJECTED. The read-only diagnostic invoked the actual
`GitWorktreeManager.capture_mutations` using sealed Run5 request/permissions, exact
Task revision 8, source774e0a6, real stop proof, frozen denies and all 16 inherited paths.
It rejected the BASE `mysql_repository.py` body at `password=unquote(parsed.password)`.
The 18,099-byte baseline contains no NUL and exactly one source secret_assignment
occurrence. The same expression exists in the current file. Other authorized bodies
had no diagnostic rejection.

The committed-base real Git regression reproduced that same BEFORE-body error before
the fix. Its actual diff changes only an unrelated VALUE. The fixed regression verifies
complete before/after bytes/SHA, exact wire roundtrip, original source/index/status/HEAD
and full capture verification. Separate literal-bearing baselines still reject.

## Checks

All commands below use the repository virtualenv with `PYTHONPATH=src` in the isolated
maintenance worktree. Overlapping groups are reported separately, not added together.

- `python -m pytest -q tests/context/test_source_secret_detection.py tests/context/test_url_decoded_source.py tests/git/test_mutation_capture.py tests/orchestration/test_capture_reconciliation.py`:
  259 passed, 11 existing v1/v2 capability skips in 78.89s.
- `python -m pytest -q tests/context/test_dynamic_credential_source.py tests/context/test_source_inspection_scope.py tests/context/test_generic_redaction_scope.py tests/git/test_capture.py tests/orchestration/test_native_continuation_v2.py`:
  150 passed in 114.43s.
- Final new URL security matrix and baseline regression: 65 passed in 2.85s.
- Independent review found observable namespace mutation through `getattr`,
  `__getattribute__`/`__getattr__`, and `operator`/`_operator` reflection factories.
  These first reproduced RED; the decoder-only proof now conservatively withdraws
  at those entrances. Alias and dynamically constructed property-name variants are
  covered. Final source/generic/scope plus real Git baseline group: 287 passed in 2.35s;
  final Ruff/format, strict mypy and diff checks passed. Existing secrets rules unchanged.
- Independent root run of `tests/orchestration/test_capture_reconciliation.py tests/manager/test_wait_fact_collection.py`:
  62 passed, 11 existing v1/v2 capability skips in 63.90s.
- Modified source/tests Ruff check, format check and strict mypy passed; diff check passed.
- Fixed independent read-only Reviewer: original reflection blocker closed, no remaining
  blocking findings. Independent URL/Git BEFORE-body selection: 87 passed, 39 deselected
  in 4.96s. Final original K1 read-only probe at 05:36:27Z retains the same inventory and
  complete capture SHA above, with no body findings.
- The already authorized isolated MySQL public stopped-failure recovery suite was executed
  earlier for the pending progress-continuity fix: 2 passed in 45.32s. It was not repeated
  or misrepresented as a production K1 acceptance result.

## Actual retained K1 observation

The fixed-platform diagnostic passes complete capture, coverage, verification and final
inventory equality, with 24 source/test files, 183,618 patch bytes and capture SHA
`a6c0a5696f93f8f8078974124c9238c7666c7af35800346709fc28b35d49f760`.
Inventory remains `2986dd5b6064221dc46367a277225de71dbbe69a85c32d44122749eecbb377d0`.
The probe publishes no production receipt, outcome, result or permission. Original run
start `a1e97900673437bf2f9c3eb64fd232d0102ec98fc84509bc67f097153b0e5fef`
and native stop `6f0229548cad36e11a0e9798148f2d38be28de49142bee4147ed7e238692296b`
remain unchanged.

## 存量数据处置

No production SQL updates or original artifact/binding/outcome edits. Independent predeploy
audit at 05:29:24Z verifies all original 195 immutable files unchanged; complete global
queue observation has no active work/claim/Operation. Current PID14732 must produce its own
exact controlled READY before replacement; an old PID99829 READY is not usable. The actual
Host-owned registry remains independently checked by that original Host during drain.

After reviewed deployment, use fresh public facts for HANDLE and any precisely offered
continuation. Preserve timeout and UNKNOWN history, complete drafts and accepted progress
01/02. No evidence yet accepts steps03/04 or a candidate. No maintainer writes the K1 tree.

Rollback requires a controlled safe boundary and compatible readers for any newly sealed
decoder-containing complete bodies; no deletion/rewrite of durable evidence.
