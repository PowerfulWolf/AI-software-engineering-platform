# Bounded sharing of an executing Team read

Goal: reduce simultaneous same-Project `GET /api/v1/team` busy responses by letting at most
two additional HTTP callers observe the same currently executing read. This addresses proven
admission contention; it makes no claim that read cost, a hang or a memory leak has been fixed.

Acceptance:

1. One original caller plus two same-key callers share one snapshot, wire conversion and rendered
   byte body. Each receives a separate mutable Response with the original `as_of`.
2. A third additional caller, a different Project or `None` versus an explicit Project receives
   immediate fixed `503 TEAM_READ_IN_PROGRESS`, without queuing a second reader.
3. Actual worker ownership includes snapshot, wire conversion and rendering. Caller cancellation
   or timeout cannot cancel that worker; joined slots release exactly once.
4. Worker completion immediately retires the flight. Subsequent requests perform a fresh read,
   including after success/error and while an old completion notification is still pending.
5. Canceled callers do not accumulate callbacks or retain their scopes. Published results contain
   only immutable rendered bytes and status/media type, never snapshots or exception tracebacks.
6. Host/origin/security checks and other Console/preparation endpoints remain available.

Allowlist: `src/ai_software_engineer/web_console/transport.py`,
`tests/web_console/test_team_snapshot_coalescing.py`, necessary serialization assertions in
`tests/web_console/test_transport.py`, `.trellis/spec/core/read-memory-lifecycle.md`, and this task
directory. Root additionally authorized the necessary different-Project busy assertion in
`tests/web_console/test_preparation_progress.py` after independent review found its same-key
expectation must change. No public Schema, database, sidecar, execution/approval, frontend or standalone server
change. Baseline is `8d494027bbbc3a97198dc410601fed11f5f9f91d` in an independent clone.

No deploy, restart, approval, commit, push or merge. Existing data needs no repair. Eventual loading
must wait for active execution and operations to end safely. Rollback restores the baseline
transport/spec/tests in an idle service; durable facts and authorization remain unchanged.
