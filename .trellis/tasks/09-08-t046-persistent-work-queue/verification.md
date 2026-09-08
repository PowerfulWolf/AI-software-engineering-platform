# Verification

## Outcome

T046 is implemented. The organization now has a single-node MySQL Run queue, a bounded
Planner-owned Dispatcher tick and an owner-fenced Lease lifecycle. A queue item represents one
Coder/QA/Reviewer Run; Task delivery state remains a separate aggregate.

## Executable evidence

- `tests/work_queue`: 10 passed against the real `ase-mysql` MySQL 8/InnoDB container.
- Queue/Host/production backend composition: 21 passed against real MySQL.
- Schema and dispatcher unit contracts: 47 passed without MySQL.
- Projection/team-view regression after removing the synthetic orchestrator member: 8 passed against
  real MySQL.
- Existing long recovery suite: 3 passed in 435.14 seconds against real Git/MySQL.
- Remaining full suite before the projection repair: 938 passed and one team-view failure; the exact
  failure was repaired and its focused projection/team-view regression passed.
- Ruff: all checks passed and 543 files were already formatted.
- Strict Mypy: 299 source files passed.
- Offline build: source distribution and wheel built successfully under `/tmp/ase-dist-t046`.
- `git diff --check`: passed.

## Bugs caught during verification

1. Waiting/expired retries originally reused deterministic Assignment/Lease IDs. `dispatch_sequence`
   now increments on every re-dispatch and participates in both IDs.
2. Dispatcher documentation promised expiry recovery while `tick()` only claimed new work. Every
   tick now reclaims expired Leases before scanning and returns the reclaimed WorkItem IDs.
3. Queue lifecycle mutations used inconsistent row-lock order with the reaper. Every mutation now
   acquires the single-node authority lock before WorkItem/claim rows.
4. `OrganizationTeamHost` test isolation stubbed only the Task repository after queue construction was
   added. The host test now isolates both MySQL components.
5. Projection attempted to convert the legacy control role `orchestrator` into an OrganizationRole,
   causing live reads to block delivery. Control Runs remain in timelines but no longer create a fake
   organization member.
6. `preferred_agent_id` was initially placed under RunDemand rather than WorkItem in the JSON Schema.
   Contract tests now prove affinity belongs only to the schedulable WorkItem.

## Honest remaining boundary

The current `ase request` path still executes a whole Task synchronously. T046 provides the durable
queue authority and Team Host composition seam; a later task must wire per-role Workers to consume
claims and drive the existing TaskOrchestrator one role at a time. No fake background CLI was added.
