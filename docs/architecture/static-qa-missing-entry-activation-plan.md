# Static QA missing-entry recovery: maintenance authorization proposal

This is an activation plan, not an active recovery route or a live K1 wait
resolution. It targets
platform `main` revision `5536cbbc946dd0a8235d2636d7c9aead50d10ae2`. The
existing K1 ProductSpec, frozen Plan, candidate and product approval remain
unchanged. The inactive proof/output slice is `36f8dbf1100cff37139e552b2f68b409b8cfbff6`;
the additional no-start investigation is `439460de23186b7ae68d9cb58a1b76603a4ece90`.

## One-time maintenance authorization record

The human user confirmed this plan's exact protected-path exception in the
trusted asynchronous reply `call_af8ceccef4f6491097071e3a54bd18d3` with
the exact answer `确认上述一次性维护授权` (UTF-8 SHA-256
`3701bb74227bcc8d1ab4137c9a1aeb2c1ae9cce1f5be08f42b499b85eedc3a22`).
The authorization applies once to the protected paths listed below against
platform `main` `5536cbbc946dd0a8235d2636d7c9aead50d10ae2`. It does not
approve any additional generated path or any change to K1 ProductSpec,
TechnicalDesign, frozen Plan or candidate baseline. This is a conversation
authorization reference, not a platform `HumanActionEvent` or an engineering
resolution; the latter must be sealed separately before consuming a live wait.

Supplemental human authorization `call_c490e86c1251409ca13da375898d720c`
allows only `scripts/sync-requirement-purge-schemas.py` against that same main
revision, using reviewed patch SHA-256
`129dbc09339e656241d8fb491ccd28a2b59dc11523ca3672e9b74b29cf52a9db`.
It preserves canonical wait guards and the Coder-only rejected-knowledge role
when regenerating the already approved deletion-cleanup schema. This reference
also is not a platform `HumanActionEvent` or a live K1 wait resolution.
The one-line import correction was separately approved in human reply
`call_002835614b90489894fd2cbe0fd95a42`; the final exact patch SHA-256 is
`5888d5a8e418274321ce71e8e8b2b9895cba3fe28333c6df15bcbf9018d41cba`.

The public Host test exposed one additional state-machine seam after the
first-stage scope was approved: the consumed static QA decision must be
recognized by the next verifier preparation claim. The human user granted a
single-file supplemental authorization in trusted reply
`call_880fd1048e8645d6ad370c2bcf4db05e` for only
`src/ai_software_engineer/work_queue/preparation_resume.py`, still against
platform main `5536cbbc946dd0a8235d2636d7c9aead50d10ae2`. The exact
reviewed patch is `/private/tmp/ase-k1-static-qa-preparation-resume.patch`,
SHA-256 `a661745afef58dbe745a5ea8d4c97e642f4df3633fe459dcc927cf22c5e56e52`.
This conversation authorization is not a live K1 wait decision. It does not
alter the frozen ProductSpec, Design, Plan or candidate.

## Exact first-stage maintenance scope

The following paths need a named, auditable maintenance authority before a
write that changes Schema, the state machine or Trellis contracts. The list is
intentionally finite; a generator that changes another path must stop and seek
an amended exact authorization before publication.

- `src/ai_software_engineer/domain/delivery_resolution.py`: add a distinct
  resolution kind and proof binding for static QA missing entry. Do not reuse
  `RESUME_UNINVOKED`.
- `src/ai_software_engineer/work_queue/execution_store.py`: consume that kind
  under the Task/queue lock with a fresh QA identity and one-use fence.
- `schemas/engineering-wait-resolution.schema.json`: generated wire contract
  and cross-field guards for the new resolution and proof.
- `schemas/console-deletion-cleanup.schema.json`: nested generated wait models
  in the deletion cleanup response.
- `schemas/console-operation.schema.json`: nested generated wait models in the
  Console operation response.
- `schemas/stopped-failure-budget-settlement.schema.json`: nested generated
  wait models in the stopped-failure settlement response.
- `schemas/stopped-unknown-budget-settlement.schema.json`: nested generated
  wait models in the stopped-unknown settlement response.
- `scripts/sync-engineering-authority-schemas.py`: regenerate the canonical
  resolution schema without dropping existing hand-written guards.
- `.trellis/spec/core/delivery-recovery.md`: nonterminal wait and replay rules.
- `.trellis/spec/core/verification-environment.md`: missing candidate entry,
  original controlled verifier no-start evidence and execution boundary.
- `.trellis/spec/core/native-verification-output.md`: distinct static FAIL
  output contract and fresh-current validation.
- `.trellis/spec/core/index.md`: index the accepted contract.

Ordinary implementation would also use the already scoped
`manager/delivery_wait.py`, `agents/verification_output.py`, production
composition, tests and `docs/`. The four nested generated Schema paths above
are the only additional generated outputs in the first-stage scope. Audit the
exact generated diff and stop before publication if any other path changes;
amend the exact authorization first. No `schemas/**` or `.trellis/spec/**`
wildcard is requested.

## Required admission and validation

The public collector must bind the current waiting WorkItem, frozen Task and
Requirement checkpoint, original QA preparation intent, both historical
claims, original `WAIT/NOT_STARTED` native observation, no invocation start or
outcome, accepted Plan/implementation and full candidate Git tree. It must
prove every named missing test entry is absent at the candidate SHA, not merely
the checkout, and reject a symlink or changed Plan row. A changed active claim,
candidate, queue generation, Task or checkpoint must refuse before a decision.
The read-only `observe_accepted_candidate_test_entry_absence` seam checks the
exact immutable Plan and implementation receipts before the Git-tree probe;
it grants no queue admission or QA verdict. Production must additionally bind
the current wait and original no-start proof before consuming any decision.

The separate engineering decision must bind that proof and be consumed exactly
once under the queue lock. It may requeue the same QA WorkItem only with a fresh
dispatch generation and independent claim, not a QA verdict or a new work
allowance. The planned controlled verifier remains unstarted. QA may inspect
source under its existing read-only policy and may submit only a proof-bound
FAIL with no tests_run or claim that the missing tests executed. Ordinary QA
FAIL routing then returns the findings to
Coder for a new candidate. Browser and live A→B capability registration and
complete independent QA/Review are separate gates.

| Case | Expected behavior |
| --- | --- |
| Exact original no-start and candidate missing entry | Permit an exact proposal, then a separately authorized fresh QA claim |
| Same K1 without new authorization | Keep `WAITING_DEPENDENCY`; no claim, command or model |
| Candidate has the test or a symlink entry | Reject static route |
| Original invocation/native command started or is uncertain | Reject static route; preserve original evidence |
| Changed Plan, claim, Task, disposition or Requirement checkpoint | Reject stale decision; no queue mutation |
| QA reports PASS, claims a planned test command ran, or omits proof | Reject output without verdict publication |
| QA gives proof-bound FAIL | Route genuine findings to Coder; then independently verify repaired candidate |

Existing records require no rewrite or deletion. New records append with exact
source and audit lineage. Rollback disables the new admission and leaves the
original wait, candidate and all historical facts intact. Activation requires
Schema round-trip/tamper tests, SQL crash/replay and owner-fence tests, real
no-start and uncertain-execution negatives, independent QA/Review regression,
and a controlled idle service release.
