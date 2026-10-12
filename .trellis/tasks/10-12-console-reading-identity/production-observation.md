# Production observation — 2026-10-12

Code commits: 6f256c2 (verified read identity), b3d5a15 (native-rule worker isolation).
Both were independently reviewed, fast-forwarded to main and pushed. No full test suite ran.

The supported service script completed controlled shutdown of inspection PID 62729 and started
inspection PID 57391. The existing persistent inspection marker was retained. The exact Console
manifest reports mode=inspection, delivery_ready=false, supported_actions=[] and both summary
protocols v0.1. Served app.js equals checkout bytes; SHA-256:
357b3932dc8237c7cb1f0ae7c6591c432523347dfc85b209f23fe957e4d19601.

A fresh Cua browser, with normal automatic polling enabled, displayed the real seven-member Team
and K1 Requirement. At 19:36 local time its exact detail displayed 完整正文与历史已读取; no captured
browser errors or warnings. This complements the offline normal/inspection interruption browser
checks in validation.md. It does not assert that every past production failure had the same cause.

## Existing data treatment

Read-only complete before/after observations were identical: 196 Tasks, 734 StateEvents,
97 WorkItems, 112 claims and 460 queue events; 9,287 Team/Project files; 2,610 Coder entries plus
HEAD, branch, status and both binary diffs. No SQL migration, approval, resume, dispatch or K1 write.
K1 retains Task IMPLEMENTING as its checkpoint, WorkItem WAITING_DEPENDENCY and zero active claims.
The original faulted Host archive, REFUSED and historical UNKNOWN records remain unchanged.

## Limits and rollback

The current production service supports reading only. Normal production writer/Agent delivery
was not enabled or certified by this maintenance. K1 must remain paused until separately requested;
these UI fixes do not resolve its engineering prerequisite or replace independent QA/Review.
First-load unnegotiated and explicit-404 legacy full reading behavior remains documented.
Rollback uses controlled stop and the prior compatible inspection assets, retaining the marker
and all durable history; code rollback does not authorize normal mode or K1 continuation.
