# Final input capacity stops and retained draft recovery

## Scope

The final provider input check runs after the role Context has been sealed and before a
durable provider invocation start. A required-input overflow is a platform capacity stop;
it is not a provider failure, an invalid Coder report, or exhaustion of the frozen Coder
work allowance.

The read side must preserve the existing `BUDGET_EXHAUSTED` wording for historical records.
New records use an explicit `CONTEXT_BUDGET_EXHAUSTED` classification and a typed capacity
receipt. The receipt records the exact Task/checkpoint, role and attempt, Run and Context
identities, request digest, baseline binding/source, queue claim/dispatch identity, estimated
and available input capacity, and a `provider_started=false` fact. The receipt is immutable and
must be rejected if an invocation-start, outcome, route attempt, or provider process exists for
the same Run.

## Recovery boundary

The receipt is a source fact for a new exact recovery plan; it is never made to look like a
failed Coder route. The plan must read and verify the latest approved execution-baseline binding
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

The console presents a capacity stop as “执行上下文超过平台输入容量，模型尚未调用；本次未消耗自动重试额度。”
It tells the user that the platform must adjust context assembly or execution capacity before a new
exact recovery plan can be prepared. It does not show the ordinary “执行额度已用完” action or the
legacy stopped-Coder route controls unless the typed capacity receipt and latest baseline are both
verified.

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
