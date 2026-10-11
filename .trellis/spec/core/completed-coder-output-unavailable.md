# Completed native Coder output unavailable

## Scope and signatures

This capability handles a nonterminal IMPLEMENTING Task with a sealed FAILED
WORK_INTERRUPTED or INVALID_OUTPUT/nontransient/no-artifact result and separately sealed completed native
stop (returncode0, output_present=true). Output content and why it was not accepted remain
unknown unless separately evidenced. INVALID_OUTPUT retains the original rejection; it is
not accepted as an artifact. It is not TIMEOUT, provider failure,
legacy unknown execution, a candidate or a verdict.

```python
CompletedCoderOutputUnavailableProof.create(...) -> CompletedCoderOutputUnavailableProof
CompletedCoderOutputUnavailableProof.validate_integrity() -> None
ProductionBaselineFactCollector.collect(target_base_ref: str | None) -> BaselineExecutionFacts
validate_completed_output_capture(proof, dirty_capture, inventory, permissions) -> None
require_completed_output_workspace(proof, dirty_capture, inventory, permissions, denied_paths) -> None
ExecutionBaselineService.propose(target_base_ref, input_mode, purpose) -> ExecutionBaselinePlan
ExecutionBaselineService.execute(plan_sha256, authority=...) -> ExecutionBaselineBinding
ExecutionBaselineService.continue_execution(binding_sha256, authority=...) -> Task
```

The public API remains the existing baseline proposal/execution/continue flow. No raw store,
process-stopped flag, shell, output-replay or cleanup permission is introduced.

## Exact contracts

The typed proof contains original immutable DeliveryInvocationOutcome, ExecutionCaptureStart
and ExecutionCaptureStop plus its digest. Validate original start/request/work/lease/checkpoint,
real historical claim and claim scope, process-stop/start digest and time, frozen Task intent,
policy, permissions and exact native Requirement/dispatch scope under existing idle/Task fences.
Require Coder FAILED, WORK_INTERRUPTED or INVALID_OUTPUT, transient=false and artifact=None; completed returncode0,
output_present=true and no cause/original_error_code. Recheck actual PGID absence through the
existing native stop seam. Do not strengthen or reinterpret its historical proof scope.

Baseline facts add optional `completed_output` excluded when None. Reservation adds optional
`completed_output_sha256` excluded when None. The ordinary `proof.reason` property derives
`completed_output_unavailable` from sealed WORK_INTERRUPTED, or `completed_output_rejected`
from sealed INVALID_OUTPUT. It is not a wire field, API input or independent permission. Facts
and queue consumption must match that derived reason exactly; mixed code/cause pairs reject.
Require outcome/start/proof references, next attempt=current+1, no receipt, no containment,
no retry_failure, no already-applied reservation. New execution consumes normal frozen work;
no transient refund. No accepted publication from the original invocation or later StateEvent
adoption can exist. Other historical publications at the same checkpoint may be excluded only
when their exact artifact ID was retired by a durably consumed rejected-output decision; never
exclude the current invocation, an unconsumed rejection or an ancestor closure. Retain all original
artifacts/publication receipts and failure facts.

A proof of stopped/unaccepted execution is not a workspace-ready proof. Final proposal compares
the original capture-start before inventory against the complete stable current inventory,
authorizes every mutation with frozen permissions/denied paths, permits only existing explicit
cache paths, and requires every noncache mutation to be present in the complete legal dirty
capture or exact inherited continuation paths. Inventory is not Git-ignore filtered. Existing
HEAD/index/branch, text-body, secret, protected-path, no-follow, mode and byte gates remain.
Recollect original facts and recheck complete inventory after capture and before publication.
The Plan model also performs pure noncache coverage and capture-after body versus inventory
kind/SHA/mode/size/deletion checks. It reads no current filesystem during historical decoding;
the service separately performs current workspace authorization and freshness checks.

Two distinct purposes use this exact proof. Ordinary SOURCE_REBIND still requires a target
different from the previous execution base and preserves its existing continuation modes.
`COMPLETED_OUTPUT_RESCUE` handles the same code base without requiring a user to enter a SHA:
`BaselineProposeCommand` forbids a target and `coder_reapply` for this purpose. Under the Task
lock and idle SQL fence, collector resolves the trusted current input's execution base; service
independently derives the same base from the current validated binding/Task. Recollection accepts
only that exact base. Missing completed proof rejects without changing original state or history.

