# Design contract

## Components

- `web_console/shutdown.py`: `ServiceWriteGate` provides a short-lock writer admission scope,
  draining flag and idle wait; `ProjectConsole.begin_shutdown()/await_shutdown(timeout)` stop
  new submission/claim and return explicit READY/REFUSED only after durable operation finishing.
- `owned_processes.py`: `HostOwnedProcessRegistry` binds a trusted current Operation
  context to spawned process groups. Registration is released only after actual owned group stop
  verification; uncertain stop leaves a blocker. No arbitrary user-selected PID killing.
- `web_console/service_lifecycle.py`: typed instance/request/result filesystem handshake plus
  `ControlledConsoleServer` signal coordination. No agent tool or remote shutdown endpoint.
  All requests/results bind private local instance nonce and exact PID/request identity.
- `transport.py`: all HTTP mutations enter the write gate; background index worker drains the
  current tick without starting another. Read requests remain available during drain.
- Fixed local service script requests controlled shutdown, waits for exact READY and PID exit,
  then replaces service. Apply-config and direct CLI replacement share one lifecycle lock.

## Wire / persistence

Local private files: `console-service-instance.json`, `console-service-shutdown.request.json`,
`console-service-shutdown.result.json`. Typed v1 models include STARTING before listeners/workers are ready; request IDs/instance IDs use random hex;
instance carries exact PID, READY carries instance/request/PID and verified completion timestamp.
Atomic fsync replacement, bounded no-follow reads, symlink refusal and restrictive modes apply.
Handshake files are service lifecycle facts, not original Run stops, provider results or verdicts.
No SQL table change or old journal rewriting. Static lifecycle Schema must match Python models.

## Validation matrix

| Case | Contract |
|---|---|
| Current operation+native tool still active | DRAINING, wait; no READY or host exit |
| Current operation finished and all writers/workers/process groups proven done | READY, then host exit |
| Deadline, store failure or process stop uncertain | REFUSED; keep old service; no replacement |
| New write/Operation after drain begins | Chinese service-draining rejection; no durable submission |
| Existing QUEUED Operation | Remains queued until later valid service startup |
| Wrong nonce/PID/request, stale READY, symlink/foreign PID | Refuse without signals |
| Repeated signals / CLI+apply race | Idempotent current request, one replacement owner |
| Old unknown K1 | Historical facts unchanged; existing explicit rescue remains required |

Good: real owned native execution saves result/stop and releases claim before restart.
Base: idle instance stops promptly and starts one replacement.
Bad: join timeout silently returns, daemon thread abandoned, old success marker accepted, fake
provider failure, or PID disappearance used as process-tree proof.
