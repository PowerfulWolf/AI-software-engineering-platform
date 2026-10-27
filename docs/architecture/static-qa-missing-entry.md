# Candidate test entry absence: controlled QA recovery

The frozen K1 plan names QA test files that are absent from its candidate commit.
`observe_candidate_test_entry_absence()` reads the candidate Git tree and binds each
missing regular-file path to an exact planned QA command row. It is a read-only
observation: the existing `WAIT/NOT_STARTED` remains in place, and no QA verdict or
queue decision follows from this observation alone.

`TrustedStaticQaMissingEntryOutputContract` is a separate application-owned output
gate for an independently claimed QA run. Given an authenticated, sealed
no-start proof and the exact candidate observation, it permits only a commandless
`qa-report` with `status=FAIL`. Every affected criterion must be `FAIL` and cite the
single proof evidence; each absent path must have a major or blocker finding with
`code=MISSING_PLANNED_TEST_ENTRY`. It rejects PASS, test-command claims, extra
evidence, unrelated findings and run/source mismatch. Multiple frozen rows naming
one path combine their criterion IDs without losing either row's observation.

The output contract is wired to the production delivery route only after a public,
owner-fenced `STATIC_QA_MISSING_ENTRY` wait resolution verifies the original
`WAIT/NOT_STARTED`, complete no-model/no-command history, current Requirement and
Task identity, exact candidate and a fresh independent QA claim; it also requires
the accepted Plan and implementation artifacts. The decision requeues the same QA
WorkItem in a new dispatch generation without granting another work attempt. The
old wait stays immutable in history. `RESUME_UNINVOKED` remains the ordinary verifier
route and does not select this contract. The current Worker, original no-start proof,
consumed decision, candidate Git tree and claim are rechecked before model admission
and output acceptance; if they drift, output is rejected without publishing a verdict.
A genuine QA FAIL follows ordinary Coder remediation. A repaired candidate still
requires independent QA and Review.

The existing engineering wait investigation now preserves the original QA verifier
preparation as `NOT_STARTED` even when a newly collected mixed prerequisite receipt
is `WAIT_ENGINEERING`. It verifies the original preparation intent, historical
claims and current native execution records before recording that fact. A missing
or drifted original claim remains `VERIFIER_PREPARATION_UNAVAILABLE`; an uncertain
native execution remains `NATIVE_EXECUTION_UNCERTAIN`. The prerequisite blocker
and empty permitted-resolution list stay intact. This is read-only diagnostic
evidence, not a static QA admission or authorization to resume.

The code and Schema are integrated but are not deployed merely by this source change.
To activate for K1, release the verified platform build while the service is idle,
use the public engineering wait inspection for the exact current K1 WorkItem and
candidate, seal a separately authorized `STATIC_QA_MISSING_ENTRY` resolution, then
let the normal Supervisor claim the new QA generation. Inspect the durable QA report,
queue and retry budget before any Coder continuation. Do not edit the frozen Plan or
retroactively rewrite the old wait. If the release must be rolled back, stop new
admissions and restore the previous platform build; preserve all appended decisions,
claims and QA facts for audit. Any in-flight claim must finish or be fenced before
restarting on the old build. K1 requires a fresh public inspection after rollback;
the old wait is never silently recreated.
