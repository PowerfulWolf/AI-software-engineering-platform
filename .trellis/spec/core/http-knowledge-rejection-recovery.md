# HTTP knowledge semantic rejection recovery

## Scope and failure mode

Applies to safely sealed RETURNED knowledge intent/assessment results that fail exact READ
membership or redaction semantics, including HTTP-only and HTTP-to-native fallback routes.
K1's successful HTTP intent could not satisfy the old per-phase native-stop requirement.
The model's changed chunk_id was correctly rejected, but recovery lacked an observation and
retained a generic PLATFORM_BUG wait. Keep that history; do not correct the old citation.

## Signatures and ownership

```python
derive_rejected_assessment(records_root: Path, binding: KnowledgeRunBinding)
    -> RejectedKnowledgeAssessment
rejected_assessment_for_work(*, records_root, task, item, scope, requirement_id)
    -> RejectedKnowledgeAssessment | None
rejected_knowledge_evidence(*, observation, task, item, step, scope, state,
                          route_root, queue, artifacts, git, ...)
    -> RejectedKnowledgePreparationEvidence
DeliveryWaitService.inspect(command: InspectDeliveryWait) -> DeliveryWaitInvestigation
DeliveryWaitService.handle(command: HandleDeliveryWait) -> DeliveryWaitHandling
MySqlRoleQueue.resolve_wait(resolution: DeliveryResolution) -> QueuedWorkItem
```

Knowledge observation remains a deterministic read of existing records, not retry authority.
The optional `RejectedKnowledgePreparationEvidence.current_draft_sha256` is omitted when
absent, preserving old wire bytes and digests. It names a complete current draft observation;
it is not a historical after-inventory or native-stop substitute. Existing proof fields bind
the original wait, current Task/WorkItem and exact source facts.

## Contracts

- Reopen both exact RETURNED phases and independently stored admission/completion records;
  validate claim, request digest, role, phase, source, Context, result and completion time.
  Every admitted route must be closed exactly and belong to the same invocation in route order.
- Native executions keep actual runner-owned stop and complete owned-session emptiness proof.
  HTTP execution uses its exact synchronous HTTP receipt and sealed result; success/fallback
  must agree with the actual route receipts. Local HTTP completion does not assert remote
  process termination. Missing/unknown/foreign/tampered records remain nonrecoverable.
- Keep exact READ membership, snapshot/source visibility, redaction and request reconstruction.
  Never alter an old citation, RETURNED bytes, intent, outcome, diagnostic or original wait.
- Existing INVALID_OUTPUT + unique rejection URI remains valid. A legacy PLATFORM_BUG wait
  with no rejection URI may offer the same resolution only after fresh full independent
  derivation proves this exact original WorkItem/claim's semantic rejection. No text matching,
  classification overwrite or generic platform-error retry is permitted.
- The collector must prove no main/provider/tool/output/accepted artifact for the rejected
  WorkItem and its carry claims. Earlier Task main runs and accepted progress remain valid.
  No live owner, late main output, unresolved execution or foreign scope may be bypassed.
- Current files/modes and full ignored/untracked inventory must equal an authenticated current
  execution input. A historical seed inventory does not authenticate later accepted progress.
  If no complete historical after-inventory exists, collect a separate current complete draft
  observation bound to the latest accepted progress and real SQL publication. Only a fresh
  exact ENGINEERING operator decision can accept that present draft as the successor input.
  Preserve the distinction between accepted progress and newly approved current bytes.
- Inspect and final resolution independently revalidate the same original wait digest, Task
  intent/revision/source, Step, proof, complete inventory, no-main facts and frozen budget.
  Publishing an exact engineering decision precedes consumption. Consume one ordinary work
  allowance once, close the old item, publish a new work identity and require a new real claim,
  Run and Context. No transient refund, timeout expansion or role verdict is granted.

## Current complete draft acceptance

```python
collect_current_draft(*, state, task, item, observation, scope, queue, artifacts,
                      git, permissions, capture, inventory, source)
    -> RejectedKnowledgeCurrentDraft
read_current_draft(state: Path, identity: str) -> RejectedKnowledgeCurrentDraft
RejectedKnowledgeDraftAdmission(state, git, task_reader, claim_reader, retry_reader)
    .authorize(request: AgentRequest, workspace_root: Path) -> None
MySqlRoleQueue.rejected_knowledge_retry(work_item_id: str)
    -> RejectedKnowledgePreparationEvidence | None
```

`manager/rejected_knowledge_draft.py` stores `RejectedKnowledgeCurrentDraft` as an
append-only `state/rejected-knowledge/current-drafts` record keyed by its canonical
`record_sha256`. It binds `scope`, Task intent/snapshot, exact waiting WorkItem/checkpoint,
semantic rejection observation, complete accepted `CoderProgressArtifact`, its unique SQL
`AcceptedRoleArtifact` publication, original `DeliveryInvocationStart/Outcome`, real
`ExecutionCaptureStart/Stop`, complete Context digest, permissions, complete
`CapturedMutations` and `WorkspaceMutationInventory`. It records current observation only;
the investigation provides observation time. It must not fabricate a past after-inventory.

