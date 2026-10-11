# Incremental verification

## Safety and existing data

The worker performed no production mutations, restart, approval, commit, delivery action,
or deletion. Production facts and immutable output/stop/artifact bytes remain owned by the
root's separately recorded `production-before.json`; this file does not replace that audit.

The implemented route reads the original successful completed invocation and captures a
separate legal draft checkpoint. It never relabels completion as timeout, refunds transient
budget, edits an old artifact, or creates a new Requirement/Task/branch. Consumption requires
the exact current waiting item, frozen Task/step/source, original claim, no active Task claim,
no StateEvent adoption, no original queue completion, no independent publication at/after
the checkpoint, and remaining frozen work budget. It increments one work reservation and
creates a fresh queued attempt. A consumed resolution filters only the rejected artifact ID
from normal execution inputs; the original receipt, artifact bytes and legal ancestors remain.

The full original inventory-before → inventory-after difference is authorized by the native
mutation policy. Noncache changes must be represented in the capture or explicit original
continuation inputs. The record additionally requires an empty Git index and real completed
stop. Readmission rechecks HEAD, index, complete capture bodies, full inventory, exact current
claim/decision and permissions; a missing decision rejects rather than granting dirty access.
The production collection wrapper holds the queue idle fence and the service holds the Task
process lock; original claim/publication/scope/stop inputs are checked before and after capture.

## Commands already passed

- `.venv/bin/pytest -q tests/work_queue/test_wait_resolution_mysql.py`: 20 passed in the
  combined MySQL incremental run (7.49s, initial new fixture errors were subsequently fixed).
- `.venv/bin/pytest -q tests/work_queue/test_rejected_output_mysql.py`: 5 passed (1.72s),
  serial isolated MySQL. Covers exact one-time consumption, original receipt/history retention,
  artifact filtering decision readback, no transient refund, claim/scope/publication drift
  transaction rollback and rejection of a StateEvent-adopted output.
- `.venv/bin/pytest -q tests/manager/test_rejected_coder_output.py`: 17 passed (27.07s) before
  the final three boundary tests were added. Covers legal existing dirty files, ignored and
  protected mutation rejection, staged-index rejection, real publication receipt preservation,
  exact new claim/source/run/context/permission/workspace admission, precise artifact exclusion,
  and real Codex adapter dirty rejection without a decision or runner invocation.
- `.venv/bin/pytest -q tests/domain/test_rejected_output_schema.py tests/contracts/test_repair_schema_generation.py tests/domain/test_knowledge_preparation_retry_schema.py`:
  53 passed (3.45s). Covers both public schemas' required evidence, forbidden timeout/replay/role/
  classification combinations, historical optional-field digest stability, legacy guards and
  deterministic regeneration without requiring a previous output file.
- Scoped Ruff: all checks passed across the 9 touched production files, 4 focused test files
  and the engineering schema generator.
- Scoped strict mypy: success, no issues found in 13 production/test source files.

## Final combined regression

Passed: **147 tests in 101.29s**.

`.venv/bin/pytest -q tests/manager/test_rejected_coder_output.py tests/manager/test_delivery_wait.py tests/manager/test_wait_fact_collection.py tests/domain/test_rejected_output_schema.py tests/domain/test_knowledge_preparation_retry_schema.py tests/contracts/test_repair_schema_generation.py`

No full test suite was run.

## Implementer allowlist

Production files changed by `inspect_recovery_entry`:

- `src/ai_software_engineer/domain/delivery_resolution.py`
- `src/ai_software_engineer/manager/rejected_output_checkpoint.py` (new)
- `src/ai_software_engineer/manager/wait_fact_collection.py`
- `src/ai_software_engineer/manager/delivery_wait.py`
- `src/ai_software_engineer/work_queue/execution_store.py`
- `src/ai_software_engineer/work_queue/worker.py` (exact accepted artifact filter)
- `src/ai_software_engineer/agents/workspace_admission.py` (conditional selector)
- `src/ai_software_engineer/manager/production_delivery.py` (typed wrapper)
- `src/ai_software_engineer/manager/production_backend.py` (trusted admission and claimed context)

Wire/generator files:

