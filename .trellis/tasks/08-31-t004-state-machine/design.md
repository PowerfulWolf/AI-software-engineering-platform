# T004 Technical Design

## Public Seams

| Seam | Input | Output | Failure behavior |
|---|---|---|---|
| `validate_transition` | current `Task`, target `TaskStatus` | `None` | `IllegalTransition` or `TerminalTask` |
| `build_event` | current Task + transition metadata | immutable `StateEvent` | typed guard error or Pydantic validation error |
| `apply_event` | current `Task`, typed `StateEvent` | new immutable `Task` | `TaskMismatch`, `IllegalTransition`, `StaleEvent` |

The functions are pure: they read value objects only and do not open a repository or invoke an Agent.

## Canonical Graph

```text
NEW -> PLANNING -> IMPLEMENTING -> QA -> REVIEW -> DONE
                                  ├-> IMPLEMENTING (QA retry)
                                  └-> BLOCKED (QA terminal failure)
REVIEW -> IMPLEMENTING (review retry)
REVIEW -> BLOCKED (review terminal failure)
any non-terminal -> FAILED (platform invariant failure)
```

Self-transitions are not legal. `DONE`, `BLOCKED`, and `FAILED` are terminal.

## Event Construction

`build_event` first calls `validate_transition`, then constructs `StateEvent` with `actor=AgentRole.ORCHESTRATOR` and the caller-provided event ID, reason, source revision, artifact IDs, and aware timestamp. Artifact semantics are intentionally deferred to later guards.

## Reduction

`apply_event` checks event/task identity, `event.from_status == task.status`, the legal graph edge, and `event.occurred_at >= task.updated_at`. It returns `task.model_copy(update={"status": event.to_status, "updated_at": event.occurred_at})`. Repository revision changes remain the responsibility of `TaskRepository.append_event`.

## Error Matrix

| Condition | Error |
|---|---|
| Unknown graph edge or self-transition | `IllegalTransition` |
| Current status is terminal | `TerminalTask` |
| Event belongs to another Task | `TaskMismatch` |
| Event starts from a stale status | `StaleEvent` |
| Event timestamp predates Task snapshot | `StaleEvent` |

