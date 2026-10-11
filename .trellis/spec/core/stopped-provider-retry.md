# Stopped provider prerequisite failure: same-Task retry

## Scope and signatures

The initial allowlist contains only Coder `FAILED / AUTHENTICATION_ERROR`,
`transient=false`, without an artifact. This is a permanent prerequisite failure,
not a service-fault refund. The original outcome remains FAILED. This capability
does not repair provider credentials or test provider health by itself.

```python
StoppedProviderFailureProof.create(
    outcome=DeliveryInvocationOutcome,
    capture_start=ExecutionCaptureStart,
    capture_stop=ExecutionCaptureStop,
) -> StoppedProviderFailureProof
validate_stopped_provider_capture(proof, dirty_capture, inventory, permissions) -> None
require_stopped_provider_workspace(proof, dirty_capture, inventory, permissions, denied_paths) -> None
ProductionBaselineFactCollector._stopped_provider_failure(task, item, step) -> StoppedProviderFailureProof | None
BaselineProposeCommand.purpose = BaselinePurpose.STOPPED_PROVIDER_RETRY
BaselineOperatorAuthorization.confirm_provider_prerequisites_repaired: Literal[True] | None
BaselineExecuteCommand.confirm_provider_prerequisites_repaired: Literal[True] | None
ExecutionBaselineBinding.stopped_provider_failure_sha256: Sha256 | None
DeliveryWaitInvestigation.provider_failure_code: Literal["AUTHENTICATION_ERROR"] | None
```

The public route uses existing baseline PROPOSE → exact EXECUTE(PAUSE) → separate
latest-bound RESUME. No new direct retry, broad transient enum or DeliveryWait
resolution is introduced. Manager can investigate and prepare but cannot supply
human engineering confirmation or modify a role verdict.

## Contracts and sequence

The proof contains immutable original outcome/start/claim and real capture start/
stop. It requires native `kind=failed`, nonzero returncode and no output, with no
interruption cause. `original_error_code` must be absent/None or the exact original
`AUTHENTICATION_ERROR`, never another failure. Request, Run, work/Lease, checkpoint,
source, scope, frozen Task intent/permissions and policy bind exactly. The trusted
collector revalidates the historical claim and current actual process/session
absence under the real Task lock and idle SQL fence. Unknown or live process facts
cannot be converted to stopped facts by an operator declaration.

Same-base `stopped_provider_retry` forbids a supplied target and `coder_reapply`.
Collector and service independently select the trusted current execution base.
Plan requires preserve_draft, unchanged HEAD/patch/inventory, no accepted
implementation, native-rule change, conflict or competing recovery proof. Full
body/fingerprint/coverage and frozen write policy reuse the shared stopped-draft
validator. A permanent provider failure cannot introduce new noncache source
mutations after capture start; the draft must already have existed. Explicit
execution caches retain their existing narrow policy. Ignored noncache files,
secrets, symlinks, protected paths, incomplete draft and inventory drift reject.

An explicit `SOURCE_REBIND` may carry the same proof for a different target. All
existing complete patch, rebase preview, native-rule confirmation and independently
approved conflict `coder_reapply` contracts remain. It also requires human
prerequisite confirmation and PAUSE. The final SQL callback rechecks the original
immutable stop/claim independently from the updated workspace, then validates its
new exact HEAD/after-inventory. It must not compare a successfully updated workspace
against the old original before-inventory.

Facts require `retry_cause=provider_prerequisite_repaired`, exact original
start/outcome/proof digests and next attempt=current+1. No interruption receipt,
legacy/completed proof, retry_failure or already-applied reservation is allowed.
No original/later accepted publication or StateEvent adoption may be overwritten.
Ordinary frozen work budget is consumed atomically; transient failures are not
refunded or added. Exact execute/consumption replay creates no second reservation.

The engineering operator confirms the original provider/native configuration
prerequisites have been checked and repaired. This statement is required in the
exact saved authorization, does not claim machine health and always PAUSEs.
The store reopens the exact authority and proof digest, includes truthful required
Context, and retains prior source/native-rule lineage. Latest-bound explicit
RESUME freshly validates paused work/source/full inventory. A successor uses a
new Run, Context and real claim, followed by independent QA and Review.

Console contract version 6 uses the exact read-only INSPECT failure-code hint to
choose one platform preparation entry without guessing from reason text. The
hint has no permitted resolutions, remains absent on other/old results and does
not authorize recovery. Preparation checks may still reject missing proof. The
exact plan displays preserved progress, original prerequisite failure, human
confirmation, ordinary work cost and subsequent explicit continue. Checkbox
confirmation survives unrelated polling but resets when the exact plan changes;
detached old controls cannot POST a stale authorization.

## Validation matrix and tests

| Fact | Required result |
| --- | --- |
| Exact FAILED AUTH, nonzero failed stop, no output; original lawful draft | Same-base complete plan; human PAUSE; separate RESUME |
| Successful result, artifact, transient flag, different code or completed output | Reject this capability; preserve original route |
| Unknown/missing/live stop, foreign scope/claim/source or unlocked scan | Reject without changing history or files |
| Permanent failure with newly mutated source | Reject; cannot evade POLICY_VIOLATION through AUTH recovery |
| Complete original draft but new Git target | Existing source-rebind and native-rule gates plus exact prerequisite PAUSE |
| Missing confirmation, automatic policy, resume-mode execute or mixed receipt/proof | Reject before execution/accounting |
| Exhausted ordinary work, accepted publication or successor already reserved | No refund, no duplicate work or overwritten output |
| Changed workspace or stop/claim at final SQL callback | Reject consumption and preserve admitted operation |
| Published/fresh embedded Binding | Strict proof/human/PAUSE gates in every envelope, old gates preserved |
| Old wire without new fields | Canonical bytes/digests unchanged; no inferred prerequisite approval |

Incremental tests: `tests/manager/test_stopped_provider_retry.py`, existing completed
output checkpoint/rescue tests, `tests/contracts/test_stopped_provider_retry_schema.py`
and repair regeneration tests. Root separately owns public production composition
tests using fake models, actual test-owned native child processes, MySQL fencing,
distinct successor identities and independent QA/Review. These tests never call a
real model or production database. Do not run the full suite for this change.

## 存量数据处置 and rollback

No DB migration, original outcome rewrite, Task reset, lost budget refund or new
Requirement is needed. Publish the compatible readers at a controlled idle service
boundary. In the original requirement, INSPECT obtains the exact diagnostic; fix
the original provider/native prerequisites, prepare the complete current plan,
review and explicitly confirm the exact PAUSE, then separately RESUME the latest
binding. Existing draft, failure history, outcomes and prior HANDLE records remain.
There is no success guarantee before fresh Coder/QA/Review results.

After new records are saved, rollback must retain readers for the additive purpose,
proof and confirmation. An older unsupported version should fail closed rather
than remove fields, resurrect old work or bypass the exact latest-bound decision.
