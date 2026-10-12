# Maintenance completion

## Scope and signatures
Local trusted engineering channel, independent of Requirement/Run recovery and verdicts.
`prepare_maintenance_completion(environment) -> MaintenanceCompletionPlan`
`complete_maintenance(environment, plan_sha256, confirm_restore_normal) -> MaintenanceCompletionReceipt`
`admit_completed_maintenance(environment) -> None` runs before first normal TeamHost composition.

## Contracts
Current successor must have an exact READY instance/SHUTDOWN request/READY result, aware ordered
publication times and actual current kernel PID absence. It must differ from the faulted predecessor.
Keep console-inspection.json and the entire original archive. Append immutable private plan,
completion receipt and first-normal-admission; no caller-provided queue/liveness/approval facts.
Plan records include digest-bound original marker/retirement receipt, current lifecycle, selected
config and Team identity, complete queue inventory digest and safe counts/IDs.

Use existing read-only Team discovery and Operation store. SQL uses a consistent READ ONLY snapshot,
no PersistentWorkQueue/TeamHost constructor, schema initialization, reconciliation or UPDATE.
Inspect all rows in the selected database conservatively: database-shared runnable work also blocks
completion; never silently discard a row because its Project identity is unknown. Validate typed row
identities, statuses, assignment/lease binding and complete inventory. Every ACTIVE claim blocks even
when expired. READY/RETRY_SCHEDULED (including future retries)/LEASED/RUNNING and QUEUED/RUNNING
Operations block; WAITING_HUMAN/WAITING_DEPENDENCY/CLOSED and terminal Operations stay unchanged.

Prepare/complete share service replacement lock. Complete requires exact digest and explicit local
confirmation, fresh identical lifecycle/config/queue; stale plans require prepare again. Durable receipt
publication is append-only and retry idempotent. Before the first normal writer is composed, fresh
idle queue/config/current stopped successor are required again, followed by a durable admission.
Admission means permission to construct normal services, not successful startup or any demand approval.
Later normal restarts retain this engineering decision and ordinary lifecycle/dispatch contracts.
External writers against the same DB are outside the local service lock: operators must quiesce them;
fresh checks detect observed drift but do not claim a distributed DB fence.

## Validation matrix / test points
Good: stopped inspection, intact full archive, idle complete queue -> exact local confirmation ->
receipt -> fresh normal admission; marker/archive and old UNKNOWN/REFUSED byte-identical.
Base: waiting human/dependency preserved; no automatic Requirement continuation.
Bad: live/recycled PID, foreign/stale lifecycle, wrong digest/no confirmation, changed config/queue,
ACTIVE expired claim, future retry, partial SQL schema/invalid JSON/unknown status, damaged archive,
symlink/unsafe permission -> refuse before normal writers. Partial publication retry only same plan.
Schemas generated from models and parity tested. Exercise CLI, script entry and production gate.

## Existing data and rollback
No Task/Operation/approval/lease or draft rewrite. K1 stays waiting. Do not delete the maintenance
marker. Before completion keep inspection. After completion, explicit inspection still forces readonly;
rollback must retain compatible archive/receipt gate. No old outcome or shutdown proof is backfilled.

## Executable entry and records
`ase-console-service.sh prepare-maintenance-completion` uses the existing controlled `stop`, then
`ase-console-maintenance.py prepare-completion`. Failure tries only explicit inspection `start`;
it never force-kills or starts a normal service. Success leaves the service stopped for review.
`ase-console-service.sh complete-maintenance PLAN_SHA256 --confirm-restore-normal` invokes
`ase-console-maintenance.py complete --plan ... --confirm-restore-normal`, then ordinary `start`.
Invalid arguments refuse before stopping. `ase-console-lifecycle.py admit-start` runs under the
inherited replacement lock after runtime.env loading and before launching the first normal child.
Direct production_console_app also checks admission outside the setup fallback before TeamHost.

Private files (0600, owner/nlink1/nofollow, full hash validation):
- console-maintenance-completions/<plan_sha256>/plan.json: marker_sha256, retirement_plan_sha256,
  retirement_receipt_sha256, config_sha256, principal_uid, instance/request/result, inventory.
- same directory receipt.json: plan_sha256, marker_sha256, principal_uid,
  supersedes_receipt_sha256, successor_mode=normal, historical_execution_outcome=UNKNOWN,
  requirement_action=NONE.
- console-maintenance-completed.json: immutable first receipt anchor, never overwritten.
- console-maintenance-admitted.json: receipt_sha256, plan_sha256, inventory_sha256,
  principal_uid, requirement_action=NONE. This is the first-normal writer admission decision.

Before admission, drift permits a newly prepared plan and explicitly confirmed superseding receipt.
Verify a single complete chain from the immutable anchor; branches/orphans/cycles/damaged records
refuse. Partial first receipt publication retries the same existing receipt, without fabricating
its time. After normal admission, no additional completion plan is accepted. Original faults remain
unknown. MaintenanceQueueInventory includes full digest, team_manifest_sha256, queue_scope,
operation_count, work_item_count, claim_count, waiting_work_item_count, blocked_operation_ids,
blocked_work_item_ids, active_lease_ids. SQL identity/payload/status/claim integrity must all match.

Tests: test_maintenance_completion.py, test_maintenance_queue.py,
test_maintenance_completion_script.py, test_inspection_console.py,
browser/inspection-console.test.cjs. Static console-maintenance-{completion-plan,completion-receipt,admission}
Schemas are regenerated by scripts/generate-fault-retirement-schemas.py and parity tested.
