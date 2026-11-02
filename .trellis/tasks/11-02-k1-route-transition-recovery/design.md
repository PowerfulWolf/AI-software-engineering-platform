# Design

## Failure and contract

The current route configuration is a runtime choice, while each DeliveryAllocation freezes a concrete role ModelSelection. `RESUME_EXECUTION_BASELINE` currently releases a paused WorkItem before checking that the frozen selection is still runnable. The Worker later refuses the CLI/Responses mismatch and leaves the Requirement BLOCKED with the Task still IMPLEMENTING. The generic terminal-Coder recovery reader requires a BLOCKED Task and a final failed route at its current attempt, so it cannot discover this pre-invocation state.

`require_compatible_baseline_routes(config, allocation, policy_lookup) -> None` validates every frozen phase against the current ordered routes and its exact stored policy before baseline continuation is consumed. It raises a fixed, actionable route-transition error before any continuation authorization or queue release. `TeamHost.continue_execution_baseline` and an immediate-resume `execute_execution_baseline` call this guard while the current service instance is stable.

The legacy K1 state needs a separate, one-use settlement and successor source. A trusted reader must bind the exact parent/child checkpoint, Task revision and intent, dispatch, latest preserved baseline binding, queue item/claim history and complete Git inventory. It must prove that the last claim is expired or released, no role invocation or route attempt exists for that generation, and the original worktree has no live owner. Settlement closes only the orphan retry and records a terminal Task event; it does not create a model result, refund budget or rewrite the old route. A dedicated source variant carries the settlement digest and full retained draft into the existing RecoveryPlan approval and new Task machinery. The new dispatch is selected from current Responses settings and cannot inherit the old CLI selection. No new role work starts before exact independent engineering approval.

## Validation matrix

## Verified legacy shape and implementation seam

The current live row is not an ordinary terminal Coder failure. Task revision 5
remains `IMPLEMENTING` with attempt 6; the sixth WorkItem is
`RETRY_SCHEDULED` at dispatch sequence 3 after its only claim ended `EXPIRED`.
The last queue event is `LEASE_EXPIRED`; there is no sixth invocation, model
route, native capture or accepted output. The child and parent Requirement
checkpoints already say `BLOCKED` while their Task reference still points at
revision 5. Consequently `NativeRecoverySourceReader._sql()` cannot be called
on the current child checkpoint after an administrative Task terminal event:
it requires the checkpoint's Task revision/status to match SQL. A dedicated
settlement reader must bind the old checkpoint to the exact appended terminal
event, or the public delivery service must append a new replayable child and
parent checkpoint before the ordinary terminal reader can be reused. It must
never synthesize a checkpoint only in memory.

The pre-invocation proof must combine the ended claim and unique
`CLAIMED`/`LEASE_EXPIRED` event chain, an exclusive existing Task lock, no active
SQL claim, `CapacityInputReader.require_claim_not_started()` with an exact
`UninvokedClaimBoundary`, and a complete retained worktree inventory compared
with the latest consumed baseline. Claim expiry or absence of an invocation
file alone is insufficient. The settlement is a new typed route-transition
fact; it must not reuse `UNKNOWN`, context-capacity or stopped-failure records.
Its Task `IMPLEMENTING → BLOCKED` event and WorkItem `RETRY_SCHEDULED → CLOSED`
event commit in one queue transaction under the Task and queue fences. The
record is written before consumption and exact replay repairs only missing
publication. The original retry debit, dispatch, baseline and draft remain
unchanged. RecoverySource then binds the settlement digest and reads the old
execution context as a historical input, while explicitly representing that
the sixth attempt has no Run or Context. The approved new Task gets a fresh
Responses selection; the old CLI selection is never rewritten.

| Case | Expected result |
| --- | --- |
| Frozen route still configured exactly | Existing same-Task resume proceeds |
| Frozen CLI replaced by Responses before resume | Refuse before continuation record/queue mutation; point to new Task path |
| Expired no-invocation claim, exact baseline and 13-file draft | One settlement and exact new RecoveryPlan under same Requirement |
| Active/uncertain claim, any later invocation, changed draft, extra file or missing baseline | Refuse settlement and leave old facts intact |
| Existing settlement replay | Return exact prior result, never duplicate Task/event/queue close |
| New Task Responses Coder completes | Independent QA and Reviewer still gate DONE |

Good: K1's old CLI attempt and draft remain immutable while a new Task starts on the approved Responses route. Base: a paused Task whose route is unchanged continues as before. Bad: changing the old ModelSelection, accepting a retry label as proof of no invocation, or creating a successor without fencing the old queue item.
