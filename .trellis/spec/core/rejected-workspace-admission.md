# Exact recovery of a refused baseline workspace admission

## Scope and failure mode

A main `DeliveryInvocationStart` is a claimed role boundary, not proof that a provider
started. An immutable FAILED/WORK_INTERRUPTED outcome can represent the trusted adapter's
pre-provider workspace gate. Such a result must remain FAILED. Never manufacture a native
capture stop, missing recovery receipt or accepted Coder result to make it resumable.

The observed compatibility defect joins two valid inputs: accepted progress frozen in a
same-source baseline Plan and a larger complete retained draft explicitly approved by that
Plan. Checking the full draft paths against only progress.changed_files rejects legal input.
The repair must not turn a historical progress artifact into a general dirty allowance.

## Interfaces and typed evidence

`manager/baseline_admission.py:BaselineInitialWorkspaceAdmission.authorize(request,
workspace_root)` remains the claimed Coder gate. It verifies Task, source/base, exact binding,
permissions, original worktree, required captures and complete inventory before provider use.
Only the exact accepted progress frozen in the current validated Plan can use the Plan's
complete unchanged approved draft. A later accepted progress uses the ordinary exact path
contract. The frozen progress ID, SHA and request paths remain unchanged.

`manager/rejected_workspace_admission.py:rejected_workspace_admission_evidence(...)`
is a trusted, read-only observation. It reopens immutable records under the existing Task
lock and returns `RejectedWorkspaceAdmissionEvidence` only for reason
`PRESERVED_PROGRESS_CAPTURE_MISMATCH`. It does not assert a new historical execution event.

The legacy invocation did not seal its runtime platform revision. A separate current
engineering declaration is therefore mandatory: `HandleDeliveryWait` and its Console intent
accept optional `workspace_admission_adapter_contract: WorkspaceAdmissionAdapterContract`.
Only trusted composition supplies `operator_principal` and `submitted_at`, after requiring
ENGINEERING duty. The declaration binds the exact scope/Task/WorkItem/claim/Run/start/outcome/
route, platform revision, sorted seven-file source manifest, deployment audit ID/SHA,
service instance ID/process birth and pre-invocation deployment observation time. No caller
can supply a process-stopped or model-not-started flag. Currently only the reviewed legacy
release `12caa6e14e47188d45bda9e7264e461acf45db89` and its exact seven source bodies are
supported; another version needs a separately reviewed contract.

`manager/workspace_admission_contract.py:seal_workspace_admission_adapter_contract(...)`
checks the supported manifest and reopens the exact immutable invocation, original claim
and unique route before sealing `WorkspaceAdmissionAdapterContractRecord` under
`state/continuations/<task_id>/workspace-admission-contracts/`. Its attribution is explicitly
`current_operator_supplied_historical_deployment_evidence`. This is what the maintainer now
supplies about an observed deployment; it is not a newly discovered historical automatic
receipt. The independently derived refusal proof and this testimony are separate mandatory
inputs. `EngineeringHumanActionRecorder` records SUPPLY_EVIDENCE at the current declaration
time, with the immutable declaration URI, even if the old Task had no baseline store.

The writer initializes a missing Task continuation directory through the existing no-follow
private700 writer and never chmods unsafe existing paths. Physical deletion explicitly
validates all typed declaration records and their Task/scope/Requirement/storage keys, then
requires complete directory-name equality before admitting the subtree. Unknown files,
foreign scope and symlinks refuse; recursive inclusion of an unchecked child is forbidden.

Evidence binds complete engineering scope and requirement/task/work/role/checkpoint/attempt/
dispatch identity, original lease and claim digest, Run and Context, source, invocation start
and outcome digests, the unique route result digest, complete Context digest, validated
baseline binding/Plan digests, exact accepted progress ID/SHA, complete workspace inventory
and capture digests, and `adapter_contract_sha256`. `observation_sha256` is the canonical
digest of all evidence fields except itself. `budget_source` is `frozen_work_attempt`.

The positive proof requires the supported trusted adapter contract whose exclusive
pre-provider exception branch emits the exact sealed refusal result. Check the matching
single ModelRouteAttempt and full immutable outcome/result identities. Independently
reproduce the old progress/full-capture mismatch and the new gate's success on the exact
approved input. Generic WORK_INTERRUPTED, arbitrary text, absent native files, a later
reproduction alone or an asserted `not_started` boolean do not establish this proof.

