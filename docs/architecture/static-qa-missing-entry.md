# Candidate test entry absence: inactive QA output gate

The frozen K1 plan names QA test files that are absent from its candidate commit.
`observe_candidate_test_entry_absence()` reads the candidate Git tree and binds each
missing regular-file path to an exact planned QA command row. It is a read-only
observation: the existing `WAIT/NOT_STARTED` remains in place, and no QA verdict or
queue decision follows from this observation alone.

`TrustedStaticQaMissingEntryOutputContract` is a separate application-owned output
gate for a future, independently claimed QA run. Given an authenticated, sealed
no-start proof and the exact candidate observation, it permits only a commandless
`qa-report` with `status=FAIL`. Every affected criterion must be `FAIL` and cite the
single proof evidence; each absent path must have a major or blocker finding with
`code=MISSING_PLANNED_TEST_ENTRY`. It rejects PASS, test-command claims, extra
evidence, unrelated findings and run/source mismatch. Multiple frozen rows naming
one path combine their criterion IDs without losing either row's observation.

This output contract is **not wired to production admission**. The current native
verifier still requires a registered executor and still correctly waits. Activation
requires a public, owner-fenced wait resolution that verifies the original
`WAIT/NOT_STARTED`, complete no-model/no-command history, current Requirement and
Task identity, exact candidate and a fresh independent QA claim; it also requires
Schema and runtime integration. Do not use `RESUME_UNINVOKED` for that purpose: it
re-enters the ordinary verifier and waits again. The immutable old wait must remain
in history. A genuine QA FAIL would then follow the ordinary Coder remediation path,
and the repaired candidate would still need independent QA and Review.

No existing Requirement, Task, Operation, queue or verdict data is changed by this
inactive code. Removing this code is the rollback; current K1 stays at its original
wait until the complete public recovery route is separately implemented and checked.
