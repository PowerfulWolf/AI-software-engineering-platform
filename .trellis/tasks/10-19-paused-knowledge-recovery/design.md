# Paused knowledge preparation: forward design for review

Status: root reviewed and approved; producer implemented and focused verification passed.
Stored K1 rescue is a separate engineering decision and is excluded from this design.

## Reproduced failure and scope

The new focused regression drives real `ServicePauseControl` →
`FallbackStructuredModelClient` → `KnowledgeConsultationService` /
`KnowledgeInvocationJournal` → `RetryingOrchestrator._knowledge_failure` →
`WorkerLease` / `WorkerDeliveryFailureControl.wait` → `DeliveryWaitService.inspect`.
Only the queue persistence and never-admitted provider are fake ports. Git, SQLite Task,
knowledge records, claim, failure routing, wait publication and collector are real.

Command (maintenance checkout, explicit source path):

```text
PYTHONPATH=/tmp/ase-fix-legacy-ignored/src:/tmp/ase-fix-legacy-ignored /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q tests/manager/test_paused_knowledge_recovery.py
```

Observed: `1 failed in 0.90s`; exact assertion reports
`executions=0, evidence=(), missing=(INVOCATION_UNRECORDED,)`.
Earlier assertions prove provider port calls=0, exact persisted claim/binding,
WAITING_DEPENDENCY with lease released, and unchanged Task/events/draft bytes.
Ruff check/format and `MYPYPATH=src .../python -m mypy --strict <new test>` pass.

The existing collector correctly refuses missing execution facts. The defect is the
producer dropping the positively observed pre-admission pause, then routing the phase as
an undifferentiated main-role pause. This design adds a precise prospective fact rather
than treating `SERVICE_PAUSED + executions=[]` as evidence.

## Minimal contracts

Add an independent `StructuredPreAdmissionPauseReceipt` in a small Agents module. It is
neither a `StructuredExecutionAdmission` nor a `StructuredNativeNotStartedReceipt`.
Do not extend the legacy `StructuredObservationRecord` union or fabricate an admission.

```python
class StructuredPreAdmissionPauseReceipt(DomainModel):
    kind: Literal["structured_pre_admission_pause"]
    schema_version: Literal["v1"]
    origin: Literal[
        "fallback_before_route",
        "native_client_entry",
        "responses_client_entry",
        "responses_before_transport_admission",
    ]
    request_sha256: Sha256
    timeout_seconds: int  # 1..86400
    phase: CallPhase
    role: TeamRole | None
    invocation_id: ObservationId | None
    selected_call: StructuredCallIdentity | None
    operation_id: NonEmptyStr
    pause_request_id: NonEmptyStr
    pause_instance_id: NonEmptyStr | None
    pause_requested_at: AwareDatetime
    refused_at: AwareDatetime
    receipt_sha256: Sha256

ServicePauseControl.request_snapshot() -> PauseRequest | None
require_structured_admission_open(
    *, origin, instructions, input_payload, output_schema, timeout_seconds,
    input_images=(), role=None, invocation_id=None,
) -> None

class StructuredAdmissionPaused(StructuredModelError):
    receipt: StructuredPreAdmissionPauseReceipt
    def with_context(self, context: str) -> StructuredAdmissionPaused: ...

KnowledgeInvocationOutcome.pre_admission_pause:
    StructuredPreAdmissionPauseReceipt | None = Field(
        default=None, exclude_if=lambda value: value is None)

class KnowledgePreparationPaused(StructuredModelError):
    outcome: KnowledgeInvocationOutcome
    def with_context(self, context: str) -> KnowledgePreparationPaused: ...

read_paused_preparation(records_root: Path, outcome_sha256: str)
    -> KnowledgeInvocationOutcome
```

`request_snapshot` freezes the actual current Host pause epoch while holding its existing
lock, even during the grace window. `due_request()` is not suitable: pre-admission closes
immediately, before the grace deadline. Cancellation after observation does not erase that
epoch. The helper uses only a real active `ServicePauseScope` and its control snapshot;
provider text, generic exceptions and externally supplied booleans cannot produce a receipt.
No active pause means the helper returns without changing legacy execution.

For `fallback_before_route`, `selected_call=None`, the invocation ID is the actual new
Fallback invocation ID, and no provider/model/route/admission is claimed. For the other
origins, `selected_call` is the actual currently bound call identity when one exists;
its request/role/phase/invocation identity must agree. Direct structured clients without
Fallback can retain `selected_call=None`; a knowledge receipt still binds the exact full
request, role/phase and intent, not a fabricated route. `refused_at >= pause_requested_at`.
There are no prompt, payload, credentials, endpoint, stdout/stderr, PID or stop claims.

The helper replaces all four actual pre-admission pause checks. It computes the shared
request digest (including verified image digests) from exact arguments. Exception subclasses
preserve their receipt/outcome through `with_context`; generic `StructuredModelError` retains
its current behavior. Receipt construction/publication errors fail closed as observation /
knowledge uncertainty, not provider fallback or retry.

## Knowledge publication and existing native facts

When the Journal catches `StructuredAdmissionPaused`, it independently validates receipt
request SHA, timeout, role, `knowledge_<phase>`, intent time and the original current claim.
It stores the receipt under lane namespace `structured-admission-pauses`, keyed by its SHA,
before publishing the FAILED/SERVICE_PAUSED outcome containing that optional receipt.
It then publishes `knowledge-pause-intents/<outcome_sha256>` as a content-bound lookup of
the full original intent. All writes use the existing real execution guard / owner fence;
partial publication remains uncertainty. Reopening independently rereads receipt, original
intent and outcome and compares complete typed bytes/SHA. Empty `executions` alone is never
the positive fact.

