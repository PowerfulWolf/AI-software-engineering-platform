# Implementation record

## Changes

- `agents/execution.py`, `work_queue/ports.py` and `work_queue/worker.py` carry bounded trusted
  lease-authority abort facts. `codex_cli.py` records the real native stop and optional abort
  reason before lost authority propagates; it does not publish a fenced result.
- `manager/stopped_execution_checkpoint.py` validates exact start/capture/claim/session identity.
  `baseline_production.py` collects that proof separately from known-cause receipt reconciliation
  and verifies it again under the existing Task lock and idle SQL fence.
- Domain, baseline models/service/store and queue consumption support
  `purpose=stopped_execution_rescue`, `stopped_execution_sha256` and ordinary next-work reservation.
  Execution preserves source and inventory, requires explicit engineering PAUSE, and reuses the
  existing exact separate baseline release for RESUME.
- Historical traversal verifies approved stopped-proof lineage without inventing the original
  result or receipt. Legal heartbeat extension of the historical lease expiry does not change
  its exact identity; original claim fields and capture scope still bind.
- `ReplayGuardedClaimObservation` covers a real extra claim that completed read-only `RETURNED`
  knowledge preparation behind an existing unknown invocation. This is a current investigation
  observation, not a newly manufactured historical refusal event. It binds exact extra claim,
  original Context and complete knowledge execution digests to the unique earlier write-once
  start, with strict time/dispatch ordering and same WorkItem/role/attempt/checkpoint/source.
  The original call still requires its independent containment; complete scans reject any new
  main native capture, route, raw artifact or receipt attributable to the reclaimed claim.
  `BaselineInvocationProof.replay_guarded_claims` records the exact observations in the existing
  `BaselineQuiescenceProof` record, with no refund, future event family or old-record rewrite.
- `EngineeringHumanActionRecorder` seals one `SUPPLY_EVIDENCE` event per binding, pointing to
  the exact operator authority. Evaluation continues to classify this as human-assisted delivery.
- Console contract version 9 and the browser stopped-run card expose target-free preparation,
  exact paused approval and normal separate continuation. Old services and stale controls refuse.
- Schema synchronizers retain enclosing wire guards while updating nested rescue, capture and
  owned-session definitions. Generated schema edits are part of the maintenance allowlist.

## Tests introduced

`tests/agents/test_guard_abort_native.py` uses a real guarded subprocess and actual local expiry,
checks owned-session cessation, retained draft and no result publication. The manager proof matrix
checks unknown historical stop fixtures, bad/foreign/missing session or output facts, no refund,
same-source PAUSE and exact digest/immutability constraints.

`tests/manager/test_stopped_execution_delivery.py` creates a real native Coder claim in isolated
MySQL, shortens its lease through normal queue renewal, lets the actual native clock guard expire
and observes a negative child exit with complete stop proof. Ordinary Console continuation first
reclaims the expired lease, then a fresh claim discovers the unknown outcome and enters engineering
wait. The public proposal/PAUSE/RESUME path must then keep the same Task/worktree/branch/draft,
consume one ordinary attempt and deliver through distinct native Coder, QA and Reviewer claims.
It inspects same-candidate immutable reports, original missing outcome/receipt, unchanged old bytes,
static schemas, one human evidence event and ADR recomputation. Offline model responses are test
adapters; QA and Review execute independent real Git inspections and save evidence.

## Bug found by the public fixture

The first real public proposal reached `DeliveryWaitFactCollector` and tried to reconcile an old
interruption receipt. `cause=null` correctly made that route refuse with `ContinuationRejected`.
The new purpose now selects its own trusted stopped-proof collector before any receipt path.
This preserves the old reconciliation gate for known interruption recovery and leaves the unknown
history honest. The corrected end-to-end outcome is recorded separately after actual execution.

The subsequent real public run exposed a second classification gap: ordinary Continue first
reclaimed the expired WorkItem, completed knowledge preparation and was correctly prevented from
calling Coder by the original unknown start. The old baseline collector treated every nonoriginal
claim as a failed/preflight claim and demanded a receipt that did not exist. The unified current
replay-guarded observation validates that exact mandatory fence plus complete returned preparation
and fresh negative scans. It does not reinterpret `RETURNED` as `FAILED`, ignore arbitrary extra
claims or backfill a past `prepare()` refusal. The public fixture keeps the naturally absent
historical marker and asserts exact later-claim/start binding plus unchanged original bytes.

## Existing data and rollback

No SQL migration or direct data patch is planned. The existing K1 must first have no active lease,
valid owned-session-empty stop, no result/output and complete legal unchanged draft. An expired
RUNNING lease may need ordinary dispatcher reclamation and a subsequent ordinary claim to enter
`EXECUTION_UNCERTAIN`; no new Coder call is permitted in that ordinary unknown-result check.
Then submit public exact proposal, approve PAUSE, inspect the preserved successor and separately
RESUME. Keep original Product approval, Task intent, frozen permissions, old unknown Run and all
stop bytes. Native QA and Review remain mandatory.

Only the root maintenance task records production operation IDs and the actual result after
deployment. Rollback pauses/drains execution and keeps compatible readers plus all newly appended
proof/authority/binding/audit records. Never erase an immutable record or draft to make an older
binary accept the state.

## Console race found during production recovery

`loadCurrentOperationDetails` cleared readiness on every unchanged poll while leaving the current
enabled button visible. `deliveryButton` then silently returned; a second path rejected the exact
approval because full Task JSON included changed read-side locators/timestamps. The correction keeps
only already verified same-scope cached readiness until an actual inventory/cache change or read
failure, waits for the same-scope pending read before fresh write checks, and projects only the three
baseline actions through the explicit read-side field exclusions. New/unknown authority fields
remain compared. The shared button wrapper now explains unavailable control.

The focused VM tests cover successful overlap, failed reads, 15 real authority changes and visible
refusal. The real Chrome test reads/approves three native-rule changes and overlaps an idle refresh
with fresh full-plan reading, then observes one original PAUSE intent. No durable operation or
approval migration is required. Production assets are cached by transport construction; deploy this
follow-up only at a safe maintenance boundary, then refresh the original Requirement.
