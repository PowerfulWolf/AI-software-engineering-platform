# Verification record

## Scope and environment

Maintenance worktree: `/tmp/ase-fix-legacy-ignored`. Python tooling is the main checkout's `.venv`,
whose editable installation points to the main checkout. Execute tests with `PYTHONPATH=src` and
type checks with `MYPYPATH=src` so the modified maintenance source is the tested source.
MySQL tests use only `ASE_TEST_MYSQL_DSN`, validated by `tests/conftest.py` and
`tests/mysql_safety.py`; do not use the production config/DSN or run simultaneous reset fixtures.
Native tests use offline model fixtures plus real local subprocesses, Git and isolated claims.

## Completed observations

- Public fixture first actual run reached the genuine expired-guard native stop: failed negative
  exit, complete owned-session-empty proof, `cause=null`, `output_present=false`, bounded
  `local_expiry` abort reason, no invocation outcome and original RUNNING WorkItem without a live lease.
- The ordinary expiry route first produced `RETRY_SCHEDULED`, as designed. The fixture now shortens
  only the test dispatcher's delay to one microsecond, then submits a second public Continue.
  It observed a separate real claim and `EXECUTION_UNCERTAIN` wait without a second Coder call.
- The public new-purpose proposal exposed a real failure in old cause-dependent receipt
  reconciliation. Backend correction routes this purpose through direct stopped-proof validation.
  The corrected full result passed in the root task's final isolated-MySQL test batch (41.91s).
- `ruff format tests/manager/test_stopped_execution_delivery.py`: passed.
- `ruff check tests/manager/test_stopped_execution_delivery.py`: passed.
- `MYPYPATH=src mypy tests/manager/test_stopped_execution_delivery.py`: passed.
- `git diff --check -- tests/manager/test_stopped_execution_delivery.py`: passed.
- Root: all 29 changed Python files passed Ruff and format checks; 17 changed production
  source files passed `MYPYPATH=src python -m mypy`.
- Root: manifest contract-9 regression passed (1 test), and combined stopped-rescue plus
  engineering-wait JavaScript checks passed (116 tests).
- Root: full public fixture actually ran after explicit sandbox-outside approval and exposed
  a second real boundary: the ordinary reclaimed claim finished RETURNED knowledge, then the
  durable invocation fence rejected a new Coder call. The baseline collector incorrectly demanded
  a failed-knowledge/preflight marker for that claim. The new current observation family corrected it.
- Independent review found raw ArtifactStore absence must not use AcceptedArtifactStore's
  filtered view. The regression now uses a real RoleQueueAdmission and demonstrates that
  an unaccepted original-run artifact is hidden in the filtered view. The original code was
  observed RED before the raw-store correction; final green is recorded when available.

The first attempted local DB test was sandbox-denied. Subsequent real DB test execution above used
approved isolated local access. Two later command-start requests timed out in automatic approval
review before execution; they are neither passing tests nor runtime failures. MySQL test ownership
has been handed to the root task for sequential final verification.

## Final verification gates

| Command / review | Assertions | Result |
| --- | --- | --- |
| `PYTHONPATH=src python -m pytest tests/agents/test_guard_abort_native.py` | Real stop after revoked guard; unchanged Task/events; no result | See completed results below |
| `PYTHONPATH=src python -m pytest tests/manager/test_stopped_execution_rescue.py tests/manager/test_completed_output_checkpoint.py` | Exact stopped proof, negative/tamper matrix, historical optional fields, PAUSE and no refund | See completed results below |
| `PYTHONPATH=src python -m pytest tests/manager/test_stopped_execution_delivery.py` | Public original-Task DONE, same candidate, distinct agents, preserved unknown, audit/ADR | See completed results below |
| `node --test tests/team_view/stopped-invocation-rescue.test.cjs` | Contract 9, exact plan, stale/disconnected/old-service refusal | See completed results below |
| Schema generation / nested contract tests | Fresh generated and static nested guards agree; no weakened old contract | See completed results below |
| Ruff / format / mypy for all changed files | No standards/type regression | See completed results below |
| Independent read-only review | Contract and standards findings resolved | See completed results below |

### Completed final results

- Public full-chain fixture: **1 passed in 41.91s** after replacing the unobserved scripted knowledge
  client with the existing actual observed HTTP adapter and offline response transport. Original
  stop/start bytes and missing outcome remain; the reclaimed claim has one exact current observation.
  Same Task, ordinary work accounting, native Coder, distinct QA/Reviewer, same-candidate PASS/APPROVE,
  final DONE, audit/ADR and subsequent complete history traversal all passed.
- Root combined static/fresh guard/stopped/owned-session schemas and worker abort checks:
  **35 passed in 7.65s**.
- Root frontend stopped-rescue and existing engineering waits: **116 passed**.
- Root manifest contract 9: **1 passed**. Root all 33 changed Python files: Ruff and format passed.
- Root type checks: initial 17 production files and then the 3 new/changed reclaim helpers plus
  the public fixture passed strict mypy. Independent reviewer repeated affected strict checks.
- Backend real owned-stop proof matrix: **18 passed**, including old optional-field-absent unknown
  classification, exact PAUSE, exhausted work and raw artifact/route negatives. The raw ArtifactStore
  regression was observed RED with the accepted-only view, then GREEN after correction.
- Backend current-observation/old-invocation matrix: **35 passed**; original knowledge claim
  regression **12 passed**; latest observation/collector repeat **24 passed**.
- Independent read-only review repeated **35 observation/invocation tests**, **12 knowledge tests**,
  **31 published/fresh Schema checks**, UI checks and strict static checks; identified findings fixed.
- Real browser stopped-rescue verification from the UI implementation: **2 passed**. A later independent
  browser retry could not launch Chrome under the sandbox and supplies no additional UI result.
- Final public fixture rerun: **2 passed in 57.91s**. The normal case completes the original
  Task through separate QA/Review. The late-artifact case publishes a real schema-valid raw
  original-Run artifact inside the final SQL consumption callback, observes the production
  validator reject it, and proves no consumption, successor queue/claim or extra model call.
  Original Task/events/history, draft bytes, HEAD/index and dirty inventory remain unchanged;
  the injected immutable raw publication is retained.
- Final strict mypy repeat: **20 source/test files passed**; stopped-rescue UI repeat **5 passed**;
  `git diff --check` passed. The public fixture and legacy compatibility fixture use isolated
  local MySQL and temporary native subprocesses under the user's explicit outside-sandbox authorization.
- Existing legacy local-stop/ignored-source public recovery regression:
  `test_public_host_rescues_original_unknown_coder_without_rewriting_history[False-False-True-False-True]`
  **1 passed in 62.40s**. This confirms the new final-consumption callback still accepts the
  legitimate legacy route while retaining original UNKNOWN history and complete ignored source.

Do not treat a real production model run as a substitute for the offline public fixture.

## Production existing-data disposition (pending)

Original K1 stays the recovery target. Original start/stop bytes, missing outcome and unknown cause
are retained. Record precise public proposal, paused execution and separate resume operation IDs,
plan/binding digests, Task/WorkItem identities, complete before/after inventory and final native
delivery facts after those operations actually finish. No direct SQL repair, recreated Task,
fabricated result or old checkpoint is permitted. A successful maintenance test does not imply
K1 business delivery has passed QA or Review.

## Rollback

Use controlled pause and drain before runtime replacement. Retain all newly sealed plans,
authorities, bindings, queue consumption/releases and human-action events. Deploy only a reader
capable of validating the appended contracts; never mutate or delete historical records or input
drafts to make an older binary run. Keep the Requirement paused if safe compatible rollback is unavailable.
