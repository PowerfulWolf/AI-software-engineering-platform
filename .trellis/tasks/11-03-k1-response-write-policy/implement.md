# Work record

Production facts at diagnosis: K1 child `delivery_c833c3235d0bb73adba67937d16ea66c`, Task `task_recovery_2638493abdfdb9c04e14f0e20b924d2c` is `BLOCKED` revision 6. Run `run_557f59df7ede4e3abf03552afededc97` has completed final route SHA `c5351021a2fc014455183f95bed8ffd92377b5184800dfeaf9950df06f44915b`, exact error `Responses tool request rejected: write_file/PATH_DENIED`, and a matching failed invocation outcome. Attempt 2 accepted `coder-progress` SHA `art_coder_progress_c54a956f1d2c4a919eed81eace66fa07`; three test files remain untracked in the original Coder worktree. The rejected request path is not in immutable evidence, so its identity remains unknown.

The Task Plan's next source-contract step explicitly permits `src/ai_software_engineer/artifacts/accepted.py`; the generic role guard rejects its `artifacts` path component. This is a reproduced platform defect to test independently from the actual denied request. The failed Run and policy event remain valid history.

The user separately confirmed that the older start-only Run
`run_87fcb918f85c40deb6270f2bfc4f2784` and all its local tools had ended
and could not write the original workspace. Its exact legacy rescue was already
recorded in the first baseline binding before this Task; this confirmation is
not evidence that the later `run_557f59df7ede4e3abf03552afededc97` succeeded.

Implementation: the role write guard now reserves only actual delivery-fact
roots and report outputs after the Task path grant, so an exact approved source
module under `src/.../artifacts/` is writable. Terminal Responses
`write_file/PATH_DENIED` with an unchanged nonempty lawful draft gets a distinct
v4 snapshot and a new `coder_reapply` Plan; the old failure remains immutable.
The static recovery Schema, generator output, Trellis and contracts are in sync.

Validation in this working branch: 135 focused unit/contract tests passed;
the new isolated MySQL/Git public fixture with accepted Responses Coder progress,
actual completed PATH_DENIED route, new Plan, independent engineering approval,
fresh Coder, QA and Review passed. Ruff check and format, Mypy on all 54 recovery
and tool source files, Schema regeneration idempotence and diff whitespace check
passed. The full three-case Responses public fixture remains the final gate
before commit and release.

Stock-data disposition: no direct SQL or migration. The existing K1 parent is
already BLOCKED in sync with its child; after controlled release, inspect the
exact terminal Task, Run, queue, source and retained three-file draft again.
Only then use public `CONTINUE_DELIVERY` to propose and separately approve the
new Plan. Keep ProductSpec, Design, Plan, old results and all QA/Review gates.
Rollback before approving the new Plan means stopping the new binary through
the controlled service path; after new append-only facts exist, repair forward.
