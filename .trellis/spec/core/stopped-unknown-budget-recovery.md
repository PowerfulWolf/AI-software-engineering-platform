# Exhausted stopped UNKNOWN execution recovery

## Scope and signatures
A complete owned-session-empty stop, even completed/returncode0 with output present, does not
establish a final model outcome. After genuine frozen ordinary-budget exhaustion there is no
remaining same-Task work authority. Public HANDLE may settle this exact wait into BLOCKED
without manufacturing the missing result or increasing the frozen budget. The existing
Requirement is preserved and its successor execution requires a new exact RecoveryPlan approval.

- `StoppedUnknownBudgetSettlement`: independent immutable pre-task/investigation/WorkItem/step/
  stopped-proof/capture/inventory/event contract; never a failed-outcome subclass.
- `StoppedUnknownBudgetSettlementService.try_settle(...)`: caller holds exclusive Task lock and
  idle SQL authority scope; returns a BUDGET_EXHAUSTED DeliveryWaitHandling or no applicable path.
- `MySqlRoleQueue.settle_stopped_budget(cursor, settlement)`: typed strict settlement union,
  atomic exact Task+event+CLOSED queue CAS, no current ACTIVE claim or accepted publication.
- `RecoverySource.stopped_unknown_settlement_sha256`: optional exact new source discriminator;
  omitted historical field preserves wire and digest.
- Dedicated source reader: validates original proof with the pre-terminal snapshot, then exact
  terminal reducer/closed item and full current facts; ordinary failed-route reader stays strict.

## Contracts
Preserve original invocation/stop bytes, unknown outcome, attempts, retry policy and all approved
product scope. Require unique waiting Coder, IMPLEMENTING, work_budget_exhausted, exact source/
permissions/context/claim, genuinely empty original session and no outcome/route/raw artifact/
continuation receipt or later conflicting publication. Full retained capture must cover the
complete legal source inventory with unchanged HEAD/index/branch and repeated freshness checks.
Never classify zero exit/file presence as success or capacity/pre-provider non-invocation.

Seal the decision and full retained capture before SQL consumption; make recovery from crashes
idempotent. Replays compare exact event, Task reducer, queue closure and seal. No refund or
new attempt is written to the old Task. Event reason states BUDGET_EXHAUSTED and UNKNOWN.

Only a newly approved exact same-Requirement RecoveryPlan grants a successor Task budget.
Target source revision/native rules and permissions are rechecked under existing engineering
authority; preserve complete transitive reapply inputs. Coder adapts the full old draft against
a clean approved base. Independent QA/Reviewer verdicts remain mandatory for the same candidate.
Public GET cannot settle, create receipts or authorize work. Physical deletion validates and
removes the new exact typed settlement/capture/handling groups with the Requirement.

## Validation and error matrix
| Input | Behavior |
| --- | --- |
| Exact v1/v2 stop, no final facts, exhausted budget, full lawful draft | One audited terminal settlement; new recovery proposal |
| Budget available | No terminalization; existing same-Task path |
| Any active claim/live or unverifiable process, late outcome/route/artifact/receipt | Refuse with retained original facts |
| Source/context/permissions/HEAD/index/inventory/parent drift | Refuse without state or budget change |
| Same command replay after crash/commit | One event and closure, no new debit |
| Historical source without new field | Original bytes/digest and strict ordinary path |
| New exact recovery approved | Same Requirement successor using new claim/Run/Context |
| Old approval, absent full patch, real verification unavailable | Refuse or WAIT_ENGINEERING; never fabricated verdict |

Good: exhausted old UNKNOWN Task ends honestly and exact recovery continues original Requirement.
Base: existing failed-stop settlement and terminal failed route remain strict. Bad: add an
unbounded same-Task budget overlay, rewrite old outcome, force an unexhausted Task terminal.

## Existing data and rollback
K1 attempt11/work_attempt10-of10 has a valid v2 stopped proof with no invocation outcome.
The rejected same-Task proposal is expected and remains in history. After reviewed release use
fresh public INSPECT/HANDLE, then same-Requirement recovery plan and exact delegated approval.
No SQL repair, new Requirement or retroactive product approval is needed. Before consumption
revert the maintenance commit; afterward retain compatible readers and controlled pause and
never erase new records to satisfy an old runtime.


