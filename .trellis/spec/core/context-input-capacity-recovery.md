# Final input capacity stops and retained draft recovery

## Scope

The final provider input check runs after the role Context has been sealed and before a
durable provider invocation start. A required-input overflow is a platform capacity stop;
it is not a provider failure, an invalid Coder report, or exhaustion of the frozen Coder
work allowance.

The read side must preserve the existing `BUDGET_EXHAUSTED` wording for historical records.
New records use an explicit `CONTEXT_CAPACITY` classification and a typed capacity receipt.
An already claimed delivery role keeps its Task checkpoint, releases its Lease and enters
engineering waiting rather than an irreversible terminal state. Unclaimed initialization or
Planner failures retain their own boundary and cannot manufacture a role claim.

## Signatures and immutable receipt

```python
FinalModelInputCapacityExceeded(*, estimated_input_tokens: int, max_input_tokens: int)
BoundModelInputBudget.check(request: AgentRequest, content: str) -> None
PreflightInvocationControl(..., context_reader: Callable[[str], ContextBundle] | None = None)
ContextCapacityReceipt.validate_integrity() -> None
```

`agents/model_input.py` checks the actual complete serialized provider input, including
wrapper, output Schema, continuation and source package. `manager/preflight_gate.py` discards
private prepared resources, verifies the real Worker claim/Task/Context and rechecks delegate
start/outcome inside its write fence before publishing. Missing `context_reader` keeps the old
custom-composition exception boundary; no invented receipt or claim.

`KnowledgeRecordStore(<repository-sidecar>/state/delivery-preflight)` publishes namespace
`context-capacity-receipts`, key `receipt_sha256`. The waiting evidence is
`context-capacity://<receipt_sha256>`. Schema: `schemas/context-capacity-receipt.schema.json`.

Receipt fields are `origin`, `task_id/task_sha256/task_intent_sha256/task_revision`,
`work_item_id/lease_id/assignment_id/claim_sha256/dispatch_sequence/checkpoint_sequence`,
`role/attempt/source_revision/context_manifest_id/context_sha256`,
`max_input_tokens/context_input_tokens/final_input_tokens/request`,
`execution_baseline_sha256/provider_started/observed_at/receipt_sha256`.

`origin=final_input` requires the actual `AgentRequest` and actual final estimate strictly
greater than the limit; request identity/source/baseline must match. The limit is the sealed
Context `max_input_tokens`; Context assembly itself retains its separate reserved-output
boundary. Section totals cannot prove final payload fits. `provider_started` only accepts
boolean false, rejecting explicit 0/null/strings. Its default is trusted producer convenience;
readers must independently prove no invocation, outcome, route or native call, not trust a flag.

`origin=legacy_terminal_context` is a current retrospective observation and forbids request
and final-input count. It never invents a missing historical Run, process stop or result.
The receipt records observation time and hashes its full body excluding its own digest.

## Recovery boundary

The receipt is a source fact, never a failed Coder route. For new Coder capacity waits, the
existing execution-baseline service validates full claim/Context/source history and prepares
an exact plan. It requires PAUSE, followed by a separate RESUME with a fresh dispatch/Lease/Run;
same Task/WorkItem, branch and frozen allowance remain. The uninvoked attempt neither advances
nor receives a transient refund.

QA/Reviewer capacity recovery remains on the same candidate and its verifier-preparation
path. It must validate original READY intent/checkpoint, complete Context and claim, current
native observation with definitive success/absence, current prerequisites and zero main-model
start/outcome/route. READY cannot be relabelled WAIT or native completion called a verdict.
Only an exact `RESUME_UNINVOKED` decision permits a fresh real claim; it grants no Coder writes
or candidate rebase.

Legacy terminal Task compatibility is separate and documented in
[terminal-context-capacity-recovery.md](terminal-context-capacity-recovery.md).
The plan must read and verify the latest approved execution-baseline binding
and its `complete_capture` (including the complete UTF-8 patch and mutation/file hashes). A
`coder_reapply` plan starts a clean worktree at the approved target base and supplies that complete
patch as required Coder input. It retains the original Team/Project/Repository, Requirement,
Task intent, native-rule epoch, permissions, acceptance chain, baseline lineage and approval
scope. It creates one authorized successor Task through the existing recovery plan and approval
service; it never resets the terminal Task, edits its events, refunds its attempt, or creates a
new Requirement.

The legacy terminal route reader remains strict: it still requires its own invocation start,
stop/outcome evidence, route history and workspace proof. A capacity receipt cannot satisfy those
fields. Conversely, the capacity recovery reader must fail closed when any provider-start evidence
is present or when the latest baseline/patch/source facts drift.

## Context identity and deduplication

Context sources are deduplicated only by their existing typed source ID/URI rules. Identical body
content under different source identities must not be silently merged: doing so changes the
Context manifest and can remove required evidence from an approved plan. Before proposing recovery,
the platform may report section URI/SHA/token accounting and the final serialized input estimate,
but it must not increase a frozen budget, truncate required material, or infer that an overflow is
caused by duplicate knowledge.

## Presentation contract

The console presents a capacity stop as “执行上下文超过平台输入容量，模型尚未调用。”
It tells the user that the platform must adjust context assembly or execution capacity before a new
exact recovery plan can be prepared. It does not show the ordinary “执行额度已用完” action or the
legacy stopped-Coder route controls unless the typed capacity receipt and latest baseline are both
verified.
The exact capacity-recovery approval shows full retained patch bytes, target code baseline,
Coder adaptation and the independent QA/Review gates. Empty clean capture cannot be shown as
“保留 0 文件”, nor can the page claim that this uninvoked Coder ran and stopped. Existing counters
remain actual historical values; section/Operation preparation success is not delivery success.

## Existing data and rollback

Existing Task, Requirement, baseline, Context, queue, invocation and Operation records remain
immutable. The first implementation is read-only compatible with those records; no SQL migration
or terminal reset is allowed. Before a new capacity receipt exists, a historical terminal Task
continues to use its existing safe blocked presentation. Rollback removes new proposal/reader/UI
code while retaining immutable receipt and plan readers once such records have been published.

## Validation matrix

| Case | Required result |
| --- | --- |
| Final serialized input exceeds available capacity before provider start | Capacity receipt, zero provider start, no automatic retry refund or verdict |
| Context section has duplicate URI or source ID | Existing typed source rejection |
| Same text under distinct required source identities | Preserve both identities and hashes; no silent deduplication |
| Capacity receipt has invocation-start/outcome/route evidence | Reject the receipt as inconsistent |
| Latest baseline or complete patch drifted | Refuse recovery and require a new exact plan |
| Valid receipt plus current baseline and complete patch | Prepare `coder_reapply` successor plan; require exact human approval and normal Coder→QA→Review gates |
