# Preserve an exact historical incoming admission during stopped-execution rescue

## Problem and goal

Production K1 successfully re-entered public recovery on main229eabd: expired original Run6
claim became EXPIRED, its fresh guarded claim became RELEASED/EXECUTION_UNCERTAIN, the Task,
source and all195 historical files remain unchanged, and no main Coder call was repeated.
The subsequent public stopped_execution_rescue proposal failed COMMAND_REJECTED:
"容量停止的原 Run 已有原生恢复记录, 不能证明未调用".

The replay-guard observation reuses CapacityInputReader.require_claim_not_started with a
PriorInvocationFence. It precisely recognizes the historical main invocation and capture
start/stop, but fails to recognize its incoming native admission from the preceding rescue.
That admission belongs to the original Run6 claim; it does not authorize the fresh guard claim.
No context-capacity receipt exists for this Task; do not describe this as retired capacity state.

## Scope

Only permit an exact verified incoming admission of the already proven prior invocation.
Do not skip receipts, outgoing admissions, current-claim native facts, unrelated/late/aliased
records, routes or artifacts. Do not weaken ordinary no-start proof without a complete
PriorInvocationFence. No Schema change, direct SQL, historical record rewrite, Task reset,
new Requirement, source change, refund or K1 business checkout edit.

Author owns manager/capacity_input_reader.py and focused tests in
tests/manager/test_replay_guarded_claim_observation.py and
tests/manager/test_stopped_execution_delivery.py. Explain any additional required path
before editing. Root owns task/spec documentation. Author is not alone in this checkout;
do not revert other agents' work. The fixed reviewer remains read-only.

## Acceptance and checks

First reproduce the production incoming-admission failure. Add positive proof through the real
public stopped-execution/native/MySQL recovery fixture with incoming historical admission;
ensure complete PAUSE/RESUME and independent QA/Review still work. Add exact mismatch, missing
receipt, late time, current claim, outgoing and absent/incomplete fence refusal checks. Verify
the generic no-start scanner still rejects any current native execution or recovery record.
Run affected tests serially on the isolated database, strict Mypy, Ruff/format and diff check,
then independent reviewer verification. Do not broaden testing absent a new concern.
Keep existing test_verifier_capacity_input.py native alternate-run receipt/admission refusals green.

## Existing data and rollback

Original Requirement delivery_multi_bb78e2316afca47d005384542f685174535b69db and Task
task_recovery_622f711324450abfffedc2a8d696e2de remain in safe wait, revision8/attempt6,
source774e0a6fcc920d9a6ce3738e80b9cc43045be7eb. Old main starts/outcomes remain6/4,
no active lease exists and all195 sealed files are unchanged. After reviewed deployment,
read fresh public facts, prepare a new exact rescue proposal, delegate approval for PAUSE
then independently RESUME. Preserve old failed proposal and all UNKNOWN history.
Rollback only after controlled stop; retain appended immutable facts and compatible readers.