Reopen all original journal, Context, artifact and claim sources. Require the latest active
published progress, prior successful main Coder and actual completed owned-session stop,
same Task/source/worktree/permissions, unchanged HEAD and index, and exact changed paths.
The complete current capture must agree with current file bytes/modes/inventory and remain
stable across inspection. This only proposes a present input; it does not assert those
bytes equal the unsealed historical post-progress state. Candidate reports or conflicting
progress/publication identities cannot be repurposed as this approval.

For this optional mode `HANDLE_DELIVERY_WAIT` must return `NEEDS_AUTHORIZATION`, even if
frozen organization policy allows ordinary wait resolution. Only an explicit
`RESOLVE_DELIVERY_WAIT` with `resolution_kind=RETRY_REJECTED_KNOWLEDGE_PREPARATION`, the exact
fresh `proof_sha256` and trusted `ENGINEERING` principal accepts the current complete draft.
The resolution must use `authorization_source=engineering_operator_decision`; an automatic
`EngineeringAdmission` is insufficient. This does not approve candidate/QA/Review output.

Before consumption reopen the exact proof and compare all current source facts and complete
capture/inventory. Under SQL fences keep the active progress, close only the old waiting item
and debit one ordinary work attempt. On the fresh successor claim, revalidate the consumed
decision, snapshot, progress, worktree and full file/index/ignored inventory before provider
admission. After the first real successor main start, ordinary continuation facts govern
legitimate new Coder edits; old engineering approval is not reusable for another execution.

Deletion must discover exact typed `carry-refusals` and `current-drafts` records in the
shared state directory. Validate complete Task/Requirement/scope/key/nested lineage and
retain foreign scoped files. Unknown, corrupt, symlinked or miskeyed children refuse cleanup;
never recursively delete an unchecked shared directory. For deletion, use the explicit historical
reader to rederive complete immutable receipt/READ/digest semantics. Historical ownership must
not depend on today's boot identity or whether an unrelated process reused the original PID.
Execution recovery keeps the current owned-session liveness gate; the historical reader grants
no execution authority. Current inactivity remains the responsibility of the separate
Requirement deletion guard, not a historical record reader.

## Validation matrix

| Case | Required behavior |
| --- | --- |
| HTTP intent + HTTP/native assessment fallback; exact invalid citation | Revalidatable rejection observation; original returned bytes retained |
| Both phases successful HTTP; semantic rejection | Same route-aware complete proof, no native stop fabrication |
| Native source | Original real owned-stop requirements unchanged |
| Legacy PLATFORM_BUG, exact sealed rejection, current valid progress | Fresh proof and exact same-Task resolution; old wait preserved |
| Generic PLATFORM_BUG without proven semantic rejection | No semantic resolution |
| Missing/unknown/foreign/late/duplicate route or mismatched result | Refuse before retry authority |
| No historical after-inventory; complete current draft + exact operator acceptance | Bind present bytes, preserve accepted progress; same-Task ordinary successor |
| Automatic policy tries to accept a present draft | NEEDS_AUTHORIZATION; no work replacement |
| Current byte/mode/index/ignored/source/progress drifts after proposal or consumption | Refuse before provider; preserve scene |
| Replayed decision | Same successor; no extra budget debit or model call |
| Active owner, raw/main output for rejected work, stale source or exhausted budget | Refuse unchanged |

## Good, base and bad

Good: exact HTTP-completed semantic refusal is independently verified, an engineering decision
binds the retained 21-file progress, and a fresh claimed knowledge Run retries on the same Task.
Base: native-only proofs and old serialized digests still work. Bad: delete a native guard,
pretend HTTP means remote stopped, trust error text, repair historical identifiers, reset a
Task, create a new public Requirement, or accept arbitrary current dirty files.

## Required verification

- Real structured HTTP/native fixtures at derive_rejected_assessment and consultation seam,
  with the production chunk_id mismatch and negative receipt/identity/time tests.
- Domain, collector and final MySQL-fence tests for the persisted generic wait, full accepted
  progress/current draft approval, no-main and idempotent one-time ordinary-work accounting.
- Exact draft approval must reject automatic policy, stale proof and same-path byte, mode,
  index, ignored-file, source, progress/publication or claim drift, including after consumption.
- Physical deletion closure must include same-scope carry/draft files and retain foreign files.
- Identity-checked isolated MySQL supervisor replacement through separate Coder/QA/Reviewer.
  Run tests sharing that database serially. Fixtures do not establish production K1 DONE.
- Scoped Ruff/strict Mypy, relevant schema parity, immutable-store regressions and diff checks.

## Existing data and rollback

No direct SQL migration, Task reset, old outcome/READ correction or budget refund. After an
idle controlled service upgrade, inspect the original K1 wait using its current exact public
identities. Only a complete fresh proof may authorize the existing engineering resolution.
If inventory or another prerequisite still fails, report that specific remaining blocker;
do not claim HTTP support alone guarantees recovery. Preserve all first-Coder progress and
original failures. Runtime replacement does not rebase the approved target repository.

Rollback only while no execution is active; retain compatible proof/decision readers and all
durable history. Published same-Task decisions are not undone by reverting code.

## Wrong versus correct

Wrong: compare today's 21 dirty path names to accepted progress and claim the original seed
inventory proves all current bytes, or automatically accept a new snapshot under old policy.
Correct: preserve the progress and original failures, seal today's complete capture with its
real lineage, require a new exact engineering decision, then recheck the approved bytes before
the successor provider starts.
