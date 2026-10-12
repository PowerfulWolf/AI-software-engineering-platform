# Unaccepted Coder draft UI

## Signatures and contract

`consoleSupportsCompletedOutputRescue(rejected=false)` requires operation contract version 5
for historical unavailable output, version 7 for rejected output, plus the unchanged typed
baseline actions and explicit RESUME capability.

`matchingCompletedOutputRescuePlan(plan, bound, operation, sameSource=true)` binds current
Task/revision/work/source, original Coder Run/start/stop, complete capture and proof digest.
FAILED/nontransient/no Artifact and native completed/zero return code/output present are required.
WORK_INTERRUPTED pairs only with `completed_output_unavailable`; INVALID_OUTPUT pairs only
with `completed_output_rejected`. Neither permits provider failure or legacy containment.

Same-source additionally requires frozen target, unchanged prepared source, preserve_draft,
no native rule change, no conflict and no caller target. SOURCE independently retains its exact
target, input mode, current plan, native-rule review and human PAUSE gates. Rebase inventory
need not equal old inventory; the backend verifies both independently.

`engineeringCurrentCompletedPlan` selects the latest **validated** proposal across the two
existing purposes. `engineeringWaitCurrentFacts`, current wait controls and copied handling
reports consume this result. An older missing-stop/checkpoint investigation stays historical.
Preparation never proves eligibility or invokes a model. Approval preserves failed history,
consumes ordinary work and pauses. Only later exact RESUME can start a new claimed role.

## Validation matrix

| Input | Display / write behavior |
| --- | --- |
| Current INVALID_OUTPUT wait, compatible service | Existing “准备保留进度的恢复方案”; only platform check promised |
| Exact stopped rejected proof, correct ordinary reservation | Visible full explanation and exact PAUSE approval |
| New rejected proof on v5/v6, or capability withdrawn later | Explain service upgrade; no prepare/execute/SOURCE POST |
| Different Project, Run, capture, cause, digest, published result or live/unknown stop | Reject detached control; preserve facts |
| SOURCE plan with changed project rules | Read every complete diff and confirm before exact PAUSE |
| Newer current SOURCE plan | Suppress obsolete same-base preparation; target decision remains clear |
| Old WORK_INTERRUPTED proof on v5 | Existing compatible PAUSE path unchanged |

`coderOutputDiagnostic` and Python `_coder_output_diagnostic` map only the fixed native
structured-output prefix plus delimited `WORK_SLICE/validation_rule` tokens. Known Enum values
get fixed Chinese. Unknown values remain neutral; GIT_CONTRACT says its old specific subcause
was not saved. Do not reflect provider JSON or arbitrary exception text. Run/digest locators
remain secondary audit references. Python and shipped JS have parity tests.
The real native result may wrap that prefix once as `coder run run_<lowercase alnum> failed: `.
Both readers remove only this anchored single envelope before the existing fixed-prefix/token
checks. Foreign roles, nested wrappers, arbitrary preceding prose, malformed run IDs and
delimiter-like token suffixes do not acquire this diagnostic. Historical raw records stay intact.

Good: report rejected, complete draft sealed, explicit ordinary cost and QA/Review explained.
Base: unknown pre-check offers a check, not an approval or success claim. Bad: tell users the
business work is done, guess the historical slice cause, use stale approval, or submit new
rejected recovery to an older server.

## Verification and stock handling

`engineering-wait.test.cjs` exercises real DOM callbacks, exact SOURCE/same-base identities,
versions, drift, copied reports, ordinary PAUSE and prior stopped/provider/legacy paths.
`test_blocker_text.py` checks fixed wording and actual shipped JS parity.
No SQL migration or historic operation rewrite. After compatible deployment refresh the
same Requirement, prepare its current exact plan, review target/rules when updating source,
approve PAUSE, then independently RESUME. Old terminal tasks are never reset.

Rollback preserves new typed reason readers and immutable facts. Reverting the UI can hide
the new entry and reintroduce opaque wording; it is not a substitute for undoing an approval.
