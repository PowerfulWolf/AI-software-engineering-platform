# Candidate executable spec: prospective knowledge admission pause

Proposed destination after review: `.trellis/spec/core/knowledge-preparation-pause.md`.
This draft grants no new production capability and makes no historical no-start assertion.

## Scope and producer signatures

Use only a trusted Host pause observed before structured route/transport admission, or an
independent existing native admission-closed receipt before Popen. Keep knowledge preparation,
main role execution, result publication and accepted progress separate.

```python
ServicePauseControl.request_snapshot() -> PauseRequest | None
require_structured_admission_open(
    *, origin: PreAdmissionPauseOrigin, instructions: str,
    input_payload: Mapping[str, object], output_schema: Mapping[str, object],
    timeout_seconds: int, input_images: tuple[Path, ...] = (),
    role: TeamRole | None = None, invocation_id: str | None = None,
) -> None
read_paused_preparation(records_root: Path, outcome_sha256: str)
    -> KnowledgeInvocationOutcome
knowledge_preparation_pause_evidence(
    *, outcome: KnowledgeInvocationOutcome, task: Task, item: QueuedWorkItem,
    source_revision: str, scope: EngineeringScope, historical_claim: QueueClaim,
    delivery_requirement_id: str,
) -> KnowledgePreparationPauseEvidence
```

The independent raw receipt has kind/version, exact origin, request SHA/timeout/phase/role,
optional actual invocation/selected call, actual operation and pause epoch IDs/times,
refusal time and SHA. Fallback before route selection requires selected_call=None. A selected
identity, when present, must match request/phase/role and actual invocation. It has no PID,
admission, process stop or remote-completion fields. Trusted scope/control snapshot is the
only producer. Generic provider SERVICE_PAUSED errors cannot fill it.

## Delivery evidence fields

```python
class KnowledgePreparationPauseEvidence(DomainModel):
    scope: EngineeringScope
    requirement_id: NonEmptyStr
    delivery_requirement_id: NonEmptyStr
    task_id: TaskId
    role: Literal[AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER]
    work_item_id: NonEmptyStr
    original_lease_id: NonEmptyStr
    original_claim_sha256: Sha256
    original_attempt: int  # >=1
    original_dispatch_sequence: int  # >=0
    checkpoint_sequence: int  # >=0
    previous_run_id: RunId
    previous_context_manifest_id: ContextId
    source_revision: NonEmptyStr
    snapshot_sha256: Sha256
    phase: Literal["intent", "assessment"]
    intent_sha256: Sha256
    outcome_sha256: Sha256
    request_sha256: Sha256
    proof_mode: Literal["pre_admission_refusal", "native_admission_closed"]
    pre_admission_pause_sha256: Sha256 | None  # absent when None
    execution_record_sha256s: tuple[Sha256, ...]
```

`pre_admission_refusal` requires a positive independently persisted raw receipt and no
execution admissions in this paused phase; execution_record_sha256s is empty because no
admission occurred, not as proof by itself. `native_admission_closed` requires the exact
independent native admission + not-started pair with
failure_kind=service_pause_admission_closed and no other route, HTTP or process stop.
It has no raw pre-admission receipt. Both bind the complete original claim and current
Task/source/checkpoint and preserve the original knowledge/Requirement identities.

## Publication and consumption

The lane persists raw `structured-admission-pauses/<rawSHA>` before the full FAILED outcome
links its optional pre_admission_pause. The root knowledge store publishes
`knowledge-pause-intents/<outcomeSHA>` only after complete validation. All are immutable,
atomic, typed, SHA-verified and synchronously guarded; failure is uncertainty, not fallback.

Typed `KnowledgePreparationPaused(outcome)` survives context wrapping and replay and raises
`ServicePauseRequested(evidence_ids=(knowledge-pause://<outcomeSHA>,))` through the existing
knowledge failure router. The actual Worker wait releases the Lease.

`DeliveryWaitInvestigation.knowledge_pause` and `DeliveryResolution.knowledge_pause` are
optional and omitted when None. They are exclusive with original invocation authority,
verifier/capacity/retry/other knowledge/capture proofs. The matching wait is SERVICE_PAUSED,
its evidence tuple contains exactly the bound knowledge-pause URI, main start/outcome and
accepted output are absent, and the only permitted decision is RESUME_UNINVOKED.

Investigation and resolve read original independent bytes and claim again. Consumption is
fenced on Task lock → queue authority → MySQL Task row, current original claim/dispatch,
Task intent/revision/attempt/source, no active claim and no contradictory main-role output.
The same WorkItem becomes READY with dispatch+1; no attempt/refund/retry_failure/budget or
source change. Dispatcher issues a fresh claim/Run/Context. Replay consumes once.

## Validation matrix

| Facts | Expected result |
| --- | --- |
| Trusted first-route refusal; exact independent bytes/claim; main uninvoked | Same-attempt RESUME_UNINVOKED |
| Exact native admit + real admission-closed not-started | Same-attempt RESUME_UNINVOKED |
| SERVICE_PAUSED + legacy empty executions; no new receipt | Remain waiting; no retroactive proof |
| Provider raises generic SERVICE_PAUSED despite no active Host pause | Remain waiting; no receipt |
| Native actually started / only HTTP local completion / earlier admitted route | No no-start resume; preserve actual facts |
| Pending/corrupt/foreign independent record or failed publication | Uncertainty; zero further provider calls |
| Wrong role/phase/claim/scopes/Task/source/Run/Context/request/checkpoint | Reject; no queue or budget mutation |
| Main invocation/result/accepted output exists under same claim | Reject; do not infer absence from another Run name |
| Exact decision already consumed | Same result, no second dispatch or accounting change |
| Old optional fields absent | Identical nested bytes, digest and old record key |

## Schema and verification targets

- New `structured-pre-admission-pause.schema.json` equals the new raw model schema.
- Update knowledge-invocation-outcome and every embedded copy of that model.
- Update canonical engineering-wait-resolution, console-operation and stopped-budget
  settlement schemas plus their generators; preserve all existing allOf guards.
- Extend exact RESUME_UNINVOKED guards for one and only one proof family. Existing
  verifier/capacity/knowledge-local-limit rules remain unchanged.
- Do not alter the legacy structured-observation or knowledge-execution-record union.
- New None fields use `Field(exclude_if=...)`; validate real old wire/key replay, not only
  standalone `to_wire()` output. Existing global historical validators do not require new facts.

Required commands: focused real preparation/wait regression and negative/lineage cases,
relevant existing knowledge/structured/wait tests, generated-Schema guards, Ruff/format,
strict Mypy, and a separate isolated-MySQL public consumption/claim test owned by root.

## Existing data, authority and rollback

No production SQL or historical bytes are edited. No stored empty list is promoted to
this prospective contract. Stored K1 recovery requires its separate reviewed engineering
path and exact actual facts. Product approval remains frozen; receipt evidence grants no
engineering permission and cannot approve QA/Review. Current policy, role permissions and
budget gates still apply. Rollback preserves new typed readers and immutable records and
uses verified controlled deployment, without changing an active role's runtime.
