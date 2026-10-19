# Existing-contract verification design

The real K1 attempt reached allocation and clean worktree creation before a current-facts
gate rejected preparation. No seed or invocation was published. The observed environment
later had both Console and Colima/MySQL stopped. Preserve these facts without asserting an
unproven causal failure or modifying existing records.

Exercise the actual public Continue -> recovery entry -> allocator -> coordinator -> seed
chain. Inject one bounded preparation interruption at the seed boundary, after allocation
and worktree creation. Reconstruct service state, reuse the same approved Plan and resume
without another approval field. Compare persistent identities and meaningful run counts.
Do not replace the entire facts/builder/allocator chain with a cast synthetic success.

Good: unchanged complete current facts and clean unseeded target resume the same worktree
and allocation once. Base: a repeated request adopts/rejects the already-admitted invocation
through normal rules without executing it twice. Bad: dirty target or changed facts reject,
leaving the old approval/allocation and drafts intact.

No signatures, wire fields, Schemas, permissions or production behavior change. No migration
or service restart is required to add this coverage. Fixture success never establishes real
K1 QA/Review acceptance. Root controls any later independent commit and deployment decision.
