# Candidate test entry absence: controlled QA recovery

The frozen K1 plan names QA test files that are absent from its candidate commit.
`observe_candidate_test_entry_absence()` reads the candidate Git tree and binds each
missing regular-file path to an exact planned QA command row. It is a read-only
observation: the existing `WAIT/NOT_STARTED` remains in place, and no QA verdict or
queue decision follows from this observation alone.

For the later K1 candidate `ec178521719a9b1ce0a9d1eb97505e77fe0c3cc7`,
the planned Python file exists but the exact frozen pytest function selection
has no direct definition or named reexport in that file. A separate bounded
Git-blob/AST observation may record this direct source gap when the module has
only simple, unambiguous declarations and imports. It does not assert that
pytest could not dynamically collect a test, and it never executes candidate
imports. Ambiguous source keeps the original engineering wait. Historical
missing-file proof wires and SHA remain unchanged.

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
requires independent QA and Review. The proof-bound static QA input is deliberately
limited to the authenticated absence proof and frozen Context; it does not append
the ordinary candidate source snapshot or claim that code review or planned tests
ran. The ordinary QA/Reviewer source view resumes on the repaired candidate. A
safe Plan directory suffix `/**` expands only against the base and candidate Git
trees to exact tracked paths, with the normal read/deny and bounded-input checks;
other glob syntax and missing exact dependencies remain rejected.

For a named-node proof, the trusted output and knowledge scope carry the full
frozen selection and explicitly say the original verification is `NOT_RUN`.
Independently claimed QA may fail source adequacy with proof-bound findings;
the platform does not create its verdict. The current Task, claim, Plan and Git
blob are reread at output acceptance just as for a missing file.

If the first post-decision QA claim has a sealed `READY/NOT_STARTED` preparation
but its lease expires before a durable model invocation start, a later adjacent
claim may continue the same consumed decision only after checking the expired
claim, the unchanged active static decision and Task/candidate, the original
marker, a fresh `NOT_STARTED` native observation, and the absence of any
WorkItem invocation start/outcome. The old decision is not resubmitted and the
failed claim remains in history. Any missing or uncertain fact returns to an
engineering wait; a later generation cannot inherit this one-step recovery.

The existing engineering wait investigation now preserves the original QA verifier
preparation as `NOT_STARTED` even when a newly collected mixed prerequisite receipt
is `WAIT_ENGINEERING`. It verifies the original preparation intent, historical
claims and current native execution records before recording that fact. A missing
or drifted original claim remains `VERIFIER_PREPARATION_UNAVAILABLE`; an uncertain
native execution remains `NATIVE_EXECUTION_UNCERTAIN`. The prerequisite blocker
and empty permitted-resolution list stay intact. This is read-only diagnostic
evidence, not a static QA admission or authorization to resume.

The initial static QA route was published on platform main `4ebb0bd9678f4cb2889fe3f9a960dfb43afc2fb5`.
K1's exact public wait investigation and `STATIC_QA_MISSING_ENTRY` decision were
already sealed and consumed; do not submit them again. Its first resumed QA claim
reached `READY/NOT_STARTED` and then expired without a durable invocation start.
After the follow-up input and no-start recovery fix is reviewed and released at
an idle boundary, use the public `CONTINUE_DELIVERY` operation with the current
parent checkpoint. The normal queue reaper fences the expired claim, and the
new preparation gate verifies the consumed decision and no-start facts before a
fresh independent QA claim. Inspect its actual QA report, queue status and frozen
Coder allowance before any Coder continuation. Do not edit the frozen Plan or
retroactively rewrite the old wait. On rollback, stop admissions, retain every
decision, claim and QA fact, and use readers compatible with any appended facts;
an expired lease is never proof that the original execution completed.
