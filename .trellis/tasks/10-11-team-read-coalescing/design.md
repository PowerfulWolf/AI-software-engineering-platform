# Design and contracts

`create_console_app` owns `_TeamSnapshotReads`. Its private lock protects one flight identified
by exact `project_id`, original worker and at most two additional waiter slots. No application
cache exists. The original private `_team_snapshot(..., LockType)` entry remains compatible with
its existing direct baseline-lifetime test; the application supplies the new coordinator.

The flight owns one master asyncio Task which awaits the threadpool worker. Each consumer uses
`asyncio.shield` so cancellation detaches that consumer's callback rather than canceling the
master. A joined consumer returns its slot in `finally`; cancellation of the original consumer
does not convert its reserved ownership into extra slots. The master result is a frozen rendered
body/status/media-type value. Each consumer creates an independent Response over the same bytes.

The worker marks entry under the same lock and retires its exact flight in `finally` only after
read/wire/render. This retirement happens before async notification, so a completed result cannot
be joined. Identity comparisons prevent late startup/cleanup from clearing a successor. An
unstarted canceled or unschedulable flight is marked retired; any late worker invocation must
skip reading. Cancellation after entry leaves ownership with the worker.

Safe read errors retain `503 TEAM_UNAVAILABLE`; unexpected read/serialization/scheduling errors
become the ordinary safe 500 body. No future receives the original exception or traceback. Host
checks still run before admission, and normal middleware adds request-local security headers.

Memory ownership is one active read's peak plus one rendered bytes body and at most three
consumer references. Neither response byte size nor total process/network memory has a fixed
bound. Completed HTTP/network buffering from older generations is outside this coordinator.

Validation: deterministic held-worker ASGI tests first; private coordinator lifetime tests for
cancel/timeout-before-start, canceled-slot reuse, completion races, identity cleanup, weak scope
release and safe error sharing. Retain public transport and baseline-lifetime regressions,
preparation-progress availability. Run only relevant non-MySQL tests and scoped Ruff/mypy.
