# Design

The stored K1 route and invocation outcome prove that the Responses adapter
returned `FAILED/POLICY_VIOLATION` after a synchronous `write_file/PARENT_NOT_FOUND`
refusal. The start inventory is sealed; there is no native process to observe and
no native `capture-stop`. Ordinary native terminal recovery currently requires one
unconditionally. An absent stop alone is not authority.

Add a narrowly typed terminal snapshot completion variant. For a single final
Responses route with the exact stable tool-refusal code and matching sealed
invocation outcome, use the route completion as the synchronous boundary only if
the full current inventory equals the sealed start inventory, the Git capture is
empty, no interruption receipt exists, the Task and queue are terminal, and the
existing Task lock is held. Bind the final route digest and completion time in
the snapshot; `capture_stop_sha256` is absent for this variant. The native variant
retains its exact current wire shape and stop proof. Re-read all facts and inventory
after source/target checks. A missing route, changed outcome, dirty worktree,
other refusal, native route, active claim or present receipt rejects.

The route completion and invocation outcome are existing trusted synchronous
boundaries for this exact returned refusal. A future separate stop receipt could
strengthen more general Responses recovery, but is outside this narrowly
verified K1 path. No historical record is backfilled.

Good: exact K1-style refusal with unchanged worktree produces a new Plan and
fresh Task after approval. Base: native stopped failure retains v1 snapshot bytes.
Bad: start-only UNKNOWN or dirty/mismatched Responses scene is rejected.
