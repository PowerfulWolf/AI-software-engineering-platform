# T003 — SQLite Task Repository and State Event Log

## Goal

Persist typed Tasks and their state transitions in a small, restart-safe SQLite repository so the Orchestrator can recover from the event stream without trusting in-memory state.

## Requirements

- Add a typed `StateEvent` model and canonical `state-event.schema.json`.
- Store validated Task snapshots as JSON and maintain a monotonically increasing per-Task revision.
- Append state events and update the Task snapshot in one SQLite transaction.
- Make event append idempotent by `event_id` and exact event payload.
- Reject event ID reuse with a different payload, stale `from_status`, unknown Tasks, and corrupted stored JSON.
- Enable SQLite foreign keys and WAL mode for the single-machine v0.1 runtime.
- Expose a `TaskRepository` Protocol and a concrete `SqliteTaskRepository`; keep domain models independent of SQLite.
- Preserve the v0.1 boundary: no state-machine legality rules, ArtifactStore, Git, Agent adapter, or orchestration loop yet.

## Acceptance Criteria

- [x] Valid StateEvent examples pass Pydantic and `state-event.schema.json`.
- [x] Task create/get round-trips through a fresh repository process.
- [x] Appending an event atomically updates the Task status, updated timestamp, event list, and revision.
- [x] Replaying the exact same `event_id` and payload is a no-op.
- [x] Reusing an `event_id` with a different payload is rejected without mutation.
- [x] A stale `from_status` is rejected and leaves Task/event state unchanged.
- [x] Duplicate Task IDs and unknown Task IDs fail with typed repository errors.
- [x] SQLite foreign keys and WAL mode are enabled; persistence tests pass after close/reopen.
- [x] Ruff, strict mypy, pytest, lock, and build checks pass.

## Out of Scope

- Checking whether a transition is legal; T004 owns the state-machine reducer/guard.
- Artifact body files, SHA computation, or cross-artifact revision checks; T005 owns ArtifactStore.
- Concurrent Task scheduling, migrations beyond idempotent bootstrap, network, and model SDKs.

## Rollback

Revert the T003 commit. The repository creates only a caller-selected SQLite file; no remote state or irreversible migration is performed.
