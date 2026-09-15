# Repair delivery recovery, stage queues, and blocked Requirement controls

## Goal

Make Requirement delivery state trustworthy and operable from intake through terminal failure.

## Requirements

- A QA environment/command error must not be routed to Coder as if it were a code defect and then fail with a no-change `GIT_CONTRACT` error.
- Manager, Product, Designer, and Planner work must appear in the corresponding Team member queues while those stages are executing.
- A blocked Requirement must support explicit close and delete operations.
- Delivery flow renders only stage-node status; operation prose such as “Manager is redelivering” must not remain in the flow section.
- “Continue delivery” must not leave a stale running message after the operation has stopped, failed, or reached a human gate.

## Acceptance Criteria

- [x] QA infrastructure/command `ERROR` selects verification retry or a human gate, not Coder remediation.
- [x] Stage activity for Manager/Product/Designer/Planner projects into the Team queues with correct status.
- [x] Blocked Requirements can be closed and deleted through guarded durable commands.
- [x] Delivery flow contains only the seven delivery nodes and their statuses.
- [x] Operation status is derived from current durable operation state and clears after terminal completion.
- [x] Targeted backend and UI regressions pass, followed by the sandbox-compatible quality suite.

## Technical Notes

This is a cross-layer change spanning recovery classification, read-side projection, Web Console commands, and browser rendering. Preserve append-only Requirement history, exact checkpoint fencing, and independent QA/Reviewer gates.
