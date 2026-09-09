# Universal delivery resume design

## Boundary

`resume` operates on a Delivery aggregate, not an individual Agent Run. A Role Run remains
at-most-once. When a provider invocation may have started, Project Manager creates a successor plan
or successor Task; it never calls the provider again with the consumed invocation identity.

```text
ase request resume DELIVERY
        |
        v
DeliveryResumeController
        |-- automatic checkpoint stage -> existing UnifiedProjectEntryService.resume
        |-- human gate -> return exact required human action, zero model calls
        |-- failed Coder, no candidate -> discover failed Run and capture worktree
        |       |-- no approval -> return exact recovery plan
        |       `-- approved -> fresh recovery Task -> Coder -> QA -> Reviewer
        |-- terminal candidate -> CandidateVerificationEntry
        |       |-- no approval -> return approval-required result
        |       |-- admitted/incomplete -> propose a successor verification plan
        |       |-- PASS+APPROVE -> accept the independently verified candidate
        |       `-- QA FAIL / Review REJECT -> CandidateRemediationService
        |                                      `-> fresh serial Coder -> QA -> Reviewer Task
        `-- joint delivery -> resume incomplete child first, then parent integration
```

Low-level `verify-*` and `recovery *` commands remain break-glass interfaces. The normal operator
interface is `resume`, optionally carrying exact approval for a plan emitted by a prior `resume`.

## Durable records

- Existing ProjectDeliveryCheckpoint remains the aggregate cursor and append-only hash chain.
- CandidateVerificationPlan/Authorization/Invocation/Completion remain candidate-scoped evidence.
- `ContinuationDispatchRecord` binds the verification completion, original Delivery/Task/candidate,
  current clean base, successor Task, organization workforce snapshot and serial allocation.
- The successor Task ID and dispatch ID are deterministic from the completion digest. Exact resume
  replay returns the same allocation; changed lineage fails closed.
- Remediation context contains the sealed verifier completion plus the bounded, secret-scanned
  candidate patch. Coder owns adaptation to current main; QA and Reviewer judge Candidate V2.

## State and error matrix

| Current durable fact | Resume behavior | Provider call |
|---|---|---|
| PREPARING through DELIVERING | Continue existing automatic stage | Only next unconsumed run |
| WAITING_PRODUCT_REPLY / WAITING_PRODUCT_APPROVAL / WAITING_HUMAN | Return exact gate | No |
| DONE | Return current result | No |
| BLOCKED/FAILED Coder without candidate | Capture its worktree and propose exact recovery plan | No |
| Approved Coder recovery | Fresh serial recovery Task; attach result to original Delivery | Yes |
| BLOCKED/FAILED with candidate, no verification plan | Propose exact verification plan | No |
| Verification plan awaiting approval | Return exact digest and resume approval command | No |
| Approved plan with no invocation | Run QA, then Reviewer only after QA PASS | Yes |
| Admitted verifier without completion | Propose successor plan; require new approval | No |
| QA FAIL or Review REJECT | Commit deterministic remediation Task and run serial delivery | Yes |
| Drift, unsafe path, policy mismatch, ambiguous provider outcome | Stop with typed human action | No |

## Live team view

The read model includes both `dispatch_commits` and `verification_reservations` in the same
repeatable-read MySQL snapshot. Verification is a first-class work item with its execution Task,
source Delivery/Task, candidate scope, assigned QA/Reviewer, current role, route attempts and sealed
documents. Continuation dispatches appear as `remediation` work and retain their source lineage.

## Good / base / bad

- Good: QA FAIL completion deterministically creates one fresh Coder Task, produces Candidate V2,
  passes independent QA/Review, updates the child Delivery, then permits joint integration.
- Base: repeating resume after any sealed completion returns the same records without new calls.
- Bad: source/main/preparation/policy drift, mismatched approval digest, duplicate allocation identity,
  secret-bearing patch or uncertain admitted invocation never causes a silent rerun.

## Rollback

Code can be reverted without rewriting existing Task/checkpoint/verification records. Existing
records remain readable because new dispatch kinds are explicitly tagged and old records are
unchanged. No target branch is merged, pushed or deployed by resume.
