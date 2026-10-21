# K1 knowledge citation rejection and HTTP recovery coverage gap

Status: diagnosed on 2026-10-21; this note does not implement or approve a fix.
The user asked why the existing K1 paused again and what operation is appropriate.

## Exact observed scope

- Public Requirement: `delivery_multi_bb78e2316afca47d005384542f685174535b69db`.
- Task: `task_recovery_6c7e369928a23df6e2ccf8ba32d6f816`; source `5547815464a04991f50a2e0532d6f2f13d8daa69`.
- Current WorkItem: `work_2b17cd34f8e2bf4840df927102e82e841446642207fb1265cd32d89bfbd703ab`, Coder attempt 2, checkpoint 5.
- At 05:02:41Z, a consistent SELECT-only transaction observed Task IMPLEMENTING/revision 5,
  WorkItem WAITING_DEPENDENCY and both historical leases RELEASED. Budget is available;
  projection has PLATFORM_BUG, engineering responsibility and retry_authorized=false.

## Trigger independently replayed from immutable facts

The first main Coder returned SUCCEEDED with `coder-progress`
`art_coder_ad453ed626a141a52548c2bda1e11b11`. It retained 21 changed files and completed
`design_step_step_01_contract_compatibility`; seven declared steps remain. This is progress,
not a candidate or independent QA/Review acceptance.

The second knowledge Run `run_knowledge_b7492806353b7d281b6f99ee51b10664` completed its intent and
assessment as RETURNED. The READ manifest has 16 exact citations and 20 total evidence
records. The model returned three claims. One claim about
`.trellis/spec/core/completed-coder-output-unavailable.md` has the correct document identity,
scope, document digest, chunk digest and URI, but an incorrect `chunk_id`:

- Model: `ff68fc4c40ffebdca5ef88ff3a6bc960c4d2871d96dfa3da92a934d940882b9e`.
- Actual READ: `ff68fc4c40ffebdca5efc8bafca3ba5883a2d2c221bca09a71b09b29b81ea2c5`.

`assessment_rejection_reason` deterministically returns CLAIM_WITHOUT_READ. The document
was retrieved; the model changed one exact identifier. Rejecting the result is correct.
Do not repair the returned citation, invent another READ or relax exact membership.
The second main Coder invocation has neither start nor outcome; it did not begin execution.

At 2026-10-21T05:07:05.189924+00:00, the actual read-only replay command was:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/ase-k1-rejected-knowledge-forensic-20261021.py --assert-valid
```

It exited 1 with `ASSERT_VALID_FAILED: CLAIM_WITHOUT_READ`. The script reopens the exact
Task's two documented knowledge lanes, validates immutable outcome/manifest digests and
replays the same production membership function. No model, Task state or old record is changed.
Bounded forensic report canonical digest: `58751173ff2043bb9d0bdda42b1bef16c0a901d7e54cfb292976644271218de1`.

## Why the existing recovery cannot proceed

The original intent has StructuredExecutionAdmission + StructuredHttpRoundTripReceipt,
with a successful Responses HTTP result. Assessment has HTTP 504 followed by a successful
Codex CLI fallback and a real StructuredNativeStopReceipt. Thus only the intent is HTTP-only.
Both phase outcomes are fully RETURNED; diagnostic route success is not semantic acceptance.

`knowledge/assessment_rejection.py::_returned` currently requires a native stop receipt for
each phase. `derive_rejected_assessment` calls this for intent first and refuses with
`RejectedAssessmentUnavailable(ASSESSMENT_REJECTION_NATIVE_STOP_REQUIRED)`. An HTTP request
has no native process stop. No complete semantic rejection observation is published;
the Worker correctly retains the current fallback PLATFORM_BUG wait under that contract.

The public investigation-only operation `operation_198a62ce1380f71957ea6fa13fa2a878` succeeded and produced
proof `09c72c212e70548bca6917f8e8f9120b4e5fc7b5ebd8688564dfea3ecfe37e90`. Its typed digest was revalidated. It reports
`missing=[INVOCATION_UNRECORDED]` and `permitted_resolutions=[]`. The generic wait inspector
looks for a main invocation that did not begin; this is not permission to fabricate one.
Repeating Continue, restarting or increasing budget cannot supply the missing proof.

## Required maintenance and existing-data treatment

1. Add route-aware semantic-rejection completion proof: validate exact synchronous HTTP
   admission/round-trip/RETURNED/result/request/claim binding; keep native routes' real owned
   session stop proof. Local HTTP completion does not assert arbitrary remote process stop.
2. Support an exact, independently revalidated handling path for this already-persisted
   PLATFORM_BUG wait. Preserve the old wait and original RETURNED bytes; do not rewrite SQL
   classification, fabricate an observation or force the existing INVALID_OUTPUT branch.
3. After contract tests and controlled deployment, inspect this same WorkItem and produce a
   fresh hash-bound engineering decision. If all source/READ/claim/no-main/complete-inventory
   and frozen-budget gates pass, resume new knowledge preparation in the same Task via a
   new WorkItem/claim/Run, consuming one ordinary work attempt exactly once.
4. Preserve the first accepted progress, 21 draft files, old route failures, approvals and
   budgets. Independent Coder candidate/QA/Review requirements remain unchanged. No new
   business Requirement or main rebase is required solely to repair this knowledge wait.

The future regression must cover HTTP-only intent + HTTP-to-native assessment fallback,
exact citation mutation, fresh proof for the existing generic wait, unchanged draft,
idempotent one-time budget debit and real new claim. It must reject incomplete/unknown/live/
foreign/tampered route receipts and cannot use the new route as a generic BLOCKED retry.

## Limits and rollback

This is an investigation, not a deployed repair or completed K1 delivery. Only the public
Inspect operation added an audit observation; source code, original outcomes, Task, budgets
and role verdicts were not modified. The diagnostic document can be reverted independently;
keep the durable investigation and source facts intact.

## Maintenance findings after authorization

The fixed route-aware helper independently reopened the same production records read-only at
2026-10-21T05:33:13Z and derived observation
`a42d270b1ded4fe69ab7bd691fd2ff656d80cb7fdf6276d91bc0526999f3dea3`. The wrong
citation remains unchanged and still rejected. No model or state mutation was involved.

The prior progress does not contain independent full DiffEvidence; its two evidence references
are logical command/test references. No stored run manifest exists for that main Run. Its
real capture start is `8489982b079f534b5635575023b09e2b84b439360d10d4d91bb449f4b646b6c3`,
with before-inventory `53dd023f3fa0cb6d12db81e64a7956ed630bd9919d40ac486d5762387e01c3ba`.
Capture stop `15f330ab6546568ad29f2bd5117ef049310819a9fe8a933925bd512e1a9df8c1`
records actual completed process and output present, but contains no after-inventory.
Consequently neither the original seed nor a comparison of path names proves today's bytes.

Maintenance therefore adds a distinct complete current draft observation and exact current
ENGINEERING acceptance in the public wait-resolution protocol. This accepts today's full
retained input without claiming a missing historical snapshot or changing accepted progress.
Automatic policy cannot approve this mode. Final consumption and successor provider admission
reopen the exact current inventory and full capture. Deployment/recovery results belong in a
separate final audit after verification; this diagnostic does not itself establish them.
