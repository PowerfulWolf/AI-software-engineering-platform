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

## Separate final-Run draft from complete Task history

The settled `CapturedMutations` is relative to the final Coder Run's input HEAD,
not the original Task base. A Coder may have committed earlier progress before
that UNKNOWN Run. `NativeRecoveryEntry._propose` must preserve **both** facts:

- `GitWorktreeManager.capture_legacy_changes(old, ..., base_revision=Task base)`
  provides the complete Task-base-to-current `RecoveryPlan.capture`, including
  earlier Coder commits and any final dirty work. Its exact patch remains the
  successor seed or required Coder reapply input.
- A separate `capture_legacy_changes(old, ...)` observes HEAD-to-working-tree.
  `require_stopped_unknown_capture(original, full, current)` binds only this
  Run-local patch, index digest and ordered after-file hashes to the immutable
  settlement; every Run-local after-file SHA must also occur in the full capture.
  It checks Task/attempt/HEAD/worktree/branch identity and the full capture's
  original Task base. Deletion or other unsupported mutation remains rejected.

Proposal rechecks the full source after the Run-local capture. The current-facts
gate used at proposal, approval and execution repeats the Run-local capture,
verifies the full plan capture against live source, and rechecks the Run-local
capture again. Existing source reader independently revalidates the sealed
stopped execution and full mutation inventory. No Plan, approval or Task field
is added; old UNKNOWN facts, attempts, budgets and Operation failures remain
unchanged.

| Source / drift | Required result |
| --- | --- |
| Prior committed code, final Run clean (K1: 37 files from Task base, zero Run-local dirty paths) | Retain the full 37-file patch; accept the separately verified empty Run-local capture |
| Prior committed code plus final Run dirty modification | Retain complete final bytes; match Run-local patch/index/after hashes and their inclusion in the full capture |
| Missing final file from full capture, wrong base/HEAD/branch, changed current draft or later writer | Reject before approval/execution; preserve original stop and draft |
| Final Run reverses an earlier commit exactly to the Task-base file, so the full net diff omits its Run-local changed path | The legacy capture gate rejects the index-only difference; a separate exact base-blob proof contract would be required to support it. Never silently drop the stopped mutation |
| Deletion, mode change or ignored-only Run-local mutation not representable by the normal recovery patch | Reject; request a separate authorized recovery contract |

`tests/recovery/test_stopped_unknown_source.py` uses real Git for clean and
dirty final Runs after an earlier commit, and checks tampering and live drift.
No stored data migration is needed. After an idle release, a fresh public
Continue on the same Requirement prepares a new exact Plan; approve that Plan
only after its complete patch and target revision are reviewed. Rollback to the
previous verifier will again refuse this legitimate mixed-history source but
cannot reinterpret UNKNOWN as a successful model result.

### Bounded current-facts observation during authorization

For the standard native stopped-UNKNOWN verifier, one synchronous authorization
gate observes the complete source and target, validates the full plan capture,
then independently observes the complete source and target again. This gives a
fresh before/after observation around capture validation. `authorize()` invokes
that gate both before and after the exact human decision; execution admission
invokes it again. `inspect_current_authorization()` uses the same window and
returns only its second complete observation to the Task builder. The source
reader's own sealed stop, SQL, original execution
and full mutation-inventory checks remain in **each** observation. Capture
verification errors retain their original classification; source or target
drift fails closed. A custom or replaced verifier/inspection method keeps the
original two `facts.validate` calls around capture verification.

Do not nest another two-observation `facts.inspect` on *both* sides of the
capture check for this source. That made one authorization gate traverse and
hash the entire retained workspace four times at the outer layer, and at
least 64 times across the complete K1 approval chain once the source reader's
own repeated inventories were included. The bounded window removes only
those redundant outer passes; it does not cache file hashes across approval,
replace byte observations with metadata, or skip the human-decision fence.
`test_stopped_unknown_authorization_uses_two_fresh_observations_around_capture`
asserts the exact observation/capture/human ordering and rejects drift during
capture; `test_stopped_unknown_custom_inspection_keeps_original_authorization_gate`
guards extension behavior. No old Requirement, Task, Operation or approval
needs migration. Deploy at an idle service boundary; rollback restores the
slower repeated observations without rewriting any saved fact.

### Sealed Task to MySQL dispatch admission

`RecoveryAllocator.allocate()` obtains one `require_current_draft()` result:
the stored Task record, approved authorization and freshly derived draft are
checked together before the workforce snapshot is seeded. Inside the MySQL
global reservation transaction, `validate_current` runs both before allocation
preview and immediately before commit. Each call rereads the durable Task
record and its exact plan/authorization binding **before and after** one fresh
complete native source/capture observation, comparing those facts with the
initial draft. The SQL transaction still rechecks current workforce, Task and
reservation facts; no prior Python snapshot substitutes for that fence.

For the same standard builder object held by both allocator and sealing, with
standard `build` and `validate_current_against` methods, this avoids rederiving
the same frozen Task on each fence while retaining source freshness. The seam
guard is reevaluated at each MySQL validation callback. A separately injected
builder, subclass or replaced builder/sealing method uses the original full
rebuilding path so an extension's stronger checks are never bypassed. A changed stored
record, approval SHA, source body or current facts rejects dispatch without a
commit. The offline allocation regression asserts 16 complete fact observations
and four capture checks rather than the previous 32/eight, with separate
second-fence drift, stored-record tamper, separate-builder and no-op-validator
negatives.
Existing immutable records and SQL rows need no migration. Publish only at an
idle service boundary; rollback restores repeated derivation and cannot undo
an already committed dispatch.

### Claimed first Coder invocation admission

`RecoverySeedService.seed()` keeps its full sealed-Task rebuild before touching
the target worktree. After a seed receipt exists, `authorize()` still checks
the exact Coder request, Context, clean/seeded target capture, absence of an
earlier invocation and the current Worker claim under `write_scope`. For the
same standard store and sealing/builder methods, its final pre-publication
gate reads the sealed Task record and verifies exact plan/approval binding,
matches the committed dispatch Task/request/record SHA, performs one complete
fresh native source/capture observation, then rereads the sealed record. The
native inspection itself preserves its two observations around capture; the
seed receipt does not grant source freshness. A custom sealing method or a
different injected store retains the original full `require_current` rebuild.

This avoids a second deterministic Task derivation at the claimed invocation
boundary: the offline role-admission regression changes from eight fact
observations and two capture checks to four facts and one complete capture
check, while retaining the same lease and at-most-once publication
checks. Stored-record tamper, changed source and custom-gate tests must leave
the invocation absent. No new stored field or SQL migration is needed; publish
at an idle boundary, with rollback restoring the slower full rebuild.

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
