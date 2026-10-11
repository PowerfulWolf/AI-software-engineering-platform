# 已停止但产出被拒的 Coder 续跑

## Scope / trigger

处理非终态Task中真实completed、已有完整SUCCEEDED Coder progress，但仅因精确执行序号
语义错误而未进入交付checkpoint的情况。它不是中断、provider transient、有效progress、
candidate或verdict。禁止改写原产物、停止记录、publication receipt或失败历史。
其它INVALID_OUTPUT、权限违规、候选、QA/Review产出不能从本契约获得继续权。

## Signatures and records

```python
AgentResult.validate_current_output() -> None
DeliveryWaitFactCollector.collect(task, step, guard) -> None
capture_rejected_checkpoint(*, state, task, step, outcome, start, stop, git, validate_inputs) \
    -> RejectedCoderOutputCheckpoint
read_rejected_checkpoint(state, work_item_id) -> RejectedCoderOutputCheckpoint | None
verify_rejected_workspace(record, git, task) -> None
MySqlRoleQueue.resolve_wait(resolution: DeliveryResolution) -> QueuedWorkItem
MySqlRoleQueue.rejected_output_retry(work_item_id) -> RejectedCoderOutputEvidence | None
MySqlRoleQueue.rejected_output_artifact_ids(task_id) -> frozenset[str]
RejectedCoderOutputAdmission.authorize(request, workspace_root) -> None
ConfiguredDeliveryRouteAdapterFactory.wrap_initial_workspace_admission(wrapper) -> factory
workspace_admission_for_request(admission, request) -> InitialWorkspaceAdmission | None
```

Implementation: `manager/rejected_output_checkpoint.py`, `manager/wait_fact_collection.py`,
`manager/delivery_wait.py`, `domain/delivery_resolution.py`, `work_queue/execution_store.py`,
`work_queue/worker.py`, `manager/production_backend.py`, `agents/workspace_admission.py`.
Public operations remain `HANDLE_DELIVERY_WAIT` / `RESOLVE_DELIVERY_WAIT`; there is no
new raw store endpoint, arbitrary process-stopped Boolean or shell permission.

`sidecar/state/rejected-coder-output` uses immutable `KnowledgeRecordStore` namespace
`rejected-checkpoints`, original work item ID as key. `RejectedCoderOutputCheckpoint`
contains task snapshot/step digest, original complete invocation outcome, original
capture start and real completed stop, complete `CapturedMutations`, after inventory
and `checkpoint_sha256`. Original before inventory remains in capture start.

Compact `RejectedCoderOutputEvidence` binds EngineeringScope, native child requirement_id,
task/work item, original lease/claim digest/attempt/dispatch sequence, queue checkpoint,
previous Run/Context, source, invocation start/outcome digests, rejected artifact identity/digest,
`rejection_code=PROGRESS_SEQUENCE_MISMATCH`, expected/reported sequences, process stop,
capture/inventory/checkpoint digests and `budget_source=frozen_work_attempt`.
Expected sequence equals original execution attempt; reported differs. Queue checkpoint is
an independent field. Evidence never changes the rejected artifact's sequence.

Investigation/resolution add optional `rejected_output`, excluded when None so historical
canonical hashes remain unchanged. `RETRY_REJECTED_CODER_OUTPUT` is permitted only with
its matching complete evidence, no missing proofs and no interruption/transient cause.
Static JSON Schemas and regeneration guards must agree with domain validators.

## Capture and validation contract

1. Own the idle Task process lock and verify the current waiting queue boundary, frozen
   Task intent/revision, exact original invocation/claim/permissions/scope. Expired lease
   alone is not stop proof. The owned completed stop must bind the original capture start,
   same request/Run, returncode0 and output_present=true, with no timeout/transient cause.
2. Only SUCCEEDED `coder-progress` with sequence mismatch is eligible. Verify ordinary
   output source/context/producer, direct parent/supersedes, exact changed files and
   allowlisted complete workspace. A publication receipt may have been written before
   the final semantic check; that receipt does not mean a StateEvent adopted the output.
   Any actual checkpoint adoption, completed role advance, candidate or independent
   verifier output prevents this path.
3. Capture tracked/untracked regular text changes with full before/after bodies. Compare
   original before inventory to current after inventory, authorize all changes including
   ignored noncache paths, and require noncache changes covered by the capture or exact
   legitimate inherited progress. Reuse existing cache/policy rules, not a new allowlist.
   HEAD/branch/index, root, denied/protected paths, symlinks, secrets and byte budgets retain
   existing Git/mutation validation. Recheck full inventory and queue facts after capture.
4. Seal an independent record. Identical read/prepare is idempotent; changed original
   facts or current workspace reject, preserving the prior record and all files.

## Atomic decision and execution contract

`DeliveryWaitService` re-collects exact proof under lock before sealing the engineering
decision. Existing frozen engineering authority or an explicit authorized engineering
principal may consume it; a product checkbox or model opinion is not authority.

