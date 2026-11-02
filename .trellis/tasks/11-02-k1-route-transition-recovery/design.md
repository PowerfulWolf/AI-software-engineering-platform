# Design

## Failure and contract

The current route configuration is a runtime choice, while each DeliveryAllocation freezes a concrete role ModelSelection. `RESUME_EXECUTION_BASELINE` currently releases a paused WorkItem before checking that the frozen selection is still runnable. The Worker later refuses the CLI/Responses mismatch and leaves the Requirement BLOCKED with the Task still IMPLEMENTING. The generic terminal-Coder recovery reader requires a BLOCKED Task and a final failed route at its current attempt, so it cannot discover this pre-invocation state.

`require_compatible_baseline_routes(config, allocation, policy_lookup) -> None` validates every frozen phase against the current ordered routes and its exact stored policy before baseline continuation is consumed. It raises a fixed, actionable route-transition error before any continuation authorization or queue release. `TeamHost.continue_execution_baseline` and an immediate-resume `execute_execution_baseline` call this guard while the current service instance is stable.

The legacy K1 state needs a separate, one-use settlement and successor source. A trusted reader must bind the exact parent/child checkpoint, Task revision and intent, dispatch, latest preserved baseline binding, queue item/claim history and complete Git inventory. It must prove that the last claim is expired or released, no role invocation or route attempt exists for that generation, and the original worktree has no live owner. Settlement closes only the orphan retry and records a terminal Task event; it does not create a model result, refund budget or rewrite the old route. A dedicated source variant carries the settlement digest and full retained draft into the existing RecoveryPlan approval and new Task machinery. The new dispatch is selected from current Responses settings and cannot inherit the old CLI selection. No new role work starts before exact independent engineering approval.

## Validation matrix

| Case | Expected result |
| --- | --- |
| Frozen route still configured exactly | Existing same-Task resume proceeds |
| Frozen CLI replaced by Responses before resume | Refuse before continuation record/queue mutation; point to new Task path |
| Expired no-invocation claim, exact baseline and 13-file draft | One settlement and exact new RecoveryPlan under same Requirement |
| Active/uncertain claim, any later invocation, changed draft, extra file or missing baseline | Refuse settlement and leave old facts intact |
| Existing settlement replay | Return exact prior result, never duplicate Task/event/queue close |
| New Task Responses Coder completes | Independent QA and Reviewer still gate DONE |

Good: K1's old CLI attempt and draft remain immutable while a new Task starts on the approved Responses route. Base: a paused Task whose route is unchanged continues as before. Bad: changing the old ModelSelection, accepting a retry label as proof of no invocation, or creating a successor without fencing the old queue item.