## Producer ordering and regression commands
The specialized exact UNKNOWN settlement is tried before generic interruption receipt
reconciliation. A valid v2 stop has cause=None/output_present=true and cannot produce a normal
interruption receipt; running reconciliation first would incorrectly return PLATFORM_ATTENTION.
The new branch grants no ordinary retry or candidate acceptance. Remaining-work UNKNOWN Tasks
still use the original same-Task stopped rescue and cannot be administratively terminalized.

Relevant tests: tests/manager/test_stopped_unknown_budget.py (v1/v2, crash replay and final late
facts), tests/manager/test_stopped_unknown_budget_public.py (real native/Git/MySQL same-Requirement
latest-main recovery through independent DONE and final SQL rejection), tests/recovery/test_stopped_unknown_source.py
and test_stopped_unknown_schema.py (source, audit and published/fresh guards),
tests/contracts/test_stopped_unknown_budget_schema.py and
tests/manager/test_stopped_unknown_budget_deletion.py (exact schema and physical cleanup).
Run MySQL test groups serially against an identity-checked dedicated test database.

The current normal legacy recovery capture supports regular modifications/additions; deletion
and mode-change drafts remain sealed but are refused by this successor path. No new unsupported
capture behavior is inferred from a complete stopped mutation inventory.
Both historical and ordinary recovery capture may span at most 2,000,000 bytes
of changed current file bodies, because seed verification and target observation
reuse the ordinary path. The 1,000,000-byte per-file and patch bounds remain;
see `delivery-recovery.md`. A previously settled UNKNOWN Task
whose larger draft was rejected during proposal generation remains settled.
After an idle release, use a new public recovery proposal/approval against the
same Requirement; neither replaying the old handling nor extending its budget
is required.

## Public wait settlement and recovery operation boundary

`TeamHost.handle_delivery_wait` returns the durable `BUDGET_EXHAUSTED` handling
after the stopped UNKNOWN Task and queue have been settled. It must not call
`_resume_delivery_once` to propose a successor in that same Console Operation:
proposal failure would otherwise mark the successful settlement as a failed
HANDLE operation. `TeamHost.resume_delivery` may automatically handle one
engineering wait, but only a `RESOLVED` handling permits a second continuation
in that call. A budget settlement leaves the original continuation result for
the caller to refresh from durable Requirement/Task facts; the next public
Continue prepares the separately approvable recovery plan. Exact replay of an
already sealed settlement remains idempotent and does not retry the proposal.

| Durable handling | `TeamHost.handle_delivery_wait` | `TeamHost.resume_delivery` |
| --- | --- | --- |
| `RESOLVED` | Return handling after one continuation | Continue a second time after the handled wait |
| `BUDGET_EXHAUSTED` (including exact replay) | Return sealed handling without proposing recovery | Return the first continuation result; require a new public Continue for the plan |
| Still waiting | Return current handling | Return the first continuation result |

`tests/manager/test_team_host.py` asserts both budget paths never invoke the
second continuation and keeps the `RESOLVED` one-time path. The existing
`operation_6b17db82053bcc55cca1680c14fb1927` failure remains historical;
this code does not rewrite its status, Task or approval. A new public Continue
uses the current Requirement checkpoint and exposes a separately reviewable
plan. Rollback at an idle boundary restores the old coupling and may again
misreport a settled handling if proposal generation fails; it cannot undo the
sealed settlement.

## Read-side reference publication and legacy exact replay

The UNKNOWN settlement/capture store is `delivery-preflight`, while complete Team
history reopens `delivery-waits/wait-investigations` independently from its handling.
Both initial handling and fully verified exact replay must publish the original
immutable investigation there before `wait-handlings`. An embedded proof alone
does not satisfy that reference. Do not weaken the reader or return partial Team
data when it is missing.

A released omission could settle the Task correctly but make summary/detail return
503 because only the handling was published. Restore this exact missing reference
through a new public HANDLE operation with the original command fingerprint and
current parent checkpoint. Replay must first reverify the settlement, terminal
reducer, queue closure, stopped process and full retained capture; then append the
unchanged original proof. Existing Task attempts/events, result bytes and history
remain unchanged. Existing conflicting/corrupt records fail closed and are never
overwritten. Reusing the old Console idempotency key only reads its cached result
and does not execute this repair.

Regression: `test_unknown_handling_publishes_complete_read_only_history_and_repairs_exact_replay`
executes the real initial/replay producer and complete `engineering_history` reader
for v1/v2 stop facts, including the historical missing-reference state.