`MySqlRoleQueue.resolve_wait` uses existing task lock → queue authority → Task row
fences. Revalidate original waiting identity/disposition, source/current step, scope,
claim and no ACTIVE Task claim. Recheck no StateEvent adopted the rejected ID and
no completed original work. Atomically close the old work, append WAIT_RESOLVED with
full compact resolution, increment normal work attempt, and create a fresh successor
work/Run/claim. There is no transient refund or changed Task/source/branch/permission.
Exact replay returns the first consumption; changed proof/actor/kind rejects.

Only a consumed decision can retire the exact rejected artifact from execution reads.
`AcceptedArtifactStore` retains original disk bytes and SQL publication receipts;
it filters only that ID. Do not apply a supersedes ancestor closure or drop the valid
previous checkpoint. Historical UI/evidence readers keep all original records.

The production selector resolves `ConditionalWorkspaceAdmission` per current request.
No matching consumed successor returns original delegate or None, preserving the
normal dirty-workspace checks. A selected rejected-output admission requires the exact
new work identity/attempt/source/permissions, new Run/Context/lease and unchanged
complete captured workspace; missing authority after selection must reject, not no-op.
New Coder context receives stable rejection facts, not raw exception authority. Its new
progress/candidate still follows normal schema, workspace, lineage and QA/Review gates.

## Frontend / user contract

Current handling explains that the report was not accepted, execution really ended,
complete files were preserved, and a new Coder call consumes one remaining work allowance.
The explicit action is `保留进度并重新提交开发报告`; no old-result replay button is shown.
Before investigation, invalid-output/platform-bug waits use `让平台处理产出校验` instead of
claiming that a completed call was interrupted.
Current proof/evidence must bind the selected Project, native child/current Task, work item,
source, queue checkpoint, Run and all invocation/stop/inventory digests. Stale callbacks
recheck these exact facts and send no mutation. Hashes remain secondary engineering detail.
Investigation, handling, resolution and copied reports preserve Chinese reasons and
complete history, and never imply independent QA/Review passed.

## Validation matrix

| Case | Required result |
| --- | --- |
| attempt4, queuecheckpoint8, rejected progress9, real completed stop, legal full draft | Independent receipt; exact fresh execution permitted |
| New current output progress4 | Normal accepted checkpoint, never rejected recovery |
| Old sealed progress9 | Read/hash valid; cannot replay or be selected as a usable checkpoint |
| Live/unknown process, missing start/outcome/stop, scope/claim drift | Preserve wait, no capture authorization/consumption |
| HEAD/index/branch/source/complete inventory or permissions drift | Reject without clearing files |
| Unauthorized ignored mutation, protected path, symlink or secret | Reject full capture; no partial acceptance |
| Candidate/verdict/StateEvent consumption or completed original work | Reject this capability |
| Exhausted work budget | No new attempt and no transient refund |
| Exact decision replay / changed decision | One consumption / reject conflict |
| No current consumed successor decision | Original workspace admission/default dirty gate applies |
| Evidence disappears after selection | Fail closed before model call |
| UI foreign/missing/stale evidence | No continue control, detached callback makes zero writes |

Good: a new claim reuses the complete legal draft and valid earlier progress, then generates
a fresh exact report. Base: normal progress never enters this route. Bad: correct sequence9
in old JSON, pretend completed was timeout, refund work as provider fault, or mark Task DONE.

## Required incremental tests

`tests/manager/test_rejected_coder_output.py` must first reproduce stopped rejected output
with no usable public decision, then cover full capture and negative drift/authority cases.
Queue integration must use a real isolated test MySQL database, serially: exact consume,
normal-work accounting, old owner refusal, replay/conflict and artifact filtering. Admission
must exercise real provider dirty checks with no consumed decision and exact successor
reopen/authorization. `tests/team_view/engineering-wait.test.cjs` and its Chrome counterpart
cover visible plan, exact evidence, old closures and complete history. Include public
Continue/adoption → HANDLE → resolve → claimed new Coder, retaining same Requirement/Task.

## Existing data, rollout and rollback

Target K1 Task `task_recovery_8ca06fa0aec236ab940597ad1482bfc8`, attempt4/revision8,
rejected `art_coder_42479ee20e471e903336aa3db579b4f4`, native child
`delivery_dc5cf0aee44e5ffe0cb600557204e0d0`. Its previous recovery Operation failed before
writing the requirement cursor. First adopt the exact existing approved recovery Task's
real queue wait via public Continue, without another model call; then Handle the current
wait, inspect the exact saved plan and use authorized resolution. No direct database
update or original history migration. Record actual before/after IDs, budgets, workspace
inventory and immutable records in task verification when executed.

Deploy only while all Operations/claims/tools are idle, using controlled restart. Before
consumption code can roll back while retaining audit. After new resolution consumption,
keep compatible readers/writers and prefer forward fixes; do not run a binary that cannot
understand the new decision, remove records or return to old usable-artifact selection.

## Failure analysis and prevention

B/D/E: provider success, artifact publication and delivery-checkpoint adoption were treated
as interchangeable facts; schemas/prompts did not bind the exact semantic sequence, tests
stopped at individual components, and recovery only covered absent output. Keep live output
admission before publication; keep rejected facts distinct from unknown interruption; test
the public path and old durable records, including a published-but-never-adopted artifact.
