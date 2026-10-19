# Implementation

The only Python change is `tests/recovery/test_preseed_reentry.py`. Production code,
Schemas, real K1 state and the production Host are outside this task.

The tests reuse `modern_failed_native_fixture`: a real temporary Git repository,
actual TeamHost/stages/stores/Worker, and an owned offline failed Codex executable.
Its existing gate requires the exact `ai_software_engineer_test` database, private
nonblocking OS lock, MySQL advisory lock, no other database sessions and all 13
mutable fact tables initially empty. A local empty autouse fixture prevents the
global reset from preceding that gate. The helper stops its owned process and
checks/reset facts only while still holding exclusive ownership.

After a real stopped Coder failure, the test commits a conflicting new base and
proposes an explicit `coder_reapply` Plan. Public `TeamHost.resume_delivery` selects
that Plan and processes its exact approval. A one-use exception at
`RecoverySeedService.seed` occurs after allocation and creation of the clean managed
Coder worktree, before any seed, SQL Task, queue claim or recovery invocation exists.
The public execution method is wrapped only to inject its documented offline
`route_factory` port; `resume_execution`, native facts, sealing, allocation,
worktree recovery, seed and claimed admission all execute their real implementations.

The next call reconstructs a TeamHost and its services, then uses public Continue
without an approval digest/reference. The unchanged case checks exact approved
authorization, sealed Task, dispatch and assignments/leases. Worktree reference,
inode and `.git` identity are checked at the real route-factory boundary after seed
verification and before provider execution; completed delivery normally releases
the clean Coder worktree. It also checks exactly one seed and first invocation;
the complete old patch in Coder's
Context; serial independent Coder/QA/Reviewer on the same candidate; and no duplicate
role run when a further reconstructed Host adopts the terminal result.

Two negative cases preserve the same approved records and both workspaces. A dirty
unseeded target must refuse execution. Changed current target facts must invalidate
the old Plan and require exact approval of a newly proposed Plan, with no new role
invocation or Task. All cases preserve the original failed Task, StateEvents and
worktree bytes. No source fix is presumed by this regression coverage.
