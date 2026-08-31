# T004 — Pure Task State-Machine Guard and Reducer

## Goal

Turn the documented v0.1 Task lifecycle into a small, deterministic Python module. The module must be the only place that decides whether a status transition is legal and must emit replayable `StateEvent` values without performing I/O.

## Requirements

- Define the canonical legal transition graph from `docs/state-machine.md`.
- Reject transitions from terminal states and all graph-skipping transitions.
- Build an orchestrator-owned `StateEvent` with the supplied reason, source revision, artifact IDs, event ID, and timestamp.
- Reduce a valid event into a new immutable `Task` snapshot without mutating the original.
- Validate Task ID, source Task status, actor, and monotonic event timestamp at the pure boundary.
- Keep persistence, Git, artifact lookup, retries, and Agent execution outside this module.

## Acceptance Criteria

- [x] Every documented legal edge is accepted.
- [x] Every undocumented edge, self-transition, and terminal-state transition is rejected with a typed error.
- [x] A generated event validates against `StateEvent` and `state-event.schema.json`.
- [x] Applying an event changes only `status` and `updated_at`; the original Task remains unchanged.
- [x] Events for another Task, stale `from_status`, non-orchestrator actor, or an older timestamp are rejected.
- [x] No repository, filesystem, subprocess, model SDK, or network behavior is introduced.
- [x] Ruff, strict mypy, pytest, and JSON contract tests pass.

## Out of Scope

- Artifact content checks such as QA PASS or Review APPROVE; those remain Orchestrator/ArtifactStore guards.
- Attempt counting, retry routing, Git worktrees, Context Builder, Agent adapters, and persistence.
- Dynamic roles, parallel execution, DAGs, queues, PostgreSQL, vector databases, or production deployment.

## Rollback

Revert the single T004 commit. The module has no migration or external side effect.
