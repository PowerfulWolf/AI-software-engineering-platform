# Design

## Reproduction
The real Playwright fixture keeps `role_queue` and heartbeat fixed while changing only
`item.execution`. `task-overview` updates, but `task-activity` is reused because its
signature omits the execution object that `roleExecutionActivity(item)` consumes.
The screenshot shows “保存结果” above a stale “准备知识” activity.

## Contract
`viewBlock(activity, "task-activity", sources)` must include the current execution
facts used to render the activity. This affects read-side invalidation only. Existing
keyed reconciliation continues to retain unrelated document and chapter nodes.
The Task waiting badge uses an exact presentation selector/class with the same red
semantic as the Requirement waiting state; unknown and neutral states stay distinct.

## Validation matrix
| Input | Expected |
| --- | --- |
| Same queue, changed execution phase | Both current explanations update |
| Timestamp-only or identical facts | Existing document identity/open state remains |
| Running phase | Blue, never green before acceptance |
| Waiting phase | Red in Task and Requirement |
| Passed delivery gate | Green only from its existing passed fact |
| Narrow viewport | Full readable content without horizontal overflow |

## Boundaries
No schema, API, source revision, worktree, budget, durable event, approval or role verdict
changes. Local browser fixtures perform zero mutating API requests.
