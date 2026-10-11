# Minimal read-side contract

Use a read-only helper with the trusted sidecar/team/project/requirement/source
scope plus the freshly validated SQL QueuedWorkItem, RoleAssignment and TaskLease.
No Host, reconciliation, operation status, shell inspection or model diagnostics
history may establish a role phase.

Phase is optional: KNOWLEDGE_PREPARATION, ROLE_EXECUTION or FINALIZING. Its absence
retains neutral ROLE_WORK_CLAIMED / "已领取当前工作, 细分执行进度暂未上报".
The queue reader invokes the helper only for
RUNNING with a current valid lease. Frozen claim item status remains LEASED;
heartbeat lease expiry may be newer than the frozen receipt. Compare immutable
claim identity fields and acquired_at separately, and use current SQL liveness.

Resolve source_revision from the exact hashed QueuedRoleStep and the boundary
before its current CLAIMED event. Coder's approved source can differ from both
Task.base_ref and historical candidate SHA. Existing queue events have neither a
QueueEvent domain model nor a historical sha256 column; validate their full typed
row/payload and exact lease/item/dispatch/time identity instead of inventing one.
Match the selected pre-claim EXECUTION_BASELINE_REBOUND detail to independently
hashed BaselineQueueConsumption/plan/binding records. Load at most 100 consumed
baseline records and reuse the pure resolve_step_overlays algorithm. Unsupported
inherited epochs return no fine phase. The original mutation service still owns
inherited-baseline authorization and every write.

Read main role records by exact work item key under state/invocations. A matching
current start takes priority over knowledge; a matching outcome means FINALIZING.
For knowledge, use the shared scope-to-lane hash helper under knowledge/runs/
invocations. Only the native Requirement scope and explicitly supported legacy
Task-id scope are eligible. Validate every bounded record before selecting a
matching current intent, limiting each lane to 512 intent files before payload
reads. A finished knowledge outcome still precedes the main role; its embedded
execution records must equal independently loaded content-addressed receipts.
Missing old stores/receipts return None; corrupt or unsafe stores raise, preserving
the reader's existing fail-closed behavior.

_task_execution derives Chinese text and reason_code from the optional queue
phase each time it recomputes. _request_with_current_work naturally copies that
execution. The browser uses a shared running presentation for Task, Requirement
role dispatch and activity without replacing it with generic executing text.

Validation covers current claim, changed lease/dispatch/attempt/source/scope,
renewed expiry, main invocation precedence, valid outcome finalizing, legacy dump
hash preservation, no writes, unsafe files and Python/DOM Schema parity.
