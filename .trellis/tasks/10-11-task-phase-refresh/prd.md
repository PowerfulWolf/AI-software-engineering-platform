# Task phase refresh consistency

## Goal
Task details must show the same current execution phase in their summary and activity,
even when the role queue and heartbeat have not changed between snapshots. Delivery
waiting is red, executing is blue and passed stages are green.

## Scope
- Correct the Task activity block invalidation inputs; preserve document DOM,
  expansion, scroll and selection during incremental refresh.
- Align the precise Task waiting badge with delivery waiting colors; do not change
  unknown or historical completion facts.
- Keep all durable records, role verdicts and write/approval gates unchanged.

## Acceptance
- Same queue/heartbeat with knowledge preparation → role execution → result saving
  updates both Task explanations, without showing a completed delivery.
- Requirement and Task agree on Chinese phase text and semantic colors.
- An expanded document remains the same open DOM node across phase changes.
- Real browser checks at 1440 and 390 pixels have no horizontal overflow.
- Only targeted DOM/browser regression checks run; no production operation or full suite.

## Existing data and rollback
No database or historical record changes are needed. The active K1 Operation continues
unchanged. Deploy when the entire Operation is safely idle, using controlled restart,
then refresh its existing details. Revert this presentation commit to roll back; retain
all checkpoints, approvals and execution records.
