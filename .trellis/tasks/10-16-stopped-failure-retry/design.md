# Stopped unclassified native failure: exact ordinary-work retry

## Scope and signatures

A Coder invocation may have a final `FAILED / PROVIDER_UNAVAILABLE / transient=false`
result, a real nonzero `failed` native stop, and no output. This is not a missing outcome,
AUTH prerequisite repair, known transient outage or a successful completion. Preserve its
classification and complete history. A human engineering decision may spend one remaining
ordinary work attempt on the same Task/source/draft without claiming its cause is known or fixed.

`StoppedFailureProof(kind=stopped_failure)` binds the immutable outcome, capture start and
capture stop. `BaselinePurpose.STOPPED_FAILURE_RETRY = stopped_failure_retry` uses existing
public `PROPOSE_EXECUTION_BASELINE → EXECUTE_EXECUTION_BASELINE(PAUSE) → separate
RESUME_EXECUTION_BASELINE`. `facts.stopped_failure`, reservation/binding
`stopped_failure_sha256`, and reservation `retry_cause=stopped_failure_retry` bind one proof.
`confirm_stopped_failure_retry=True` is required in the exact operator authorization and
execute request. It acknowledges unknown cause and one ordinary work debit, not repaired
provider prerequisites. Manager cannot supply it and automatic policy cannot substitute.

## Contracts and sequence

Preparation fixes the trusted current base; target overrides and `coder_reapply` are refused.
Require exact historical Coder claim, request, Run, source, Context, scope, Task intent,
permissions, checkpoint, outcome/start digests and actual owned-session cessation. The native
stop must be `failed`, nonzero, output absent, cause absent; original error code must be absent
or PROVIDER_UNAVAILABLE. Do not parse error message or stderr digest to grant authority.

Full source bodies/patch/inventory must be legal and stable, with unchanged HEAD/index/branch.
No new noncache source mutations since invocation start are allowed. Explicit existing cache
policy remains. No accepted implementation, native-rule update, other proof, retry failure,
interruption receipt or pre-applied reservation is allowed. Inspect raw artifacts as well as
adopted artifacts and revalidate late publication/stop/claim facts inside final SQL fencing.
Unreadable, corrupt, foreign, live or ambiguous facts refuse without source or history mutation.

The approved operation preserves all drafts, reserves exactly one new ordinary work generation,
and holds it in WAITING_HUMAN. No transient refund, error rewrite or historical Task reset.
Replay consumes no second reservation. Explicit latest-bound RESUME revalidates source, exact
hold/binding/disposition and complete current inventory; fresh Run/Context/claim then executes.
Existing candidate, independent QA and Review gates remain mandatory. Failed future attempts
require another current exact decision and remaining frozen budget; no automatic unknown retry.

Absent optional fields preserve old canonical bytes/digests. Old AUTH/completed/no-outcome
recovery acceptance boundaries remain unchanged. Console capability version 10 gates new controls.
Read-only NONTRANSIENT_INFRA waits may offer a platform check; only successful exact preparation
shows an approval for this proof, and polling cannot carry approval to a different plan.

## Validation matrix / required tests

| Fact or request | Result |
| --- | --- |
| Exact stopped FAILED PROVIDER_UNAVAILABLE(false), no output, complete pre-existing draft | Same-Task/base preserve-draft plan |
| AUTH, transient=true, policy/invalid output, success, missing output with no outcome | Refuse this capability; existing routes unchanged |
| No stop, live/foreign session or claim, late raw output/receipt, altered route/outcome | Refuse before consumption |
| New source mutation, secret/ignored source/link, omitted body or inventory drift | Refuse, preserve original scene |
| Missing confirmation, wrong confirmation family, automatic authority, immediate RESUME | Refuse |
| Different base, reapply, native-rule change, competing proof, accepted implementation | Refuse |
| Ordinary work exhausted | Refuse; no refund or increased budget |
| Exact PAUSE replay / latest explicit RESUME | One reservation / one fresh claimed Run |
| Fresh regenerated / published embedded schema | Same cross-field gates and old wire compatibility |

Use typed proof/service/store/queue unit tests, fresh schema generation guards, browser stale-plan
and capability tests, and public Console/native isolated MySQL flow to same-Task DONE with independent
QA/Review. No real model is required for regression tests. Do not run MySQL reset fixtures in parallel.

Good: approve complete legal retained input while explicitly accepting an unresolved failure.
Base: cause remains unknown and prior failed outcome remains readable. Bad: relabel failure AUTH,
claim repaired credentials, refund transient budget, erase stderr history or infer process stop.

## 存量数据处置 / rollback

No DB migration or old record mutation is required. At a verified idle boundary, load compatible
runtime readers, prepare in the original Requirement, approve the exact PAUSE with the explicit
engineering decision, then separately RESUME. Existing FAILED outcome, prior UNKNOWN, claims,
progress, drafts and approvals stay immutable. No new Requirement is needed. Native delivery
still must produce a candidate and independent QA/Review; an operation success is not delivery success.
Before new records publish, code may revert; afterwards keep additive readers and pause execution
for a forward repair. Never delete bindings/audits/drafts or restart an incompatible older reader.


## Evaluation audit

`EngineeringHumanActionRecorder.record()` must include STOPPED_FAILURE_RETRY in its explicit
binding families. Reopen exact plan/failure proof/binding/authority; append a stable
`evalevt_failure_<binding-prefix32>` SUPPLY_EVIDENCE HumanActionEvent at authority.submitted_at
with immutable authority URI. The note says unknown failure and ordinary-work cost, never a
repaired cause. Exact replay is idempotent; altered same-ID events or missing/tampered authority
must reject. Runtime invocation calls the recorder before execution, so ADR recomputation sees
HUMAN_INTERVENTION. An Operation authorization artifact alone does not feed evaluation events.
Tests require exact/replay/tamper and ADR INELIGIBLE/HUMAN_INTERVENTION, plus public same-Task DONE
assertions. Do not retroactively synthesize old AUTH events or widen this change to other purposes.