The existing native runner race has a different honest fact: a real structured admission
followed by `StructuredNativeNotStartedReceipt(failure_kind=service_pause_admission_closed)`.
Preserve that pair. A newly written Journal may publish the same paused-preparation index
and typed error for this pair after complete independent validation. Do not replace it by
the new pre-admission receipt. The no-start resume path accepts no native stop, HTTP call,
incomplete admission or other started route in the paused phase. Earlier fallback attempts
with actual execution mean this path is unavailable, even if the last route was refused.

Earlier completed knowledge phases stay real facts, not main-role invocations. Unknown,
pending, corrupt or failed earlier calls in the same claimed preparation cannot be hidden.
The minimum first implementation may conservatively refuse such mixed histories; no
automatic recovery for them is promised by this task.

`KnowledgePreparationPaused` wraps only a revalidated prospective refusal or the exact
native admission-closed pair. Replay raises the same typed paused error from the original
outcome without invoking a model. `_knowledge_failure` handles that subclass before generic
SERVICE_PAUSED and raises `ServicePauseRequested(evidence_ids=(
"knowledge-pause://" + outcome.outcome_sha256,))`. The Worker keeps its existing fenced
SERVICE_PAUSED wait and releases the real claim.

## Public recovery and queue consumption

Add an absent-by-default `knowledge_pause: KnowledgePreparationPauseEvidence | None` to
`DeliveryWaitInvestigation` and `DeliveryResolution`. Its exact fields are in the companion
contract draft. It is mutually exclusive with all other invocation/verifier/retry proofs;
it can authorize only `RESUME_UNINVOKED` for SERVICE_PAUSED with exactly one matching
`knowledge-pause://<outcome_sha256>` evidence ID.

The collector rereads the independent index/intent/outcome/receipt(s), frozen snapshot and
real historical claim. It checks Team/Project/Requirement/Repository/Task/role, repository
scopes, exact source and current checkpoint, attempt/dispatch, Run/Context, request and
receipt SHAs. Use `claim_identity_sha256`, including repository scopes and excluding only
the existing mutable fields. Verify the original WorkItem has no main invocation/result,
accepted current output, continuation/capture or provider facts contradicting no-start;
do not equate an absent current Run filename with absence of an execution for that claim.

The Task lock, queue authority and MySQL Task fence are retained. Resolve recollects and
compares the exact proof; SQL consumption checks the original claim, current waiting
generation, Task intent/revision/attempt/source and no active claims again. A consumed
decision changes only the current WorkItem to READY and dispatch_sequence+1, retaining the
same Task, WorkItem, attempt, frozen budgets, source, branch and accepted draft/progress.
The next execution has a fresh claim, Run and Context. No refund, retry failure, new work
reservation, source change or automatic verdict is created. Replay is idempotent.

This uses existing `HANDLE_DELIVERY_WAIT` / exact `INSPECT` → `RESOLVE` public operations.
Frozen engineering policy or an actual exact engineering principal remains necessary;
the receipt is evidence and grants no authority. Current permission/budget/final-input
checks remain in force. No new generic retry button or control API is needed.

## Actual pause entrances and boundaries

| Actual entrance | Durable fact | New same-attempt no-start path |
| --- | --- | --- |
| Fallback before selecting the first route | New refusal, selected_call=None | Yes after all claim/input checks |
| Native client entry before structured admission | New refusal, actual selected identity if present | Yes |
| Responses entry / before HTTP admission | New refusal at the exact guard | Yes |
| Native admission exists; pause prevents Popen | Existing admission + exact native not-started pair | Yes for newly indexed validated outcome |
| Native process actually started and was stopped | Existing actual native stop/session proof | No; preserve real stop and ordinary-work engineering route |
| HTTP already posted / earlier route executed | Existing real local round-trip or uncertainty | No; no invented remote stop or whole-call no-start |
| Generic SERVICE_PAUSED or legacy empty executions | Original failure only | No |
| Pause requested after a guard but provider actually admitted | Actual admission/completion facts | No pre-admission receipt for that admission |

## Schema, tests and compatibility

Add a standalone raw-receipt Schema and update `knowledge-invocation-outcome` plus all
embedded copies and the three canonical wait/Console/settlement schemas through their
generators. The raw receipt is not added to `knowledge-execution-record` or the old
structured-observation union. None fields must be omitted from every nested `model_dump`
and `to_wire`, preserving old hashes, store keys and exact serialized bytes. Global model
validators continue reading old outcomes without retrospectively requiring a receipt.

Required tests: real positive preparation→wait→public collector; generic pause/empty list
negative; each exact early guard; native admission-closed pair; admitted native stop and
HTTP round-trip not no-start; missing/corrupt independent receipt/index; wrong claim/source/
scope/phase/role/Run/Context/request/Task; alias/main-start contradictions; replay and owner
loss/publication failure; Task/draft/budget preservation; consumed exact queue decision and
fresh claim; old absent-field wire/digest and full generated Schema guards.

## Confirmed ownership

- run6: new raw receipt module, pause snapshot accessor, four structured-client guard sites,
  Journal optional field/publication/replay/typed error and failure router, focused new tests;
  read-only selected-call getter; task design and core spec/index.
- root: domain `KnowledgePreparationPauseEvidence`, wait collector and public resolution,
  queue consumption/composition, generator/Schema synchronization, stored-data disposition,
  integration, controlled deployment and real K1 recovery.
- native_owned: independent contract/code/final review; no implementation verdict self-approval.

Production producer edits are complete; consumer and integration remain root-owned.
Rollback retains every old/new
immutable receipt and reader; deploy only at a verified stopped/idle role boundary. Do not
edit stored K1 empty-execution outcome, old investigation, Task, budget or accepted progress.
