# Contracts and validation matrix

`StoppedUnknownBudgetSettlement` is separate from `StoppedFailureBudgetSettlement`. It binds
the original Task snapshot, DeliveryWaitInvestigation, exact WorkItem/step, full typed
StoppedCoderExecutionProof, expected/closed WorkItem SHA, original full inventory SHA, retained
CapturedMutations SHA and BLOCKED event. Records are sealed before SQL consumption in
state/delivery-preflight under stopped-unknown-budget-settlements/captures/handlings.

`StoppedUnknownBudgetSettlementService.try_settle` runs only for Coder EXECUTION_UNCERTAIN,
IMPLEMENTING, exhausted ordinary budget and a unique waiting item. It requires the actual
exclusive Task lock, idle authority transaction, full original-start/stop/claim and no-final-fact
rechecks, complete legal capture and double inventory comparison. The shared SQL CAS may accept
a typed union of the two strict settlement models. Its operation remains one StateEvent plus
one CLOSED WorkItem; budget_refund=false and attempts unchanged.

`RecoverySource.stopped_unknown_settlement_sha256` is absent on historical wire. The specialized
reader independently verifies the sealed pre-terminal facts, source epoch, terminal reducer and
closed item plus fresh original session emptiness. It never creates a DeliveryInvocationOutcome
or ModelRouteAttempt. It supplies full captured draft to an exact new RecoveryPlan; coder_reapply
reads every required patch from a clean approved target base. Existing source/target rule and
Engineering authority gates remain mandatory. New budget belongs solely to the successor Task.

| Case | Result |
| --- | --- |
| Exact stopped UNKNOWN, legal complete draft, exhausted work | Audited BLOCKED settlement; recovery proposal available |
| Ordinary budget remains | Existing same-Task stopped rescue; no administrative terminalization |
| Outcome/route/artifact/receipt appears, current claim, changed source/scope/index/inventory | Refuse without queue/state changes |
| v2 output file exists, exit 0, malformed stream | Keep UNKNOWN, never infer candidate or success |
| Exact replay before/after SQL commit | One terminal event and one closed work item, same seal |
| New recovery exact approved | Same Requirement, new authorized Task/Run/claim/Context |
| Old approval or changed plan/input | Refuse before execution |
| Missing browser/live verification executor | WAIT_ENGINEERING; never fake E2E PASS |

Good: public HANDLE then plan/approval restores K1 within its original Requirement.
Base: ordinary stopped failed settlement remains unchanged. Bad: delete budget guards, refund
unknown work, accept arbitrary dirty source, use old failed route or rewrite original outcome.
