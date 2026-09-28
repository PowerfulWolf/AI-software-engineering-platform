# Design

Keep one refresh pipeline rather than aborting the shared Console/Operations reads: their error
handlers currently update global readiness, so naive cancellation can falsely mark the service down.

Separate latest explicit Project intent from the last authoritative snapshot. The refresh entry
coalesces pending targets and explicit runtime-status requests, shares an in-flight promise, and
drains a pending request immediately on completion/failure. Periodic calls never replace an explicit
target or queue another identical poll. The response publisher validates the requested Project and
checks the latest intent after asynchronous boundaries before rendering Project-specific results.
An accepted Knowledge Project snapshot is rendered immediately with a loading view before awaiting
its assets, so internal identity cannot advance while the old selector/assets remain visible. If
another selection arrives after that publication, keep this accepted scope coherent while draining
the new target; do not overwrite its progress message with the earlier read's success.

Current Project identity remains snapshot-derived; a small switching predicate controls progress
text and delivery command availability. On failure retain the intended target for normal refresh
retry, not an implicit switch back to the old Project. Never render the destination as current until
its valid snapshot arrives. Existing Knowledge context/serial fencing remains intact.

Compatibility: client-only state, no persistent data or API changes. Serve the updated asset and
reload the page; no service restart is needed if static assets are read per request. Rollback only
the new UI/test/spec changes to 321f15e, leaving all production history untouched.
