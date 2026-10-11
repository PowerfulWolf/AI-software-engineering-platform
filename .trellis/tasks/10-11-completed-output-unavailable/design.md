# Design

Base: `60512345ebcb15986a93e1458ffec554e59a139d`. This is a baseline-only extension.

The source investigation established two independent facts: the invocation adapter durably
returned FAILED WORK_INTERRUPTED without an artifact, while its trusted native runner separately
sealed completed returncode0/output_present=true. The adapter calls `finished` before reading
the temporary last-message file; a rejected inventory exits the temporary directory and removes
that output. Its bytes cannot be reconstructed from the existence Boolean. Existing rejected
progress requires a parsed SUCCEEDED artifact, interruption receipts require truthful cause plus
absent output, and legacy rescue requires absent outcome/ledger. None can be relabelled to admit
this case.

## Data flow and ownership

```text
immutable invocation outcome + capture start/stop + historical claim
  → ProductionBaselineFactCollector under Task lock / idle SQL fence
  → CompletedCoderOutputUnavailableProof (unknown output, no readiness)
  → BaselineExecutionFacts + ordinary-work reservation
  → full original-before/current inventory authorization + dirty/complete capture
  → exact ExecutionBaselinePlan
  → engineering approve exact plan with PAUSE
  → existing fenced queue consumption, fresh ordinary-work successor
  → explicit latest-bound RESUME → fresh Coder claim → QA → Review
```

`manager/completed_output_checkpoint.py` owns the new versioned proof and the complete mutation
coverage check. It contains no store/state/command authority. The production collector validates
the original immutable ledger and claim with `validate_capture_stop`, including the real stop
recheck; it separately refuses original or later accepted publication/StateEvent adoption.
`ExecutionBaselineService.propose` runs existing full Git captures and then authorizes every
original-before/current mutation, including ignored files. It requires every noncache mutation
to be captured or belong to exact inherited progress. Ordinary snapshot/path/body/secret/index
and final source/inventory rechecks remain.

Baseline facts/reservation use optional excluded-None fields, preserving old canonical hashes.
`completed_output_unavailable` is a distinct baseline reservation cause; existing queue code
charges it through the ordinary-work branch. It cannot use `retry_failure`, interruption receipt,
legacy containment or already-applied reservation. General DeliveryResolution does not change.
SOURCE_REBIND still requires a different target; no new same-base rescue purpose is added.

Canonical Schema guards live in `sync-legacy-rescue-schemas.py`; standalone and embedded new
proofs constrain unknown output, FAILED WORK_INTERRUPTED/nontransient/noartifact, and completed
returncode0/output_present=true/no cause. Facts/reservation enforce matching presence gates.
Existing semantic digest/identity equality remains enforced by typed models/application services.

## Verification seams

The first red test is the existing public TeamHost baseline workflow's new completed-output
parameter: a real owned subprocess writes a draft, temporary output and oversized fixture cache,
exits successfully, then final inventory rejects before parse. After separate isolated cache
maintenance, public PROPOSE previously failed in `_reservation`. The implementation passes the
full exact approval/PAUSE/RESUME/new-claim/QA/Review workflow without changing the old result.

Additional tests exercise typed proof/Schema negatives, real fenced collector scope/claim/source,
unknown/live/missing stop, artifact publication, full ignored-mutation coverage, secrets, normal
budget exhaustion, and historical excluded-None wire compatibility. Existing no-DB baseline,
proposal fact, reservation, invocation and pause modules are retained as regressions.

## Existing data and deployment

No runtime was loaded or restarted. No production DB, main checkout, model, Task, sidecar or cache
was touched. Root owns separately approved exact stock cache preservation/removal audit. The
future public source proposal must select the actual approved target and expose the complete plan;
only exact engineering approval may consume it. Original FAILED/noartifact/stop/output-present
facts remain. Recovery still needs remaining frozen ordinary work and a nonterminal Task.
