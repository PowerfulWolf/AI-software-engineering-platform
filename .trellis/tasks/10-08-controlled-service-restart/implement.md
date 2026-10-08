# Implementation and handoff

## Delivered behavior

- Console admission, HTTP mutation leases, current index tick and owned process observation participate
  in one explicit READY/REFUSED coordinator. The claimed complete Operation retains its normal real
  role claims and terminal persistence; queued Operations remain queued.
- Native/structured/tool/candidate-source/verification/UI/proxy/chooser runners use owned isolated
  sessions. Verified process group absence, actual pipe EOF and stop-record persistence are required;
  uncertain observations survive a dead dispatcher.
- Controlled Uvicorn intercepts TERM/INT, binds its port and saves service identity before starting
  workers. Repeated signals cannot force-exit. Cancellation of an HTTP caller does not discard actual
  sync-write ownership. Known terminal/index/process persistence failures cannot be cleared by RESUME.
- A private bounded owner/mode/nlink/no-follow typed v1 instance/request/result handshake uses atomic
  fsync writes. The script checks exact nonce/PID/request/state/time, then actual process exit.
- CLI and configuration apply replacements share an inherited OS flock. REFUSED preserves original
  service/PID/supervisor. Start also verifies a fresh RUNNING instance, not only executable liveness.
- New lifecycle and configuration-apply summaries are Chinese; legacy English apply records remain
  readable. No model stop is manufactured as provider error, timeout, refund or verdict.

## Root cause and independent checks

Original red regressions were actually executed: Console close returned while execute remained active,
and new submit still succeeded (2 failing tests); Index close returned while a real tick was running
(1 failing test). This established missing admission/completion contracts rather than a model verdict.

Review was divided among agents across files they did not implement, with root reviewing core and final
integration. Fixed review findings: absent PID cannot stop a live supervisor; READY requires matching
instance state and timestamps; port bind failure starts no delivery worker; chooser uses HTTP ownership;
output collector failure is not EOF; known index/stop failures latch refusal; RESUME publishes proof
before reopening dispatcher/write admission and rejects background restart failure.

Knowledge is recorded in `.trellis/spec/core/controlled-service-restart.md` and recovery-thinking guide.
There is no `src/templates/` tree in this repository to synchronize. Static lifecycle schemas match
their Python boundary and have a focused parity test.

## Existing-data treatment

No production request, Task, Operation, queue, lease, approval, worktree or database was mutated. K1
and its old UNKNOWN Run remain paused and unchanged. This change prevents future ordinary restart
loss, not the reconstruction of absent historic outcomes. No SQL migration is required.

Old in-memory Host instances do not gain the handshake by updating disk code. The one-time verified
maintenance upgrade and normal commands are in `docs/operations/controlled-service-restart.md`.
Unproven dead PID and missing legacy handshake are refused, never retroactively labeled READY.

## Validation / limits / rollback

Only focused incremental tests and changed-file lint/type checks were used; no full suite or real model
calls. Verification commands and final counts are recorded in `verification.md`.

Drain is bounded, not forced cancellation. Crashes/OS kills/outside-Host CLI and arbitrary escaped
external execution remain separate recovery boundaries. Unknown owned group or pipe stop is refused.
Rollback first completes controlled stop, then reverts code and syncs dependency; never interrupt active
work or rewrite original Run/Task records in order to roll back.
