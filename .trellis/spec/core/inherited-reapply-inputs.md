# Complete inputs across chained recovery

## 1. Scope / trigger
Recovering a terminal Coder whose source Task was itself created by an approved recovery.
A latest worktree capture is current implementation data; it does not supersede a complete
historical coder_reapply input merely because some files have already been adapted.

## 2. Signatures and contract

Implementation files: `recovery/models.py`, `recovery/inherited_input.py`,
`recovery/context.py`, `recovery/entry.py`, `recovery/current.py`,
`recovery/inherited_queue.py`, `manager/production_backend.py` and
`manager/production_delivery.py`.

```python
reconstruct_inherited_reapply_inputs(
    records: InheritedInputRecords, source: RecoverySource, task: Task,
) -> tuple[InheritedReapplyInput, ...] | None
read_inherited_reapply_inputs(
    config: ProductionConfig, environment: Mapping[str, str],
    source: RecoverySource, task: Task,
) -> tuple[InheritedReapplyInput, ...] | None
require_plan_inherited_inputs(
    config: ProductionConfig, environment: Mapping[str, str], plan: RecoveryPlan,
) -> None
validate_inherited_reapply_context(plan: RecoveryPlan, context: ContextBundle) -> None
read_inherited_invocation_queue(
    dsn: str, start: DeliveryInvocationStart, dispatch: RecoveryDispatchRecord,
    task: Task, scope: RecoveryScope, project_id: ProjectId,
) -> None
```

The public `POST /api/v1/operations` `CONTINUE_DELIVERY` intent is unchanged. It accepts
`approved_scope_sha256` or `approved_plan_sha256` separately, never an inheritance payload.
Approval facts list the preserved input count/bytes, with exact origins/digests in technical
facts. An inherited input is not a request to edit its origin files or broaden permissions.

`RecoveryPlan.inherited_reapply_inputs` is an optional typed tuple. Each input freezes the
origin approved Plan, origin successor Task and authentic Context identity, original URI,
full UTF-8 patch body, byte length and body SHA-256. None is omitted from all canonical wire
forms to retain historical Plan/authorization identities. New Plans bind the complete tuple
to their exact digest and execution approval.

Trusted recovery composition reconstructs the tuple from immutable Task metadata, approved
Plan, authorization, sealed Task, dispatch, seed, invocation and Context facts. Context text,
arbitrary URI syntax, model statements, an expired lease or a matching body alone confer no
authority. Each ancestor must remain in the same Team/Repository/Requirement and preserve
exact source relationships. New proposals also inspect real ancestors of old Plans that did
not have this optional field. Absence is read compatibility, not permission to drop input.

## 3. Context and validation
- Keep the new capture and every prior complete input separate; never manufacture a merged
  capture or edit real drafts as a maintainer. Both strict seed and coder_reapply successors
  preserve genuine inherited required inputs.
- Deliver `recovery.inherited_patch.<origin-plan-sha>` with exact original URI/body,
  required=True, Coder-only and truncated=False. Current `recovery.patch` retains its identity.
  Explain current draft precedence without interpreting that precedence as completed scope.
- Reconstruct and compare at proposal/current-facts validation. Initial entry, seed/reentry,
  later Coder Context composition and final provider admission enforce the same complete tuple.
  Reject omitted, added, truncated, renamed or altered inherited sections before provider start.
- Deterministically deduplicate by origin Plan plus body SHA. Different origins remain distinct
  even for identical bytes. Bound ancestry/unique inputs to eight, refuse cycles/ambiguity and
  enforce the existing MAX_CAPTURE_BYTES aggregate bound plus the final serialized-input budget.
  Capacity failure preserves all inputs and never silently drops or truncates a required body.
- Patches are unaccepted implementation input. They grant no additional path, state, budget,
  candidate or verdict authority. QA/Reviewer never inherit these source patches.

## 4. Validation matrix
| Case | Expected result |
| --- | --- |
| No ancestry; historical None field | no inherited input, unchanged wire/digest |
| Full old patch includes file missing in newer partial draft | full old and new inputs retained |
| Third generation or Host rebuild | same transitive inputs exactly once per origin |
| Strict seed successor of a reapply source | required historical input retained |
| Missing/tampered Plan, approval, Task, dispatch, seed, invocation or Context | reject before provider |
| Wrong URI/body/hash/length, truncation or injected source | reject before provider |
| Cross-scope/cycle/too many inputs/aggregate or Context overflow | reject, preserve source scene |
| Independent QA/Review | candidate-bound verification, no historical patch input |

## 5. Good / base / bad
Good: original full patch has two features; a second Task adapted only the first before failing.
The third Task receives the current draft and the entire original patch under different sealed
source identities. Base: ordinary first-generation recovery remains unchanged. Bad: deciding
that current dirty files or accepted progress prove every old patch hunk was implemented.

## 6. Required verification
Focused commands include `pytest tests/recovery/test_inherited_reapply_inputs.py` and
`pytest tests/recovery/test_inherited_reapply_entry.py` from the maintenance checkout with
`PYTHONPATH=src`. The second requires the guarded isolated MySQL environment; never derive
its DSN from production configuration. Synchronize every static Schema embedding RecoveryPlan.

Focused model/Schema/lineage/tamper/capacity tests plus a public proposal → exact approval →
claimed execution fixture with real Git/stores and independently identified isolated MySQL
where needed. Verify the new Context contains the original unadapted fragment and current
patch, old persistent facts remain unchanged, and candidate still requires independent QA/Review.
Fixture DONE cannot establish a live Requirement's acceptance.

## 7. Wrong vs correct

Wrong: `new_plan.capture.patch` is the newest patch, therefore it replaces every historical
recovery input. Correct: reconstruct `inherited_reapply_inputs` from approved immutable
ancestry, bind the complete tuple to the new Plan, and validate it independently of the new
capture at every Coder call. A valid Context digest alone does not prove that a historical
invocation had a real claim: verify its exact admission, queue step and historical claim.

The SQL proof runs SELECTs in a repeatable-read read-only consistent snapshot over
`work_queue_admissions`, `work_queue_steps`, `work_queue_execution_baselines`,
`work_queue_claims` and the unique original `CLAIMED` event in `work_queue_events`.
Validate payload hashes and raw indices, exact Task/Repository/allocation, role/attempt/
checkpoint/source boundary, original lease identity and the explicit registry Project ID.
Honor complete original claim snapshots where present; historical renewable expiry is not a
new stop proof. Existing immutable execution-baseline overlays must bind the same source epoch.
Apply this to both the original recovery main invocation and the later failed main invocation.
Knowledge-only preparation counters do not establish the first main attempt number.
Never instantiate a mutable queue or initialize SQL schema from this reader.
Malformed original claim payloads and known store/database connection or SELECT failures must
become safe typed recovery refusals. At final admission they must produce a durable failed
outcome with zero provider calls; do not expose database/vendor exception text or leave a
start-only invocation. Ownership/wait control exceptions retain their existing semantics.

## 8. Stored data and rollback
No SQL migration or direct production record edits. Keep old failures, accepted progress,
worktrees, full patches and budget accounting. At idle deploy the fix through controlled service
restart, then prepare a new exact Plan and approve it separately from any scope supplement.
Before dispatch compare complete current facts again. Rollback while idle must retain readers
for published inherited-input records; do not revert into treating new records as absent input.
