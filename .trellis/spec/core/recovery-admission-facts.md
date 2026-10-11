# Synchronous authorized recovery facts

## Scope and signatures

The native Task builder formerly inspected complete current facts five times: twice
around its first capture check, once solely for deterministic derivation, and twice
around its final capture check. Return the first authorization gate's final fresh facts
and remove only the middle inspection. This is local typed data, not an execution token,
an approved Task, or permission to reuse facts at another admission boundary.

```python
@dataclass(frozen=True)
class AuthorizedRecoveryFacts:
    plan: RecoveryPlan
    facts: NativeRecoveryFacts

class _AuthorizedRecoveryFactsInspector(Protocol):
    def inspect_current_authorization(self, plan_sha256: str) -> AuthorizedRecoveryFacts: ...

RecoveryAuthorizationService.inspect_current_authorization(plan_sha256: str) \
    -> AuthorizedRecoveryFacts
RecoveryAuthorizationService.require_current_authorization(plan_sha256: str) -> RecoveryPlan
RecoveryAuthorizationService._task_facts_inspector(verifier: NativeRecoveryFactsVerifier) \
    -> _AuthorizedRecoveryFactsInspector | None
AuthorizedRecoveryTaskBuilder.build(plan_sha256: str) -> RecoveryTaskDraft
```

The new result and Protocol are internal Python composition contracts. They are not
exported as a Skill/tool/JSON Schema, persisted, given to an Agent, or accepted as approval.
The service owns its inspector. Callers cannot provide a prevalidated result or a boolean
that skips validation. The selector enables reuse only for the exact current
`NativeRecoveryFactsVerifier` class, shared by the service and builder as the same instance.
Reuse also requires the actual bound `validate` method to have this same verifier as
its receiver and the original `NativeRecoveryFactsVerifier.validate` delegate as its
function. Compare against its definition-time private function reference, not the
currently replaceable class attribute. The authorization service must also have the exact
standard class and both actual `require_current_authorization` / `_require_current`
bindings must match their original definition-time functions and this same receiver.
Instance/class overrides, a method bound to another port, and subclass overrides
retain the original validation path. The standard delegate runs the complete `inspect`.

Production seams are `src/ai_software_engineer/recovery/service.py` and
`src/ai_software_engineer/recovery/task.py`; durable approval and Task record formats
remain in the unchanged recovery models/store/sealing contracts.

## Freshness and compatibility contracts

Every typed gate freshly opens the original Plan and authority using the unchanged store
path/directory/envelope/digest checks, requires the exact APPROVED decision, and validates
Plan integrity and supported execution. It runs complete native facts inspection before
capture verification and again afterward, returning the latter result. Each native
inspection still independently observes all facts twice and compares them. Neither the
original capture sandwich nor any source/SQL/Git/lease/process/stop/inventory check changes.

The supported builder derives a Task synchronously from the returned Plan and facts, then
repeats the entire authorization gate. Before returning the draft it compares the second
Plan and the complete `NativeRecoveryFacts` with the ones used for derivation. A stable
new fact set that differs from the first gate rejects even when Plan digest is unchanged.
Task derivation, source lineage, permissions, budgets, metadata and wire fields are unchanged.

`require_current_authorization` retains its original complete `_require_current` path;
every service runs its original two `validate` calls around capture verification, including
trusted stronger service/facts implementations. Only the supported builder selects the
separate typed gate. The new typed method rejects unsupported ports rather
than inventing native facts. A subclass or instance-specific stronger `validate`, or a builder using an
independent verifier instance, follows the original complete
`require -> builder.inspect -> require` path. That compatibility path retains its existing
Plan comparison; do not claim it gains the native same-instance final complete-facts
comparison. Changing a custom port's policy requires a separate contract change.

Facts are not cached across builder calls, callbacks, dispatch transactions, seed checks,
claimed execution or model calls. The immutable-record decode scope is a separate reading
optimization and does not establish current facts or authority.

## Validation matrix and test points

| Case | Expected result |
| --- | --- |
| Exact native service and builder share one verifier and its standard bound validate delegate | Four inspect calls / eight underlying observations; both capture checks; same Task wire as compatibility path |
| Actual public approve plus one seal | Eight authorization observations plus eight builder observations = 16; every authority read remains fresh |
| Plan stays identical but complete native source/target/profile/baseline changes during derivation | Final complete-facts comparison rejects; no replacement Task or receipt |
| Receipt, Plan bytes, directory identity or live capture body changes mid-derivation | Original fresh gate rejects; retain existing records and mutation evidence |
| Capture callback changes current source | Fresh facts-after rejects; no draft publication |
| Unsupported/subclass/instance/class stronger validate or service authorization port | Typed method rejects; public authorization and old builder path preserve all stronger validation calls |
| Equivalent independent native verifier | Original five-inspection builder path and unchanged output |
| OfflineAuthority first allocation / replay | Four builders × eight observations = 32 / three builders × eight = 24; getters, eight/six captures and both transaction fences unchanged |
| Changed complete body at the second dispatch fence | Reject; no committed dispatch or skipped current check |
| Missing/rejected authority or absent Task record | Reject; no authority, Task record, claim or model output fabricated |

`tests/recovery/test_authorized_facts.py` uses the actual authorization service, builder,
file store, sealing and OfflineAuthority. Only native facts acquisition and captures use
existing deterministic fixtures; these tests do not establish complete production SQL/Git
performance. Existing preparation/record-read tests keep their full getter, capture, scan,
scope and mutation checks and synchronize only the exact changed observation counts.
Timing or RSS assertions are not portable acceptance criteria.

Good: the standard native service and builder share one verifier, derive the identical
Task wire using four complete inspections, and refuse any final complete-facts drift.
Base: a generic, independent or stronger custom verifier retains the original full
compatibility path. Bad: use exact class identity alone to skip an instance-specific
stronger `validate`, or carry an earlier local facts result into a dispatch/seed claim.

## Existing data, deployment and rollback

存量数据处置：no Schema, MySQL, journal, Requirement, Task, approval, metadata, artifact or
workspace migration. Preserve all identities, prior events, failure history, hashes and
retained drafts. This change neither grants approval nor resumes an interrupted operation.
Once existing authorized workers are idle, load the version through ordinary controlled
maintenance; continue the original Requirement via its existing public exact approval/
continue action when appropriate. Do not manufacture records, reset counters or create a
duplicate Requirement to load this optimization.

Rollback reverts the local typed result/selector and restores the redundant middle facts
inspection. Existing durable bytes remain compatible and complete gates continue to run.
Deploy or roll back only after active workers end.

## Deferred wider optimization

Reducing multiple independent builders/transaction gates into a larger observation window
would require a separate typed coherent gate protocol and analysis of callback mutation,
SQL transaction fences, source/target epochs and eventual real claim admission. It is not
implemented here. A local reduction from five inspections to four is not evidence of
production end-to-end latency or a promise that all recovery is fast.
