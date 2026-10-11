# Backend verification

## Scope and result

The backend now admits a sealed completed, nontransient Coder `INVALID_OUTPUT` only as preserved
draft input to the existing execution-baseline flow. It does not accept or reconstruct the old
report. Same-source and explicitly selected source-update proposals require exact human
engineering authorization, PAUSE and a separate RESUME. Old `WORK_INTERRUPTED` wire fields,
proof digests and SOURCE policy/RESUME bindings remain compatible.

Base: `770c02e85e4bafa01fcef3d69e1d409869848251`. No production SQL, service, model or original
Coder worktree was accessed from this backend worktree. Root owns frontend integration and
production existing-data handling. Those activities are not claimed as verified here.

## Red and green evidence

- The initial actual collector/service rejected-output cases failed: 3 failed in 4.01s. The
  collector returned no completed proof and the proof validator rejected the sealed failure.
  After implementing the unified admission they passed: 3 passed in 17.11s.
- A broader related run had 90 passing cases and two outdated Schema assertions. The assertions
  assumed every SOURCE binding carrying the optional completed digest must reject; they now
  reject the incorrect stopped-provider purpose while permitting the expressly authorized
  SOURCE form. The final Schema suite passed all 19 cases in 6.90s. The independent reviewer
  repeated that suite; its result is not counted as additional coverage.
- The final INVALID_OUTPUT incremental selection passed 44 cases, with 67 deselected, in 92.53s.
  It covers the actual collector, Git/service/store/publication seams, proof integrity,
  scope/claim/source/frozen permission mismatches, earlier accepted publication, ignored paths,
  complete inventory, original stop facts, ordinary budget and refusal of policy/RESUME execute.
- The added historical WORK_INTERRUPTED SOURCE policy/RESUME compatibility case passed. It
  verifies the missing optional completed digest and canonical field omission are still valid,
  reopens the store and replays the exact execution without another reservation.
- The added later accepted StateEvent refusal case passed. Its first test expectation incorrectly
  named `ValueError`; the existing stop gate correctly returned `ContinuationRejected`. Only
  that expected exception type changed, with no production policy change. Its targeted rerun
  passed 1 case in 2.12s.
- The Console manifest single test passed with the running action contract set to version 7.
  Historical version 5/6 fixtures were left intact.

The last three targeted checks were initially run together: the compatibility and transport cases
passed and the StateEvent case failed only on its exception assertion. The failed case was then
rerun separately. No all-green result is claimed for the initial mixed run.

## Commands

Offline checks use the existing environment's Python, with `PYTHONPATH=src` from this worktree.
Replace `python` below with that environment's interpreter if the worktree has no `.venv`.

```sh
PYTHONPATH=src python -m pytest -q -m 'not mysql' \
  tests/manager/test_unaccepted_coder_draft_resume.py \
  tests/manager/test_completed_output_checkpoint.py -k 'invalid_'

PYTHONPATH=src python -m pytest -q tests/contracts/test_repair_schema_generation.py

PYTHONPATH=src python -m pytest -q -m 'not mysql' \
  tests/manager/test_unaccepted_coder_draft_resume.py \
  tests/web_console/test_transport.py \
  -k 'old_unavailable_source or later_adopted_state_event or running_action_contract'
```

Ruff check and format check passed for all 16 changed Python source/test files; strict mypy passed
for the same 16 files. `git diff --check` passed. These are targeted checks, not a full test run.

## Independent public Host and MySQL verification

Root ran the following four parametrized cases in the exclusively guarded test MySQL database:

```sh
PYTHONPATH=src python -m pytest -q \
  tests/manager/test_production_execution_baseline.py::test_public_rejected_completed_output_preserves_original_failure_and_delivers_independently \
  tests/work_queue/test_baseline_pause_mysql.py::test_rejected_completed_output_consumes_once_pauses_and_claims_exact_successor
```

