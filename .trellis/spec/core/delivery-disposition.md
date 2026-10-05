# Delivery disposition and recoverable waiting

## Scope and signatures

New Tasks freeze organization engineering authority. One deterministic decision contract is shared
by the execution router, Manager coordination and read projection. It supplements existing
specialized proof validators; a disposition never grants permissions or changes a verdict.

```python
decide_delivery_disposition(facts: DeliveryFailureFacts) -> DeliveryDisposition
DeliveryFailureControl.wait(task, classification, reason, source_revision, artifact_ids) -> None
WorkerLease.wait_for_delivery(disposition, *, now) -> None
queue.wait(..., disposition: DeliveryDisposition | None = None) -> QueuedWorkItem
queue.make_ready(..., expected_disposition_sha256: str | None = None) -> QueuedWorkItem
```

## Contracts

- Failure cause, preserved work, authorization and next action are different facts. Ordinary
  provider retry and QA/Review remediation use existing new-Run/budget/claim services.
- Required business decisions belong to product. Execution uncertainty, missing evidence,
  environment, source preparation and unsupported capability belong to engineering. Queue waiting
  records actual responsibility, a stable cause, exact input facts and a typed resume condition.
- A recoverable wait preserves Task phase/revision; its owner-fenced queue transition releases the
  Lease. No StageEvent or role verdict is fabricated. Only explicit termination, true policy
  violation or terminal budget exhaustion becomes BLOCKED.
- Unknown invocation is not free retry. No receipt/admission may be rebound merely because its
  Lease expired. Resumption requires a fresh, exact application-verified engineering resolution;
  new invocation consumes its frozen budget and new Run/Context/claim.
- Existing policy-less Task/queue bytes remain valid and do not gain authority. Durable old
  failure history is never rewritten. Text-only legacy waits retain their specialized validators.
- Product UI consumes the durable disposition; "engineering" does not claim an administrator or
  model is actively working without assignment/execution facts. Current phase, execution state,
  responsible duty and next action remain separate.

## Validation matrix

| Facts | Decision |
| --- | --- |
| Typed provider failure, eligible budget | Existing bounded retry, new identities |
| QA FAIL / Review REJECT, eligible work budget | Existing Coder remediation with exact findings |
| Business ambiguity | Product decision wait, lease released, checkpoint retained |
| Environment unavailable / required evidence missing | Engineering dependency wait |
| Execution outcome or owned-process stop unknown | Engineering investigation wait, no invocation |
| True denied mutation / terminal budget exhaustion | Terminate with evidence and retained history |
| Wrong/foreign/stale resume signal or changed facts | Reject without queue/Task/model change |

Good: UI and Manager explain the same sealed waiting facts and a fresh verified signal resumes.
Base: legacy knowledge receipts retain exact scope/route/resolution checks.
Bad: UI hides a technical approval while backend still silently waits for product; or a free-text
message/Lease expiry resumes unknown native execution.

## Tests and rollout

Incremental domain, queue, native public entry, Manager and DOM regressions must cover exact
responsibility, nonterminal checkpoint, released lease, signal refusal and restart idempotency.
The two deleted K1 identities must remain retired; no production business work is started.
Retain new receipt/policy readers on rollback and deploy only while idle.