Scan the full exact Task/Run lanes for contradictions: native invocation/capture/tool/stop
or recovery admission receipts, accepted/completed outputs, foreign or additional routes,
changed claim/source/Context/baseline/progress, live ownership and altered draft. Unsupported
adapter versions, ambiguity, malformed records and any missing required positive fact fail
closed. Never scan unrelated workspace trees or change a prior outcome.

## Resolution and accounting

The existing public investigation/Handle protocol exposes only
`RETRY_REJECTED_WORKSPACE_ADMISSION` when the exact current observation permits it. Persist
the entire typed proof in investigation and resolution. Engineering approval is bound to
that current disposition, Task intent, source and checkpoint; product scope is unchanged.

Recollect all proof before consuming an unconsumed decision. Under the existing SQL owner
fences, replace only the refused WorkItem with ordinary attempt+1 and a new WorkItem.
The next execution requires fresh claim, Context and Run and reruns current workspace and
capacity gates. It does not refund attempts, increase time/provider limits, alter retry
failures, reset a Task or approve progress/candidate/verdict. Exactly committed resolution
replay is idempotent; stale unconsumed decisions are rejected. Active claims, terminal Tasks,
accepted current work and exhausted frozen work/identity budgets cannot use this action.

`HandleDeliveryWait` storage identity uses only the five `InspectDeliveryWait` binding
fields. Optional supplied testimony is independently sealed and checked before every early
replay; it must never silently change a consumed declaration. A manual `ResolveDeliveryWait`
after an immutable `NEEDS_AUTHORIZATION` handling preserves that old handling and appends
the final `RESOLVED` report through the existing `wait-handling-resolutions` binding alias.
It cannot overwrite the earlier handling or report a consumed resolution as still pending.
Investigation and resolution must carry equal complete workspace-refusal evidence.

Read-side engineering history and the Console show the specific platform admission reason,
retained progress/draft, original failure and ordinary work cost. Static JSON Schemas and
their embedded copies must preserve the optional-field omission form and action/evidence
cross-field guards through canonical regeneration. Old records keep their bytes and SHA.

## Validation matrix

| Case | Required result |
| --- | --- |
| Frozen progress16 + exactly approved full draft24 at original source | Gate accepts without editing files or progress |
| Newly accepted progress after that binding | Ordinary exact progress inventory; no inherited draft allowance |
| Added/removed/body/mode/ignored file, changed source/permissions/claim | Refuse before provider; preserve complete scene |
| Exact trusted pre-provider refusal, unique sealed route, matching claim/Context and gate replay | Typed investigation and one exact engineering action |
| Missing declaration, Product-only submitter, unsupported revision/manifest or altered consumed testimony | Refuse; no inferred historical revision or recovery authority |
| Same Task deletion with a declaration subtree | Complete typed scope/key/inventory closure; foreign or unknown child refuses |
| Generic interruption, different diagnostic, native/tool/start/accepted contradiction or unknown adapter | No recovery authority |
| Exact approval within budget | Ordinary work+1, new claim/Context/Run, same Task and branch |
| Stale proof, active owner, changed capture/baseline or exhausted budget | Refuse with no replacement work |
| Exact consumed decision replay / unconsumed stale replay | No extra work / reject |
| New Coder returns candidate | Independent QA and Reviewer at identical SHA still required |

Good: preserve accepted steps and the entire separately authorized draft, then create one
fresh ordinary execution after exact engineering approval. Base: an ordinary accepted
progress with no larger approved draft keeps the previous exact path check. Bad: erase the
failed invocation, synthesize process-stop evidence, change the progress declaration or
permit arbitrary dirty files because some earlier baseline existed.

Required tests include real gate RED→GREEN with negative inventory/source/permission/
progress cases; supported adapter proof and contradiction cases; Pydantic/static Schema
parity and old wire hashes; public Handle/queue atomicity, budgets and replay with isolated
MySQL; and a public same-Task fixture reaching independent Coder→QA→Review. Fixture verdicts
are not acceptance of real K1.

## Existing data and rollback

存量数据处置：original K1 work8 and its immutable FAILED/WORK_INTERRUPTED start/outcome stay
intact. The current accepted progress and all24 retained draft files stay unchanged during
maintenance. Use fresh public inspection and exact engineering Handle/Continue after a
controlled deployment; no direct production SQL, native stop backfill or Task recreation.
Audit original records and complete workspace before/after deployment, and distinguish the
runtime platform revision from K1's frozen target source. A later Coder may lawfully change
drafts through its normal policy-bound execution; maintenance must not edit that checkout.

Rollback only at a controlled idle boundary. Previous executables may not recognize new
resolution kinds, so preserve new records and use a compatible forward repair or an
inspection-only service until their work is settled. Do not delete evidence to make an old
binary read the store.