Same-base Plan requires the exact completed proof, complete legal inventory/captures, no accepted
implementation, native-rule change or legacy containment, unchanged HEAD and dirty patch, and a
nonconflicted preserve mode. Execution validates files without rebase/reset. Binding carries
optional `completed_output_sha256` for this purpose or an explicitly rejected-output SOURCE_REBIND, inherits the previous native-rule epoch
and source artifact lineage, and requires same base/source, identical before/after inventory,
exact human engineering authority and PAUSE. The store checks the proof digest and the saved exact
authority when reopening. None/default fields remain excluded from canonical historical wire.

SQL consumption rechecks the real original completed proof, both legal captures, stable inventory
and frozen write policy before atomically charging one ordinary work attempt and creating a
paused successor. Exact consumption replay does not reserve again. Explicit latest-bound RESUME
rechecks source/inventory/frozen identity and releases only that successor. New Run/Context/claim
must pass normal production gates and independent QA/Review. No HANDLE operation is rebranded or
relaxed into this capability.

Console contract version 7 advertises preparation for completed INVALID_OUTPUT; version 5
continues to advertise the older unknown-output preparation. Earlier versions retain their
original pause/source-update behavior. A visible target-free entry says the platform will check, not that any FAILED run
is recoverable. Typed known timeout/provider receipts, permitted result/continuation routes,
knowledge/rejected/legacy proofs and exhausted budgets keep their own routes without a necessarily
rejected new entry. The current sealed plan separately explains stopped execution and unknown report
content, normal work cost, exact PAUSE and subsequent independent validation. Exact bound active
RESUME uses preparation copy (“主执行尚未开始”), never a claimed model execution or an unrelated
operation. Task detail opens only a current owning requirement in the same Project.

A current exact completed-output plan takes precedence over an older precisely matched HANDLE
investigation that recorded unknown outcome/stop/checkpoint. The old investigation remains
history; it cannot hide PAUSE approval, create a second legacy rescue panel or authorize an old
legacy callback. Changed proof/scope still removes the new approval. Published standalone
envelopes, including queue release, apply the same purpose/proof/PAUSE cross-field gates to
their embedded Binding definitions as the direct Binding and Console operation schemas; fresh
regeneration must preserve both completed-output and legacy containment gates.
Incremental proof/action rendering includes the exact current plan digest in its view signature;
preparation and invalidation update the existing DOM without reload. Detached old HANDLE/RESOLVE
callbacks cannot replace the current exact plan; read-only INSPECT remains available.

## Validation matrix

| Case | Required behavior |
| --- | --- |
| Exact completed stop + FAILED WORK_INTERRUPTED/no artifact + legal full draft | Full baseline proposal; ordinary work reservation; exact PAUSE/RESUME |
| Ordinary accepted progress or successful result | Existing adoption path, no overwrite |
| FAILED result without real capture stop | Reject; outcome is not stop proof |
| Timeout/provider cause or absent output | Existing truthful routes only |
| Foreign scope/request/lease/source, missing claim/ledger, process live/unknown | Reject before workspace authorization |
| Original/later accepted publication or StateEvent adoption | Reject completed-output capability |
| Different historical work, exact consumed rejected-output ID | Retain raw receipt; omit only that ID from the current publication gate |
| Ignored noncache mutation outside draft/inherited set or allowlist | Reject complete proposal |
| Secret, symlink, staged index, oversized body or inventory drift | Reject; preserve files/history |
| Exhausted frozen work budget | No successor, no refund |
| Old wire with no completed fields | Identical canonical dumps/digests and normal routes |
| Exact execute/release replay | No duplicate attempt, binding or role execution |
| Same-base purpose with user target or Coder reapply | Reject; backend alone freezes current base |
| Same-base human approval with resume mode / automatic policy | Reject; first save exact PAUSE |
| Previous accepted native-rule epoch | Inherit exact digest/context lineage, do not clear rules |
| Other typed usable wait route | Keep original route; no new completed-output prepare button |
| Exact bound active RESUME | Show continuation preparation; unrelated Task/work/digest cannot override pause |
| Exact new completed plan + matching older unknown-stop investigation | Current PAUSE remains visible; history and old callbacks cannot replace the plan |
| Embedded completed Binding in published/fresh standalone schema | Reject resume, missing proof, reapply, policy authority or proof under another purpose |

