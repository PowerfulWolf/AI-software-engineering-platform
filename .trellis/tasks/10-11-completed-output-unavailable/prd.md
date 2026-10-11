# Completed native Coder output unavailable: same-Task baseline recovery

## Goal and authorized scope

An original native Coder call can complete with returncode 0 and observed output present,
yet final workspace validation can reject before output parsing. Its durable result is
FAILED / WORK_INTERRUPTED / nontransient / no artifact. Permit exact engineering-approved
source rebinding of this same nonterminal Task with its full legal draft and a fresh ordinary
work attempt. Preserve the unknown output content, original failure, stop and audit history.

Root authorized implementation on 2026-10-11. Base: `60512345ebcb15986a93e1458ffec554e59a139d`.
Only the separate `ase-recovery-contract-research` checkout is writable. Other agents share
the codebase; do not revert their edits. Root performs the independent implementation review.

Allowed files: `manager/baseline_models.py`, `manager/baseline_production.py`, a new typed
completed-output checkpoint module, `manager/execution_baseline.py`, necessary
`domain/execution_baseline.py` / `work_queue/baseline.py`, Schema generator and generated
baseline/checkpoint Schemas, scoped manager/contract/queue tests, relevant spec/docs and this
Trellis task. No production/main-checkout/DB/model execution or native session-stop change.

## Acceptance criteria

- A trusted proof binds exact FAILED WORK_INTERRUPTED/nontransient/no-artifact outcome,
  original invocation/capture start, historical claim, real completed returncode0 stop,
  output_present=true, no timeout/provider cause, frozen scope/source/permissions and digest.
- FAILED alone never proves stopped. Missing/foreign/live stop, claim/scope/source drift,
  accepted publication or StateEvent adoption reject without writes or budget changes.
- Proposal checks original before versus complete current inventory, authorizes every mutation
  including ignored noncache files, and covers all noncache mutations with the full legal draft
  or exact inherited paths. No partial capture, secret, symlink or unauthorized path acceptance.
- Use existing SOURCE_REBIND with a different exact target base and existing
  PROPOSE → exact engineering approval → PAUSE → exact RESUME. Only the complete sealed plan
  establishes workspace readiness; a stop/outcome proof alone does not.
- Reservation uses `completed_output_unavailable`, a fresh normal work attempt and no transient
  retry failure/refund. Respect frozen budget and immutable old FAILED outcome.
- Existing absent fields do not change historical wire bytes/digests. Schemas/generators agree.
- A public Host regression reaches a fresh Coder claim, then independent QA/Review, preserving
  Requirement/Task/branch identity and old failure history. Include PAUSE, replay and RESUME.

## Validation and rollback

First add/run the public Host completed case red, then implement. Incremental unit/contract
tests cover exact source/lease/output/stop/scope, secret/unauthorized ignored files and budget.
Run scoped pytest, Ruff/format, strict mypy and diff checks. MySQL tests must use only an
isolated test fixture database; no production DSN or direct stock-data mutation.

Rollback before consumption is the scoped patch reversal with all existing durable facts
retained. After a new decision is consumed, compatible readers/writers must remain and a
forward fix is preferred; never delete a decision or reopen old work to roll back.

## Existing data handling

Root separately owns exact cache preservation/removal audit for run7. This implementation
does not claim that cache cause is durable, clean any worktree, alter an old outcome, refund
work, or bypass approval. Once code is loaded at a controlled idle boundary and root's exact
maintenance is audited, use public baseline propose, review its full captures and facts,
approve the exact plan with PAUSE, then explicitly RESUME the latest exact binding.
