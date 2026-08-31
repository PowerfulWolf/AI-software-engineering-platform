# T003 Technical Design

## Public Seams

| Seam | Input | Output | Failure behavior |
|---|---|---|---|
| `TaskRepository.create` | typed `Task` | persisted revision 0 | duplicate ID → `TaskAlreadyExists` |
| `TaskRepository.get` | `TaskId` | latest typed `Task` snapshot | missing/corrupt row → typed repository error |
| `TaskRepository.append_event` | typed `StateEvent` | no return; atomic state/event commit | stale status, conflict, or SQL failure rolls back |
| `TaskRepository.list_events` | `TaskId` | ordered immutable tuple of `StateEvent` | missing/corrupt row → typed repository error |
| `TaskRepository.current_revision` | `TaskId` | non-negative integer | missing row → `TaskNotFound` |

## Relational Layout

```text
tasks
├── id TEXT PRIMARY KEY
├── payload_json TEXT NOT NULL
├── status TEXT NOT NULL
├── revision INTEGER NOT NULL CHECK (revision >= 0)
├── created_at TEXT NOT NULL
└── updated_at TEXT NOT NULL

state_events
├── event_id TEXT PRIMARY KEY
├── task_id TEXT NOT NULL REFERENCES tasks(id)
├── revision INTEGER NOT NULL
├── payload_json TEXT NOT NULL
└── UNIQUE(task_id, revision)
```

The JSON snapshot is the source of truth for typed Task fields. Indexed status/timestamps/revision columns make recovery queries cheap while remaining derivable from the snapshot.

## Transaction Algorithm

```text
BEGIN IMMEDIATE
  read event_id
  if existing payload == incoming payload: COMMIT (idempotent no-op)
  if existing payload differs: ROLLBACK (IdempotencyConflict)
  read Task snapshot and current revision
  require task.status == event.from_status
  derive next Task snapshot with event.to_status and event.occurred_at
  insert event at revision + 1
  update Task snapshot and revision + 1
COMMIT
```

T003 deliberately does not decide whether `from_status → to_status` is a legal state-machine edge; T004 will perform that pure guard before calling this port.

## Idempotency and Recovery

- `event_id` is globally unique in the database.
- Exact replay returns successfully without changing the Task or revision.
- Same ID with any changed field is a hard conflict; callers must not silently overwrite audit history.
- A reopened repository reads the latest snapshot and ordered events from disk; no in-memory cache is required.
- Corrupted JSON is detected at the repository boundary and never returned as a partially typed object.

## Dependency Decision

SQLite uses Python's standard-library `sqlite3`; it removes a v0.1 deployment dependency while providing transactional writes, foreign keys, WAL, and durable restart behavior.

## Test Points

- Positive Task/Event round-trip and close/reopen recovery.
- Atomic append updates status, timestamp, event list, and revision together.
- Exact replay, conflicting replay, stale status, duplicate Task, unknown Task, and corruption paths.
- Foreign-key and WAL pragmas are asserted on the real SQLite file.