Good: preserve unknown result, capture full legal source, approve a new target, pause and explicitly
release a fresh ordinary-work Coder. Base: existing timeout/transient/uninvoked/legacy behavior and
historical digests remain. Bad: invent a success artifact, call completed a timeout/provider fault,
drop ignored files, infer cache cause from a generic failure, or accept stopped proof as READY.

## Existing data, rollout and rollback

Do not change historical run7 outcome/start/stop, reset Task, delete ledger, or directly update
queue rows. Exact cache maintenance is separately authorized/audited by root and cannot grant
execution permission. At a controlled idle load boundary, public PROPOSE prepares a new complete
plan; inspect and approve its exact digest with PAUSE, then RESUME latest exact binding. A terminal
Task remains ineligible. After consumption retain compatible readers and decisions; rollback
must not resurrect old work or change ordinary work accounting.


## Completed rejected output: same flow and historical compatibility

The sealed result remains `FAILED/INVALID_OUTPUT/transient=false/artifact=None`, with the original
failure code and diagnostic, capture start, completed returncode-zero stop, output-present fact,
claim and full digest chain. No code repairs the old report, guesses a missing rejection subcause,
substitutes a timeout/progress receipt or refunds work. The existing proof kind, version and
`output_content_status=unknown` remain unchanged because rejection does not recreate its content.

Both same-base `COMPLETED_OUTPUT_RESCUE` and selected target `SOURCE_REBIND` support rejected output.
New rejected-output plans require exact operator engineering authority and PAUSE followed by a
separate exact latest-bound RESUME. Organization policy and a RESUME execute command reject before
Git changes or a new queue reservation. A SOURCE binding for this reason carries the existing
optional `completed_output_sha256`; store reopening and queue consumption match it to the full
plan proof and saved exact authority. Mixing legacy containment or provider prerequisite proof,
missing/different digest, accepted implementation or applied/refunded reservation rejects.

Historical WORK_INTERRUPTED proof, facts, reservation and binding bytes/digests are unchanged.
Old SOURCE_REBIND bindings without `completed_output_sha256`, including their policy/RESUME form,
remain readable. This compatibility does not let INVALID_OUTPUT use the historical omission.
The plain reason property is excluded from model serialization and Schema generation.

Immediately before new SQL consumption, production reopens the original outcome/start/stop and
historical claim under the same Task lock and idle queue fence. It validates the original legal
complete draft and inventory with frozen permissions. Same-base consumption additionally rechecks
both actual captures and equal before/after inventory. SOURCE consumption permits the trusted
rebase to change inventory, but compares the real current inventory to the binding's after digest,
rechecks source/branch, complete prepared dirty patch, clean index and a second full inventory.
The original proof remains about the old run; it is not compared to the rebased filesystem as
though its before inventory described the new baseline.

The six published proof/plan/binding/queue consumption/queue release/Console graphs and fresh
regeneration retain matching code/cause, proof-required and explicit human PAUSE guards. Runtime
models additionally enforce cross-record digest equality, claim, source and authority association;
JSON Schema alone cannot prove those relationships. Public Host tests must cover original rejection
→ target-free or source proposal → PAUSE with zero calls → latest exact RESUME → new Run, Context
and claim → normal independent QA/Review, with unchanged old failure and ordinary-work accounting.

### Existing data and rollback

No DDL or production SQL edit is required. An existing exact completed INVALID_OUTPUT without an
artifact can use the same Requirement's public baseline preparation, inspect the complete plan,
approve PAUSE and then separately continue. Preparation is not a guarantee of admission: missing
stop/claim, active ownership, unsafe ignored files, changed workspace or exhausted budget still
reject while retaining history. K1's missing raw JSON is not reconstructed and GIT_CONTRACT's
unevidenced subcause stays unknown. After a new rejected reservation is consumed, keep compatible
readers when rolling back and prefer a forward fix; do not delete the new records or reset attempt
accounting.
