# Design

The earlier claim is a scheduling generation, not a second Coder attempt. A
`LEASE_EXPIRED` event proves that queue ownership was reclaimed; it does not
prove a process stop or lack of model work. The collector must separately scan
all durable invocation, route, native capture, admission, receipt and artifact
facts for that exact lease. It may permit a later invocation only when its
different original claim has a greater dispatch generation and was acquired
after the first reclaim event.

Store a typed, content-addressed observation in the existing baseline
quiescence proof. Its source inputs are the original claim identity, exact
reclaim event and current blocking invocation start. Recompute it under the
Task lock and queue idle fence before consuming the approved baseline. Do not
reuse the observation as a historical process-stop receipt.

The scan has an explicit boundary for a claim that never received a Run or
Context identity. Existing capacity callers continue to require their real
identities before reading their Context. A knowledge invocation for the old
lease must either be independently sealed by the existing knowledge proof
path or cause refusal; the new observation is only for a claim with no such
fact.

Good: a genuinely uninvoked expired claim followed by one start-only local
Coder invocation. Base: a single claim with a complete outcome keeps its
existing proof. Bad: infer no start from lease expiry, skip a hidden first
route/capture, or replace the second UNKNOWN with a synthetic stop.
