# Completed native Coder output unavailable

## Scope and signatures

This capability handles a nonterminal IMPLEMENTING Task with a sealed FAILED
WORK_INTERRUPTED/nontransient/no-artifact result and separately sealed completed native
stop (returncode0, output_present=true). Output content and why it was not accepted remain
unknown unless separately evidenced. It is not TIMEOUT, provider failure, invalid artifact,
legacy unknown execution, a candidate or a verdict.

```python
CompletedCoderOutputUnavailableProof.create(...) -> CompletedCoderOutputUnavailableProof
CompletedCoderOutputUnavailableProof.validate_integrity() -> None
ProductionBaselineFactCollector.collect(target_base_ref: str) -> BaselineExecutionFacts
validate_completed_output_capture(proof, dirty_capture, inventory, permissions) -> None
require_completed_output_workspace(proof, dirty_capture, inventory, permissions, denied_paths) -> None
ExecutionBaselineService.propose(target_base_ref, input_mode, purpose) -> ExecutionBaselinePlan
ExecutionBaselineService.execute(plan_sha256, authority=...) -> ExecutionBaselineBinding
ExecutionBaselineService.continue_execution(binding_sha256, authority=...) -> Task
```

The public API remains the existing baseline proposal/execution/continue flow. No raw store,
process-stopped flag, shell, output-replay or cleanup permission is introduced.

## Exact contracts

The typed proof contains original immutable DeliveryInvocationOutcome, ExecutionCaptureStart
and ExecutionCaptureStop plus its digest. Validate original start/request/work/lease/checkpoint,
real historical claim and claim scope, process-stop/start digest and time, frozen Task intent,
policy, permissions and exact native Requirement/dispatch scope under existing idle/Task fences.
Require Coder FAILED, WORK_INTERRUPTED, transient=false and artifact=None; completed returncode0,
output_present=true and no cause/original_error_code. Recheck actual PGID absence through the
existing native stop seam. Do not strengthen or reinterpret its historical proof scope.

Baseline facts add optional `completed_output` excluded when None. Reservation adds optional
`completed_output_sha256` excluded when None and distinct `retry_cause=completed_output_unavailable`.
Require outcome/start/proof references, next attempt=current+1, no receipt, no containment,
no retry_failure, no already-applied reservation. New execution consumes normal frozen work;
no transient refund. No accepted publication from the original invocation or later StateEvent
adoption can exist. Other historical publications at the same checkpoint may be excluded only
when their exact artifact ID was retired by a durably consumed rejected-output decision; never
exclude the current invocation, an unconsumed rejection or an ancestor closure. Retain all original
artifacts/publication receipts and failure facts.

A proof of stopped/unaccepted execution is not a workspace-ready proof. Final proposal compares
the original capture-start before inventory against the complete stable current inventory,
authorizes every mutation with frozen permissions/denied paths, permits only existing explicit
cache paths, and requires every noncache mutation to be present in the complete legal dirty
capture or exact inherited continuation paths. Inventory is not Git-ignore filtered. Existing
HEAD/index/branch, text-body, secret, protected-path, no-follow, mode and byte gates remain.
Recollect original facts and recheck complete inventory after capture and before publication.
The Plan model also performs pure noncache coverage and capture-after body versus inventory
kind/SHA/mode/size/deletion checks. It reads no current filesystem during historical decoding;
the service separately performs current workspace authorization and freshness checks.

Use ordinary SOURCE_REBIND: target differs from previous execution base. Engineering principal
approves exact immutable plan/facts/captures, optionally PAUSE; SQL consumption produces an exact
paused successor and charges one ordinary work attempt atomically. Explicit latest-bound RESUME
rechecks source/inventory/frozen identity and releases only that successor. New Run/Context/claim
must pass normal production gates and independent QA/Review.

## Validation matrix

| Case | Required behavior |
| --- | --- |
| Exact completed stop + FAILED WORK_INTERRUPTED/no artifact + legal full draft | Full baseline proposal; ordinary work reservation; exact PAUSE/RESUME |
| Ordinary accepted progress or successful result | Existing adoption path, no overwrite |
| FAILED result without real capture stop | Reject; outcome is not stop proof |
| Timeout/provider cause or absent output | Existing truthful routes only |
| Foreign scope/request/lease/source, missing claim/ledger, process live/unknown | Reject before workspace authorization |
| Original/later accepted publication or StateEvent adoption | Reject completed-output capability |
| Different historical work, exact consumed rejected-output ID | Retain raw receipt; omit only that ID from the current publication gate |
| Ignored noncache mutation outside draft/inherited set or allowlist | Reject complete proposal |
| Secret, symlink, staged index, oversized body or inventory drift | Reject; preserve files/history |
| Exhausted frozen work budget | No successor, no refund |
| Old wire with no completed fields | Identical canonical dumps/digests and normal routes |
| Exact execute/release replay | No duplicate attempt, binding or role execution |

Good: preserve unknown result, capture full legal source, approve a new target, pause and explicitly
release a fresh ordinary-work Coder. Base: existing timeout/transient/uninvoked/legacy behavior and
historical digests remain. Bad: invent a success artifact, call completed a timeout/provider fault,
drop ignored files, infer cache cause from a generic failure, or accept stopped proof as READY.

## Existing data, rollout and rollback

Do not change historical run7 outcome/start/stop, reset Task, delete ledger, or directly update
queue rows. Exact cache maintenance is separately authorized/audited by root and cannot grant
execution permission. At a controlled idle load boundary, public PROPOSE prepares a new complete
plan; inspect and approve its exact digest with PAUSE, then RESUME latest exact binding. A terminal
Task remains ineligible. After consumption retain compatible readers and decisions; rollback
must not resurrect old work or change ordinary work accounting.