Result: **4 passed in 124.24s**. Two public Host cases cover same-source and updated-source input.
They use a real completed subprocess stop and legal draft with a `{}` report rejected by the real
native adapter as INVALID_OUTPUT, then public propose, exact PAUSE without a Coder call, separate
RESUME, a new Run/Context/claim, candidate and independent QA/Review through DONE. Two SQL queue
cases cover both purposes, exact once-only consumption/release replay, normal work accounting,
no transient refund and a genuinely claimable successor, with unchanged old facts.

Two earlier public runs were red because the fixture did not yet represent the real production
path. The test Manager simulator gained a Schema-valid WAITING_HUMAN diagnosis for INVALID_OUTPUT;
the new rejected-output fixture stopped writing an unauthorized `.mypy_cache/cache.db`. The old
WORK_INTERRUPTED cache fixture remains unchanged. Production permissions were not relaxed to make
those tests pass. Root reported zero owned live processes and all 13 test tables empty after
cleanup; the guarded OS/database locks were released. Backend did not run concurrent MySQL checks.
Root's guarded runner was `/tmp/ase-rejected-output-incremental-20261012.py`; its final cleanup
facts were zero owned processes and 13 empty test tables.

## Contract matrix

| Input or operation | Expected result | Evidence |
| --- | --- | --- |
| Exact completed INVALID_OUTPUT, legal full draft, no target | Existing same-source plan, human PAUSE, independent RESUME | Collector/service and public Host |
| Same facts, explicitly selected trusted source | SOURCE plan and proof-bound human PAUSE; actual rebased after inventory validated | Production publication and updated-source Host |
| Organization policy or execute RESUME for rejected output | Refuse before Git or reservation changes | Service/command/Schema cases |
| Missing/absent-output/live stop, foreign claim/scope/source or changed permissions | Fail closed, old records and draft retained | Parameterized safety cases |
| Existing original or later accepted artifact/event | Refuse; no replacement or state rewrite | Collector publication/event cases |
| Incomplete/unauthorized ignored inventory or mismatched digest | Refuse | Git/proof/facts/Schema cases |
| Exhausted work or attempted refund/applied reservation | Refuse; no refund | Reservation and SQL cases |
| Old WORK_INTERRUPTED SOURCE without optional proof digest | Preserve policy/RESUME and canonical field omission | Dedicated old compatibility case |
| Direct, embedded and freshly generated six Schema graphs | Code/cause/proof and human PAUSE guards agree | 19 Schema cases |

## Existing data handling

No DDL or production SQL update is required. No original outcome, start, stop, failure diagnostic,
Task/event prefix or previous accounting is rewritten. Root must use the same Requirement's public
baseline prepare action, verify the entire legal draft and native-rule/source differences, review
the exact plan, authorize PAUSE and then issue the separate exact latest-bound RESUME. The new
Coder execution is ordinary work and still needs candidate, independent QA and Review.

K1's missing original 10529-byte raw JSON is not reconstructed. Its persisted GIT_CONTRACT
diagnostic does not establish the missing subcause. Preparation can still refuse for a missing
historical claim/stop, active workspace ownership, unsafe ignored content, changed source or
exhausted frozen budget. Such refusal preserves evidence and needs an explicit supported action;
it must not be bypassed by editing the database or creating a replacement Requirement.

## Risks and rollback

- The original invalid report remains invalid and its contents remain unknown. Preserved code is
  only input to a new claimed execution, not implementation acceptance or a QA/Review verdict.
- SOURCE publication must separately validate original before capture and actual rebased after
  inventory. Requiring before and after to be identical would break trusted source updates;
  treating the old capture as proof of the new filesystem would be unsafe.
- Perform a controlled stop before rollback. After a new rejected-output reservation is consumed,
  retain compatible readers and exact decision records and prefer a forward fix. Do not delete
  reservations, reset attempts or resurrect the old work under reverted policy.
- Frontend and production application of this change remain root's responsibility. Full tests
  were not run, following the user's incremental-only preference.
