# Complete inherited reapply inputs

## Implemented contract
- `RecoveryPlan.inherited_reapply_inputs` is optional and absent from every canonical wire when
  None. Its typed inputs bind original approved Plan/Task/actual Context, original URI, full UTF-8
  body, bytes and SHA. Count and total body bytes remain bounded; no path permission is added.
- `recovery/inherited_input.py` reconstructs oldest-first ancestry from trusted immutable stores,
  source Task metadata and actual invocation Context. Old field-absent Plans are traversed too.
  Strict seed does not erase older reapply sources. Plan, authorization, sealed Task, dispatch,
  seed, first actual main, failed main and source epochs must match. Cycles, missing/changed facts
  or mismatched frozen ancestry fail closed. Original source failures/drafts are never modified.
- `recovery/inherited_queue.py` uses a consistent read-only SQL transaction and no queue
  constructor/DDL. It verifies queue admission, original role steps, unique CLAIMED event,
  historical claim allocation and any complete immutable snapshot, exact baseline overlays and
  bounded parent ancestry. Team and Repository come from recovery scope; Project comes from
  the trusted registry. Lease release/expiry is not treated as stop proof. Knowledge-only retries
  do not impose a new attempt=1 requirement on first actual main execution.
- The actual invocation filename/key is checked after bounded unique Run selection. Inherited
  Context sources preserve exact original body/URI/bytes/SHA without truncation, required and
  Coder-only. Current `recovery.patch` remains independent. Proposal/current checks, preparation,
  later production Context and the final provider gate all enforce the same inputs.
- A final gate refusal returns a definitive failed `WORK_INTERRUPTED` result, so the ordinary
  invocation control can seal its outcome. Malformed original claim KeyError/TypeError and known
  SQL availability StoreError/MySQLError become typed recovery refusals. Database/vendor text
  is replaced by a fixed safe message; ownership/wait exceptions and unknown bugs are not swallowed.
- `scripts/sync-inherited-reapply-schema.py` updates only this additive property and its new
  definition. It preserves handwritten guards and all unrelated definitions. Existing capacity,
  target-authority and branch synchronization scripts are narrow updates and retain these nodes.

## Verification
Maintenance checkout is `/tmp/ase-fix-legacy-ignored`; use `PYTHONPATH=src` and `MYPYPATH=src`
for the editable Python runtime. No production database was used by these implementation tests.

- Final new focused tests: `pytest tests/recovery/test_inherited_reapply_inputs.py
  tests/recovery/test_inherited_queue.py tests/recovery/test_inherited_lineage.py -q`:
  **37 passed in 7.26s**. They cover complete/required role Context, bytes/hash/URI/truncation,
  old canonical digests and static Schema, narrow Schema regeneration, count/byte bounds,
  legacy field-absent recursive strict-seed ancestry and missing/rejected authority, original
  queue identity/source/step/allocation/snapshot negatives, and final refusal with provider count
  zero plus a real durable invocation outcome for malformed claim, connection and SELECT failure.
- Related existing suite: `pytest tests/recovery/test_inherited_reapply_inputs.py
  tests/recovery/test_models.py tests/recovery/test_reapply.py tests/recovery/test_authorization.py
  tests/recovery/test_task_record.py tests/recovery/test_first_real_seed_admission.py -q`:
  **78 passed in 9.88s**. This suite overlaps the new tests; counts are not additive.
- Ruff check and format check passed for all 12 owned Python source/test/script files. Strict
  mypy passed for the same 12 files. Source also passed strict type checking independently before
  integration. The main checkout remains untouched by this subtask.
- Independent public Git/MySQL chain and independent actual K1 read-only history validation are
  owned by the wire/reviewer agents; their evidence is recorded in the task verification document.
  The public chain loaded the normal core before the final two error-boundary patches. The
  final focused tests independently cover those patches; normal SQL/lineage behavior did not change.

## Stored data / rollback
No SQL migration, direct production edit, original Task reset, verdict update or K1 continuation
was performed by this implementation subtask. Deploy while idle, re-propose through the public
scope/Plan approval path, and independently validate actual K1 inputs before dispatch. Retain the
historical full patch, current partial draft, original failure and budget history. Reverting to a
reader that silently omits newly published inherited inputs is unsafe; rollback must retain
the additive readers or stop before new Plan execution.