- `scripts/sync-engineering-authority-schemas.py`
- `schemas/engineering-wait-resolution.schema.json`
- `schemas/console-operation.schema.json`
- `schemas/rejected-coder-output-checkpoint.schema.json` (new)

Focused test files:

- `tests/manager/test_rejected_coder_output.py` (new)
- `tests/domain/test_rejected_output_schema.py` (new)
- `tests/work_queue/test_rejected_output_mysql.py` (new)
- `tests/work_queue/test_wait_resolution_mysql.py` (fixture opt-in for real rejected publication)

Task/spec/UI/pending-recovery/live-validator changes belong to the coordinating root and other
workers. This implementer did not change their files, `runner._run_agent`, immutable production
history, the service or Git history. `git diff --check` passed after final regression.

## Rollback and limits

Before consuming a new resolution, the code can be reverted while retaining newly sealed
read-only audit records. After consumption, deploy a version that understands the new
resolution/event/record; do not delete or rewrite consumed history or downgrade to a reader
that does not recognize the new enum. Existing K1 handling must be invoked through the public
exact wait recovery entry after deployment and validation of the root's before/after audit.

This route deliberately handles only a machine-verifiable Coder progress sequence mismatch
with otherwise legal complete draft capture. Unknown results/process stops, permission errors,
different semantic failures or exhausted budget stay fail closed; QA/Review remain independent.

## Root independent review and browser verification

Root independently ran 84 focused pending/rejected-manager cases (44.03s), 19 domain/Console
scope cases (1.24s), 97 relevant DOM cases and all 4 engineering-wait real Chrome cases
(7.68s); all passed. Scoped Ruff and strict mypy for 13 source modules passed.
Independent read-only review found no remaining blocking issue. Frontend missing/invalid
mandatory evidence removes continuation and success wording; old callbacks issue no write.

Before rollout root used only a real production READ ONLY transaction to run the new stored
wait reader: exact original Task, revision8 and attempt4 wait were validated. No Task/queue
mutation or model call occurred. Full retained inventory and five immutable file SHA-256
values are saved in production-before.json; public deployment/recovery verification follows.

## Public production recovery verification (2026-10-11)

Commit fa85a65 was pushed and deployed through the controlled service restart. Before restart
there were zero active Operations, zero ACTIVE queue claims and no service descendants. The
old lifecycle confirmed all operations/writes/executors/indexes ended before exit; service
36329 was replaced by 52944. No force kill or lifecycle record deletion was used.

Public CONTINUE_DELIVERY operation operation_fb34ea87afe9a0c0562d3028b1d07e7e used the
verified original joint checkpoint4cd7e8f43914a6ce23c6e5252ac58cf362ae78d71683dbe290c8dfbaf3b246ae.
The original native cursor was reattached to task_recovery_8ca06fa0aec236ab940597ad1482bfc8,
DELIVERING/IMPLEMENTING/revision8, digestf4d80fcbc0576345c6e0426eab15567d2939f8684ecbb76d0a5d3c3f35a6d38a.
The outer delivery service then used the Task's existing frozen organization engineering policy
to handle the precise wait and consume RETRY_REJECTED_CODER_OUTPUT without a second human
approval. It did not replay attempt4 or change its outcome.

Resolution a86383d8a635835c9329f1d82442e77d33a92d4c5f91e9300460fecb0935ec21 closed only
the original waiting work and reserved attempt5, with budget_refund=false. The same Task,
source90cefe26a46c3b1593521f6416631f38472a4c58, semantic branch and retained worktree continue.
The sealed inventory d14dbe071f165ee415d3162861c07bb98c07d365eba1a9f387761ced99dbf034 equals
the complete inventory observed before maintenance. All five original immutable files retain
exact byte SHA-256 values. Detailed read-only before/after facts are in production-before.json
and production-after.json. No direct database mutation was used.

Knowledge intent (88.064s) and assessment (160.450s) completed using Codex/gpt-6.1-sol. The new
main Coder invocation run_b4c092e645be48a69dc754db1bfffa0b started at09:06:45.010789Z. At this
verification point it has a live claim, not a final outcome or candidate. Requirement delivery
remains in progress and still requires independent QA and Review. Team API read contention
remains under separate investigation; these verified queue facts do not claim the production
page has been visually validated.
